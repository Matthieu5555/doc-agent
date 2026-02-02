#!/usr/bin/env python3
"""
Three-Tier Autonomous Documentation Generator using OpenHands SDK

Architecture:
  Tier 0 — Scout Agents (Devstral × 3-5):
    Explore the repository in parallel-ish passes, producing structured
    intelligence reports about structure, architecture, APIs, infra, tests.

  Tier 1 — Planner (Kimi K2 Thinking × 1):
    Pure reasoning call (no tools). Reads scout reports and designs the
    optimal documentation architecture: what documents, what sections,
    what format (diagram/table/prose/code) best serves each piece of info.

  Tier 2 — Writer Agents (Devstral × 1 per document):
    Each receives a focused brief from the planner plus relevant scout
    reports and writes one document in flowing professional prose.

Usage:
    doc-agent --repo https://github.com/user/repo
    doc-agent --repo https://github.com/user/repo --collection backend/
"""

import json
import os
import re
import sys
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# OpenHands SDK imports
from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.sdk.llm import Message, TextContent
from openhands.sdk.context.condenser import LLMSummarizingCondenser
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool
from openhands.tools.terminal import TerminalTool

# Document registry for ID-based tracking
from doc_agent.registry import (
    generate_doc_id,
    find_document_by_id,
    create_document_with_metadata,
    DocumentRegistry,
    parse_frontmatter,
    parse_bottomatter,
)

# API client for posting to backend
from doc_agent.api_client import DocumentAPIClient

# Version priority logic for intelligent regeneration
from doc_agent.version_priority import VersionPriorityEngine

# Security modules
from doc_agent.security import RepositoryValidator, PathValidator

# Model constraint resolution
from doc_agent.model_config import resolve_model_config

# ---------------------------------------------------------------------------
# Model Configuration
# ---------------------------------------------------------------------------
# Global defaults — override per-tier with SCOUT_BASE_URL, PLANNER_API_KEY, etc.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENROUTER_API_KEY")
LLM_NATIVE_TOOL_CALLING = os.getenv("LLM_NATIVE_TOOL_CALLING", "true").lower() == "true"

SCOUT_MODEL = os.getenv("SCOUT_MODEL", "")
PLANNER_MODEL = os.getenv("PLANNER_MODEL", "")
WRITER_MODEL = os.getenv("WRITER_MODEL", "")


def _resolve_api_key(tier: str) -> str | None:
    """Resolve API key: tier-specific → global → Docker secrets."""
    key = os.getenv(f"{tier}_API_KEY") or LLM_API_KEY
    if not key:
        key_file = os.getenv("OPENROUTER_API_KEY_FILE")
        if key_file and os.path.exists(key_file):
            with open(key_file) as f:
                key = f.read().strip()
    return key


def _llm_kwargs(tier: str) -> dict:
    """Build LLM constructor kwargs for a tier with fallback to globals."""
    base_url = os.getenv(f"{tier}_BASE_URL") or LLM_BASE_URL
    api_key = _resolve_api_key(tier)
    kwargs = {"base_url": base_url}
    if api_key:
        kwargs["api_key"] = api_key
    return kwargs

# ---------------------------------------------------------------------------
# Document Type Taxonomy (used for fallback and keyword tagging only —
# the planner is free to create any page structure it wants)
# ---------------------------------------------------------------------------
DOCUMENT_TYPES = {
    "quickstart": {"title": "Quick Start", "keywords": ["Getting Started", "Installation"]},
    "overview": {"title": "Overview", "keywords": ["Overview", "Introduction"]},
    "architecture": {"title": "Architecture", "keywords": ["Architecture", "Design"]},
    "api": {"title": "API", "keywords": ["API", "Reference", "Endpoints"]},
    "guide": {"title": "Guide", "keywords": ["Guide", "How-To"]},
    "config": {"title": "Configuration", "keywords": ["Configuration", "Deployment"]},
    "component": {"title": "Component", "keywords": ["Component", "Module"]},
    "data-model": {"title": "Data Model", "keywords": ["Data", "Schema", "Model"]},
    "contributing": {"title": "Contributing", "keywords": ["Contributing", "Development"]},
    "capabilities": {"title": "Capabilities & User Stories", "keywords": ["Capabilities", "User Stories", "Features", "Use Cases"]},
}

COMPLEXITY_ORDER = {"small": 0, "medium": 1, "large": 2}

# ---------------------------------------------------------------------------
# Shared Prompt Components
# ---------------------------------------------------------------------------

PROSE_REQUIREMENTS = """
WRITING STYLE (ABSOLUTELY MANDATORY):

Write professional, concise technical documentation. Each page should be
SHORT — 1-2 printed pages maximum. Think wiki page, not book chapter.

Use flowing prose paragraphs of 2-4 sentences. Use transition words to
connect ideas. NEVER use bullet points or dashes for descriptions — weave
items into sentences. Code blocks and tables are acceptable but surround
them with brief explanatory prose.

If a topic is too large for 1-2 pages, split it into sub-pages and link
to them with [[wikilinks]]. Prefer many small focused pages over few
large ones.
"""

TABLE_REQUIREMENTS = """
GFM TABLES (use when they aid comprehension):

Use GitHub-Flavored Markdown tables for structured data: endpoint summaries,
config options, comparison matrices, dependency lists, component tables.
Every table needs a header row and separator (|---|---|).
Not every page needs a table — use them where they genuinely help.
"""

DIAGRAM_REQUIREMENTS = """
MERMAID DIAGRAMS (use where visual relationships matter):

Use ```mermaid code blocks. Choose the right type:
  graph TB/TD: for architecture, component relationships
  sequenceDiagram: for request flows, data pipelines
  stateDiagram-v2: for stateful entities
  erDiagram: for data models

Include a brief caption sentence. Not every page needs a diagram — use
them on architecture, flow, and data model pages where they genuinely
clarify relationships.
"""

WIKILINK_REQUIREMENTS = """
WIKILINKS (THIS IS THE MOST IMPORTANT REQUIREMENT):

Use [[Page Title]] syntax to build a densely interconnected knowledge graph.
Wikilinks are what make this feel like a human-crafted wiki, not AI output.

INLINE WIKILINKS — EMBEDDED NATURALLY IN PROSE (this is the primary form):
  Weave links into sentences where a reader would naturally want to drill
  deeper. Examples of GOOD inline wikilinks:
    "The [[Document Service]] validates input before delegating to the
     [[Document Repository]] for persistence."
    "Authentication is handled via JWT tokens, as described in
     [[Authentication Flow]], and configured through [[Environment Variables]]."
    "This component follows the [[Repository Pattern]], abstracting all
     database queries behind a clean interface."

  BAD wikilinks (don't do this):
    "See [[Architecture]] for more." — lazy, tells the reader nothing
    "Related: [[X]], [[Y]], [[Z]]" — dumping links without context

  The key test: would a human editor naturally hyperlink this word?
  If the reader would think "what's that?" or "tell me more", it's a link.

RULES:
  - Link significant nouns the FIRST time they appear in each section
  - Every service, component, pattern, technology, and config concept
    that has its own page should be wikilinked where it's mentioned
  - DON'T over-link: same word linked twice in one paragraph is too much
  - DON'T dump links: a list of bare [[links]] with no prose is useless

DO NOT ADD A "SEE ALSO" SECTION. EVER.
  No "## See Also", no "Related pages", no link dump at the bottom.
  Every wikilink must be INLINE in prose where it's contextually relevant.
  If a connection matters, it belongs in a sentence. If it doesn't fit
  naturally in a sentence, it's not a real connection — don't force it.
  The dependency graph must reflect genuine relationships, not padding.

EXTERNAL LINKS vs WIKILINKS:
  Use [[Page Title]] ONLY for pages that exist in this wiki (listed in the
  sibling pages section below). For external resources — frameworks, libraries,
  third-party tools, specifications — use standard markdown link syntax:
  [display text](https://url).

  Examples:
    GOOD: "The [[Document Service]] validates input before persistence."
    GOOD: "Built on [FastAPI](https://fastapi.tiangolo.com/) for the backend."
    GOOD: "Uses the [OpenHands SDK](https://docs.all-hands.dev/) for agent orchestration."
    BAD:  "Built on [[FastAPI]] for the backend." — FastAPI is not a wiki page
    BAD:  "Uses the [[OpenHands SDK]] for orchestration." — external, not a wiki page

  RULE: If the concept is NOT in the list of wiki pages provided to you,
  it MUST be a standard markdown link [text](url) with an actual URL.
  Do NOT create wikilinks for external tools, libraries, or resources.
"""


# ---------------------------------------------------------------------------
# Scout Definitions
# ---------------------------------------------------------------------------

SCOUT_DEFINITIONS = {
    "structure": {
        "name": "Structure & Overview",
        "always_run": True,
        "prompt": """You are a repository scout. Your mission: produce a structured intelligence report about the overall structure of the repository at {repo_path}.

{file_manifest}
{constraints}

DO THIS:
1. Read README.md (or README.rst, README.txt) if it exists
2. Read package metadata files marked with ★ above (pyproject.toml, package.json, Cargo.toml, etc.)
3. Note the directory layout from the manifest above — do NOT run `find` or `ls`

Write your report to /tmp/scout_report_structure.md with this format:

## Scout Report: Structure & Overview
### Key Findings
- Project name and description (from README/package files)
- Primary language(s) and framework(s) detected
- Total file count and source file count
- High-level directory layout (what each top-level dir contains)
- Build system / package manager used
- License

### Raw Data
- Directory tree (top 2 levels, derived from the manifest)
- Package metadata summary
- README summary (first ~500 chars)

Be thorough but concise. Facts only, no opinions.""",
    },
    "architecture": {
        "name": "Architecture & Code",
        "always_run": True,
        "prompt": """You are a repository scout. Your mission: produce a structured intelligence report about the architecture and code organization of the repository at {repo_path}.

{file_manifest}
{constraints}

DO THIS:
1. Identify entry points from the ★-marked files (main.py, app.py, index.ts, etc.)
2. Read the main entry point(s) and trace key imports
3. Identify layers: routes/controllers, services/business logic, models/data, utilities
4. Read 3-5 core source files (prefer ★-marked, check sizes before reading)
5. Check for shared types, interfaces, or base classes

Write your report to /tmp/scout_report_architecture.md with this format:

## Scout Report: Architecture & Code
### Key Findings
- Entry point(s) and how the application starts
- Module/package organization (layers, domains)
- Core abstractions: key classes, functions, interfaces
- Design patterns identified
- Dependency flow (what depends on what)
- Database / storage approach (if any)

### Raw Data
- Import graph summary (main entry → what it imports)
- Key file list with one-line descriptions
- Notable code patterns with file references

Be thorough but concise. Facts only, no opinions.""",
    },
    "api": {
        "name": "API & Interfaces",
        "always_run": True,
        "prompt": """You are a repository scout. Your mission: produce a structured intelligence report about the APIs and public interfaces of the repository at {repo_path}.

{file_manifest}
{constraints}

DO THIS:
1. Read ★-marked files — these likely contain route/endpoint/schema definitions
2. Use grep to find route definitions if needed: grep -rn "@app\\|@router\\|HandleFunc" --include="*.py" --include="*.ts" --include="*.go" . | head -30
3. Read API route files to understand endpoint signatures (check sizes first!)
4. Look for OpenAPI/Swagger specs, GraphQL schemas, or protobuf definitions
5. Check for authentication/authorization middleware

Write your report to /tmp/scout_report_api.md with this format:

## Scout Report: API & Interfaces
### Key Findings
- API style (REST, GraphQL, gRPC, CLI, library)
- Authentication mechanism (JWT, API key, OAuth, none)
- Number of endpoints/routes found
- Key request/response models
- Error handling approach

### Raw Data
- Endpoint table: Method | Path | Handler | Auth Required
- Schema/model list with field summaries

If the project has no API (e.g., it's a library or CLI tool), document the public interface instead: exported functions, classes, CLI commands.

Be thorough but concise. Facts only, no opinions.""",
    },
    "infra": {
        "name": "Infrastructure & Config",
        "always_run": False,
        "prompt": """You are a repository scout. Your mission: produce a structured intelligence report about the infrastructure and configuration of the repository at {repo_path}.

{file_manifest}
{constraints}

DO THIS:
1. Read ★-marked files — these are the infrastructure and config files
2. Read Dockerfile(s), docker-compose.yml if present
3. Read CI/CD configs (.github/workflows/, etc.)
4. Read .env.example or .env.template if present
5. Check for deployment configs (Kubernetes, Terraform, Procfile)

Write your report to /tmp/scout_report_infra.md with this format:

## Scout Report: Infrastructure & Config
### Key Findings
- Containerization approach (Docker details)
- CI/CD pipeline description
- Environment variables required
- Deployment strategy
- External service dependencies

### Raw Data
- Dockerfile summary (base image, stages, exposed ports)
- docker-compose services table: Service | Image | Ports | Dependencies
- CI/CD pipeline steps
- Environment variable table: Variable | Purpose | Required | Default

Be thorough but concise. Facts only, no opinions.""",
    },
    "tests": {
        "name": "Tests & Quality",
        "always_run": False,
        "prompt": """You are a repository scout. Your mission: produce a structured intelligence report about the testing and quality setup of the repository at {repo_path}.

{file_manifest}
{constraints}

DO THIS:
1. Review ★-marked files — these are test files and test configs
2. Read 2-3 test files to understand patterns (check sizes first!)
3. Look for test configuration in the manifest: pytest.ini, jest.config.*, conftest.py
4. Check for linting/formatting configs: .eslintrc, ruff.toml, pyproject.toml [tool.ruff]

Write your report to /tmp/scout_report_tests.md with this format:

## Scout Report: Tests & Quality
### Key Findings
- Test framework(s) used
- Test file count and organization
- Testing patterns (unit, integration, e2e)
- Code quality tools (linters, formatters, type checkers)
- Coverage configuration (if any)

### Raw Data
- Test directory structure (from manifest)
- Sample test patterns (describe how tests are structured)
- Quality tool configuration summary

Be thorough but concise. Facts only, no opinions.""",
    },
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def clone_repo(repo_url: str, destination: Path) -> Path:
    """Clone or update a GitHub repository."""
    repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    repo_path = destination / repo_name

    if repo_path.exists():
        print(f"[Update] Updating: {repo_name}")
        try:
            subprocess.run(
                ["git", "pull"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            print("[Warning] Pull failed, using existing version")
    else:
        print(f"[Cloning] Cloning: {repo_url}")
        subprocess.run(
            ["git", "clone", repo_url, str(repo_path)],
            check=True,
            capture_output=True,
        )

    return repo_path


# ===================================================================
# Main Generator Class
# ===================================================================

class OpenHandsDocGenerator:
    """
    Three-tier documentation generator.

    Tier 0 (Scouts):   Explore the repo, produce intelligence reports.
    Tier 1 (Planner):  Pure reasoning, designs doc architecture.
    Tier 2 (Writers):  Write each document from planner briefs.
    """

    def __init__(self, repo_path: Path, repo_url: str, collection: str = ""):
        self.repo_path = repo_path.resolve()
        self.repo_url = repo_url
        self.repo_name = repo_path.name
        self.collection = (
            collection + "/"
            if collection and not collection.endswith("/")
            else collection
        )

        # Configurable output directory
        self.notes_dir = Path(os.getenv("NOTES_DIR", "./notes")).resolve()
        self.notes_dir.mkdir(parents=True, exist_ok=True)

        # Registry & API client
        self.registry = DocumentRegistry()
        self.api_client = DocumentAPIClient()

        # Load environment
        load_dotenv()

        # Validate required config
        missing = [name for name, val in [
            ("SCOUT_MODEL", SCOUT_MODEL),
            ("PLANNER_MODEL", PLANNER_MODEL),
            ("WRITER_MODEL", WRITER_MODEL),
            ("LLM_BASE_URL", LLM_BASE_URL),
        ] if not val]
        if missing:
            raise ValueError(
                f"Missing required LLM configuration: {', '.join(missing)}. "
                "Set them in .env or as environment variables. See .env.example."
            )

        # ---- Resolve model constraints --------------------------------------
        self._scout_config = resolve_model_config(SCOUT_MODEL)
        self._planner_config = resolve_model_config(PLANNER_MODEL)
        self._writer_config = resolve_model_config(WRITER_MODEL)

        # ---- Tier 0: Scout Agent -------------------------------------------
        scout_kwargs = _llm_kwargs("SCOUT")
        self.scout_llm = LLM(
            model=SCOUT_MODEL,
            native_tool_calling=LLM_NATIVE_TOOL_CALLING,
            timeout=900,
            max_output_tokens=self._scout_config.max_output_tokens,
            reasoning_effort="none",
            enable_encrypted_reasoning=False,
            # OpenRouter: middle-out transform handles provider-specific message
            # format issues (e.g. Moonshot AI requiring reasoning_content in
            # assistant tool call messages)
            litellm_extra_body={"thinking": {"type": "disabled"}},
            **scout_kwargs,
        )
        # Condenser max_size derived from context window:
        # larger context → more events before condensing
        scout_condenser_size = max(20, self._scout_config.context_window // 5000)
        scout_condenser = LLMSummarizingCondenser(
            llm=self.scout_llm,
            max_size=scout_condenser_size,
            keep_first=2,
        )
        self.scout_agent = Agent(
            llm=self.scout_llm,
            tools=[
                Tool(name=TerminalTool.name),
                Tool(name=FileEditorTool.name),
            ],
            condenser=scout_condenser,
        )

        # ---- Tier 1: Planner LLM (direct completion, no tools) ------------
        # Planner output cap: use model limit but cap at 16K (plans don't need more)
        planner_output = min(self._planner_config.max_output_tokens, 16384)
        self.planner_llm = LLM(
            model=PLANNER_MODEL,
            timeout=900,
            max_output_tokens=planner_output,
            reasoning_effort="none",
            enable_encrypted_reasoning=False,
            litellm_extra_body={"thinking": {"type": "disabled"}},
            **_llm_kwargs("PLANNER"),
        )

        # ---- Tier 2: Writer Agent ------------------------------------------
        writer_kwargs = _llm_kwargs("WRITER")
        self.writer_llm = LLM(
            model=WRITER_MODEL,
            native_tool_calling=LLM_NATIVE_TOOL_CALLING,
            timeout=900,
            max_output_tokens=self._writer_config.max_output_tokens,
            reasoning_effort="none",
            enable_encrypted_reasoning=False,
            litellm_extra_body={"thinking": {"type": "disabled"}},
            **writer_kwargs,
        )
        writer_condenser_size = max(20, self._writer_config.context_window // 4000)
        writer_condenser = LLMSummarizingCondenser(
            llm=self.writer_llm,
            max_size=writer_condenser_size,
            keep_first=2,
        )
        self.writer_agent = Agent(
            llm=self.writer_llm,
            tools=[
                Tool(name=TerminalTool.name),
                Tool(name=FileEditorTool.name),
                Tool(name=TaskTrackerTool.name),
            ],
            condenser=writer_condenser,
        )

        print("[Agent] Three-Tier Documentation Generator Configured:")
        print(f"   Scout:   {SCOUT_MODEL} ({self._scout_config})")
        print(f"   Planner: {PLANNER_MODEL} ({self._planner_config})")
        print(f"   Writer:  {WRITER_MODEL} ({self._writer_config})")
        print(f"   Condenser: scout={scout_condenser_size}, writer={writer_condenser_size}")
        print(f"   Native tool calling: {LLM_NATIVE_TOOL_CALLING}")
        print(f"   Workspace: {self.repo_path}")
        print(f"   Output:    {self.notes_dir}")

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover_existing_documents(self) -> dict:
        """Query the API for existing documents (for cross-referencing)."""
        try:
            all_docs = self.api_client.get_all_documents()
            related_docs = [
                doc
                for doc in all_docs
                if doc.get("collection", "").rstrip("/")
                == self.collection.rstrip("/")
            ] if self.collection else []
            return {
                "all_docs": all_docs,
                "related_docs": related_docs,
                "count": len(all_docs),
                "related_count": len(related_docs),
            }
        except Exception as e:
            print(f"[Warning] Could not discover existing documents: {e}")
            return {
                "all_docs": [],
                "related_docs": [],
                "count": 0,
                "related_count": 0,
            }

    def _build_document_context(self, discovery: dict) -> str:
        """Format existing documents for inclusion in prompts."""
        from security import PromptInjectionDetector
        from collections import defaultdict

        if discovery["count"] == 0:
            return "\n**DOCUMENTATION ECOSYSTEM:** This is the first document in the system.\n"

        detector = PromptInjectionDetector()
        context = f"\n**DOCUMENTATION ECOSYSTEM:** {discovery['count']} existing documents.\n\n"
        context += "**Available documents for cross-referencing:**\n\n"

        by_collection = defaultdict(list)
        for doc in discovery["all_docs"]:
            by_collection[doc.get("collection", "uncategorized")].append(doc)

        for coll, docs in sorted(by_collection.items()):
            if coll:
                context += f"Collection: {detector.sanitize_filename(coll)}\n"
            for doc in docs[:10]:
                title = doc.get("title", doc.get("repo_name", "Unknown"))
                safe = detector.sanitize_filename(title)
                dtype = doc.get("doc_type", "unknown")
                context += f"  - [[{safe}]] ({dtype})\n"
            if len(docs) > 10:
                context += f"  ... and {len(docs) - 10} more\n"
            context += "\n"
        return context

    # ------------------------------------------------------------------
    # Regeneration context
    # ------------------------------------------------------------------

    def _get_regeneration_context(self) -> dict | None:
        """
        Check if documentation already exists for this repo. If so, fetch
        full content of each doc and the commit SHA they were generated from.

        Returns None if no existing docs (first-time generation), or a dict:
          {
            "last_commit_sha": str,
            "existing_docs": [{"title": ..., "doc_type": ..., "content": ...}, ...],
            "git_diff": str,       # diff since last generation
            "git_log": str,        # commit log since last generation
          }
        """
        existing_list = self.api_client.get_documents_by_repo(self.repo_url)
        if not existing_list:
            return None

        print(f"[Regen] Found {len(existing_list)} existing doc(s) for this repo")

        # Fetch full content for each doc
        existing_docs = []
        last_commit_sha = None
        for doc_summary in existing_list:
            doc_id = doc_summary.get("id")
            if not doc_id:
                continue
            full_doc = self.api_client.get_document(doc_id)
            if not full_doc:
                continue
            existing_docs.append({
                "title": full_doc.get("title", ""),
                "doc_type": full_doc.get("doc_type", ""),
                "content": full_doc.get("content", ""),
            })

            # Get the commit SHA from version history
            if not last_commit_sha:
                versions = self.api_client.get_document_versions(doc_id)
                if versions:
                    meta = versions[0].get("author_metadata", {})
                    sha = meta.get("repo_commit_sha")
                    if sha and sha != "unknown":
                        last_commit_sha = sha

        if not existing_docs:
            return None

        # Get git diff and log since last generation
        git_diff = ""
        git_log = ""
        if last_commit_sha:
            print(f"[Regen] Last documented commit: {last_commit_sha[:8]}")
            try:
                diff_result = subprocess.run(
                    ["git", "diff", "--stat", f"{last_commit_sha}..HEAD"],
                    cwd=self.repo_path,
                    capture_output=True, text=True, timeout=30,
                )
                if diff_result.returncode == 0:
                    git_diff = diff_result.stdout

                # Also get the detailed diff (capped at 10k chars)
                detailed_diff = subprocess.run(
                    ["git", "diff", f"{last_commit_sha}..HEAD"],
                    cwd=self.repo_path,
                    capture_output=True, text=True, timeout=30,
                )
                if detailed_diff.returncode == 0 and detailed_diff.stdout.strip():
                    full_diff = detailed_diff.stdout
                    if len(full_diff) > 10000:
                        git_diff += "\n\n--- Detailed diff (truncated to 10k chars) ---\n"
                        git_diff += full_diff[:10000] + "\n... [truncated]"
                    else:
                        git_diff += "\n\n--- Detailed diff ---\n" + full_diff

                log_result = subprocess.run(
                    ["git", "log", "--oneline", f"{last_commit_sha}..HEAD"],
                    cwd=self.repo_path,
                    capture_output=True, text=True, timeout=30,
                )
                if log_result.returncode == 0:
                    git_log = log_result.stdout
            except Exception as e:
                print(f"[Regen] Warning: could not get git diff: {e}")
        else:
            print("[Regen] No commit SHA found in existing docs, will do full re-exploration")
            return None

        if not git_diff.strip() and not git_log.strip():
            print("[Regen] No changes detected since last generation")
            # Still return context so version_priority can decide per-doc
            return {
                "last_commit_sha": last_commit_sha,
                "existing_docs": existing_docs,
                "git_diff": "",
                "git_log": "",
            }

        print(f"[Regen] Changes detected:")
        print(f"   Commits since last gen: {len(git_log.strip().splitlines())}")
        print(f"   Diff size: {len(git_diff)} chars")

        return {
            "last_commit_sha": last_commit_sha,
            "existing_docs": existing_docs,
            "git_diff": git_diff,
            "git_log": git_log,
        }

    def _run_diff_scout(self, regen_ctx: dict) -> str:
        """
        Run a single diff-focused scout that analyzes WHAT CHANGED instead
        of re-exploring the entire codebase.
        """
        existing_doc_summaries = ""
        for doc in regen_ctx["existing_docs"]:
            # Include first 2000 chars of each existing doc
            content_snippet = doc["content"][:2000]
            if len(doc["content"]) > 2000:
                content_snippet += "\n... [truncated]"
            existing_doc_summaries += f"\n### Existing: {doc['title']} ({doc['doc_type']})\n{content_snippet}\n"

        diff_prompt = f"""You are a repository scout specializing in CHANGE ANALYSIS. Documentation
already exists for this repository. Your job is to understand what has changed
since the last documentation was generated and identify what needs updating.

EXISTING DOCUMENTATION (current versions):
{existing_doc_summaries}

GIT LOG (commits since last documentation):
{regen_ctx['git_log']}

GIT DIFF (changes since last documentation):
{regen_ctx['git_diff']}

YOUR MISSION:
1. Read the git diff carefully to understand what files changed and how
2. For each changed file, read the NEW version to understand the current state
3. Cross-reference changes against existing documentation to identify:
   - Facts that are now WRONG (outdated info in docs)
   - New features/endpoints/configs that are MISSING from docs
   - Removed features that should be DELETED from docs
   - Structural changes that affect architecture descriptions
4. Check if any new files were added that introduce new concepts

Write your report to /tmp/scout_report_diff.md with this format:

## Scout Report: Change Analysis
### Summary of Changes
Brief overview of what changed in the codebase.

### Impact on Documentation
For each existing document, list what needs updating:

#### [Document Title]
- OUTDATED: [specific fact that is now wrong]
- MISSING: [new feature/endpoint/config not in docs]
- REMOVE: [feature that was deleted]
- OK: [section that is still accurate]

### New Files & Features
List any new files/features that may need documentation.

### Raw Data
- Files changed: [count]
- Commits since last gen: [count]
- Key changed files with brief descriptions

Be thorough but concise. Focus on WHAT CHANGED, not on describing the whole codebase."""

        print("\n[Scout] Running diff-focused change analysis...")
        diff_max_iters = getattr(self, '_scout_max_iters', 20)
        try:
            conversation = Conversation(
                agent=self.scout_agent,
                workspace=str(self.repo_path),
                max_iteration_per_run=diff_max_iters,
            )
            conversation.send_message(diff_prompt)
            conversation.run()

            report_path = Path("/tmp/scout_report_diff.md")
            if report_path.exists():
                report = report_path.read_text()
                print(f"   [Done] Diff scout: {len(report.splitlines())} lines")
                return report
            else:
                print("   [Warning] Diff scout did not produce a report")
                return "## Scout Report: Change Analysis\n### Key Findings\nNo report produced.\n"
        except Exception as e:
            print(f"   [Error] Diff scout failed: {e}")
            return f"## Scout Report: Change Analysis\n### Key Findings\nScout failed: {e}\n"

    # ------------------------------------------------------------------
    # Tier 0: Scouts
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Repository Sizing & File Manifest
    # ------------------------------------------------------------------

    _SKIP_DIRS = {
        ".git", "node_modules", "vendor", "__pycache__", ".venv", "venv",
        "dist", "build", ".next", ".nuxt", "target", ".tox", "egg-info",
    }
    _SOURCE_EXTS = {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb",
        ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt",
        ".md", ".yaml", ".yml", ".json", ".toml", ".sh", ".sql",
        ".html", ".css", ".scss", ".vue", ".svelte",
    }
    _SKIP_NAMES = {
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock",
        "Cargo.lock", "poetry.lock",
    }

    def _estimate_repo_tokens(self) -> dict:
        """Walk the repo and build a complete file manifest with token estimates.

        Returns dict with:
          file_manifest: list of (relative_path, bytes) sorted by path
          token_estimate: total estimated tokens (bytes / 4)
          file_count: number of source files
          total_bytes: raw byte count
          size_label: "small" / "medium" / "large"
          top_dirs: {dir_name: total_bytes} for top-level directories
        """
        file_manifest: list[tuple[str, int]] = []
        top_dirs: dict[str, int] = {}
        total_bytes = 0

        try:
            repo_str = str(self.repo_path)
            for root, dirs, files in os.walk(self.repo_path):
                dirs[:] = [d for d in dirs if d not in self._SKIP_DIRS]
                for fname in files:
                    if fname in self._SKIP_NAMES:
                        continue
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in self._SOURCE_EXTS:
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        size = os.path.getsize(fpath)
                    except OSError:
                        continue
                    if size > 512_000:  # skip >500KB (generated/minified)
                        continue
                    rel = os.path.relpath(fpath, repo_str)
                    file_manifest.append((rel, size))
                    total_bytes += size
                    # Track top-level dir sizes
                    top_dir = rel.split(os.sep)[0] if os.sep in rel else "."
                    top_dirs[top_dir] = top_dirs.get(top_dir, 0) + size
        except Exception:
            total_bytes = 80_000
            file_manifest = []
            top_dirs = {}

        file_manifest.sort(key=lambda x: x[0])
        token_estimate = total_bytes // 4

        if token_estimate < 50_000:
            size_label = "small"
        elif token_estimate < 200_000:
            size_label = "medium"
        else:
            size_label = "large"

        return {
            "file_manifest": file_manifest,
            "token_estimate": token_estimate,
            "file_count": len(file_manifest),
            "total_bytes": total_bytes,
            "size_label": size_label,
            "top_dirs": dict(sorted(top_dirs.items(), key=lambda x: -x[1])),
        }

    # Per-scout focus patterns: files matching these substrings get highlighted
    _SCOUT_FOCUS = {
        "structure": {
            "patterns": ["README", "pyproject.toml", "package.json", "Cargo.toml",
                         "go.mod", "pom.xml", "Gemfile", "setup.py", "setup.cfg",
                         "LICENSE", "CHANGELOG"],
            "description": "metadata files (README, package manifests, license)",
        },
        "architecture": {
            "patterns": ["main.", "app.", "index.", "__init__.", "mod.rs",
                         "src/", "lib/", "app/", "pkg/", "internal/", "cmd/"],
            "description": "entry points and main source directories",
        },
        "api": {
            "patterns": ["route", "endpoint", "controller", "handler", "api",
                         "view", "schema", "dto", "serializer", "openapi",
                         "swagger", "graphql", "proto"],
            "description": "API routes, schemas, and interface definitions",
        },
        "infra": {
            "patterns": ["Dockerfile", "docker-compose", ".github/", "Makefile",
                         "Jenkinsfile", ".gitlab-ci", ".circleci", "Procfile",
                         "terraform", "serverless", ".env"],
            "description": "infrastructure, CI/CD, and deployment configs",
        },
        "tests": {
            "patterns": ["test", "spec", "conftest", "jest.config", "pytest",
                         "vitest", ".mocharc", "cypress"],
            "description": "test files and testing configuration",
        },
    }

    def _build_file_manifest_section(
        self, manifest: list[tuple[str, int]], scout_key: str, max_lines: int = 100
    ) -> str:
        """Format the file manifest into a prompt section with focus hints.

        All files are listed, but files matching the scout's focus patterns
        are marked with ★ so the scout knows where to start.
        """
        if not manifest:
            return "FILE MANIFEST: (empty repository)\n"

        focus = self._SCOUT_FOCUS.get(scout_key, {})
        focus_patterns = focus.get("patterns", [])
        focus_desc = focus.get("description", "relevant files")

        def _is_focus(path: str) -> bool:
            path_lower = path.lower()
            return any(p.lower() in path_lower for p in focus_patterns)

        def _fmt_size(b: int) -> str:
            if b < 1024:
                return f"{b} B"
            elif b < 1024 * 1024:
                return f"{b / 1024:.1f} KB"
            return f"{b / (1024 * 1024):.1f} MB"

        lines = []
        focus_count = 0
        for path, size in manifest:
            is_focus = _is_focus(path)
            if is_focus:
                focus_count += 1
            marker = "★ " if is_focus else "  "
            lines.append(f"  {marker}{path} — {_fmt_size(size)}")

        total_tokens = sum(s for _, s in manifest) // 4
        header = (
            f"FILE MANIFEST ({len(manifest)} files, ~{total_tokens:,} tokens total)\n"
            f"★ = FOCUS files for this scout ({focus_count} files matching: {focus_desc})\n"
        )

        if len(lines) > max_lines:
            # Show all focus files + fill remaining with largest non-focus files
            focus_lines = [l for l in lines if l.strip().startswith("★")]
            other_entries = [(p, s) for p, s in manifest if not _is_focus(p)]
            other_entries.sort(key=lambda x: -x[1])
            remaining = max_lines - len(focus_lines) - 2  # 2 for ellipsis lines
            other_lines = [f"    {p} — {_fmt_size(s)}" for p, s in other_entries[:max(0, remaining)]]
            omitted = len(lines) - len(focus_lines) - len(other_lines)
            body = "\n".join(focus_lines + other_lines)
            if omitted > 0:
                body += f"\n  ... and {omitted} more files"
        else:
            body = "\n".join(lines)

        return header + body + "\n"

    def _build_constraints(self, budget_ratio: float) -> str:
        """Build context-aware constraints based on budget ratio."""
        lines = ["\nCONSTRAINTS:"]
        lines.append("- You already have the full file tree above. Do NOT run `find` or `ls -R` to discover files.")

        if budget_ratio < 0.3:
            lines.append("- Read files freely. The repo is small relative to your context.")
        elif budget_ratio < 1.0:
            lines.append("- Use `head -200 <file>` for files larger than 20 KB.")
            lines.append("- Focus on ★-marked files first. You may read other files to trace imports/dependencies.")
        else:
            lines.append("- Use `head -100 <file>` for files larger than 10 KB.")
            lines.append("- Do NOT read more than 8 files total. Focus strictly on ★-marked files.")
            lines.append("- The repo exceeds your context window. Be extremely selective.")

        lines.append("- Write your report before running out of turns.")
        return "\n".join(lines) + "\n"

    def _run_scouts(self) -> str:
        """
        Run scout agents sequentially. Each scout explores a focused area
        of the repository and writes a structured report to /tmp/.

        Uses token estimation to calibrate scout count and iteration limits.
        Returns the concatenated text of all scout reports.
        """
        self._repo_metrics = self._estimate_repo_tokens()
        metrics = self._repo_metrics
        size_label = metrics["size_label"]

        # Budget ratio: how does repo size compare to scout's context window?
        budget_ratio = metrics["token_estimate"] / self._scout_config.context_window
        self._budget_ratio = budget_ratio
        # < 0.3  → repo fits comfortably, scouts can read freely
        # 0.3-1  → significant, scouts need focus hints + head limits
        # > 1.0  → exceeds context, scouts MUST be scoped to subsets

        # Calibrate iteration limits from budget ratio
        if budget_ratio < 0.3:
            self._scout_max_iters = 20
        elif budget_ratio < 1.0:
            self._scout_max_iters = 30
        else:
            self._scout_max_iters = 40

        print(f"\n[Sizing] ~{metrics['token_estimate']:,} tokens, "
              f"{metrics['file_count']} files, {metrics['total_bytes']:,} bytes "
              f"→ {size_label} (budget_ratio={budget_ratio:.2f})")
        top3 = list(metrics['top_dirs'].items())[:3]
        if top3:
            top_str = ", ".join(f"{d} ({s // 1024}KB)" for d, s in top3)
            print(f"[Sizing] Top dirs: {top_str}")

        # Decide which scouts to run based on budget ratio
        scouts_to_run = []
        if budget_ratio < 0.3:
            # Repo fits comfortably — structure + architecture is sufficient
            scouts_to_run = ["structure", "architecture"]
        elif budget_ratio < 1.0:
            # Significant but fits — the 3 always_run scouts
            scouts_to_run = [k for k, v in SCOUT_DEFINITIONS.items() if v["always_run"]]
        else:
            # Exceeds context — all 5 scouts, each scoped to a subset
            scouts_to_run = list(SCOUT_DEFINITIONS.keys())

        print(f"[Scouts] Running {len(scouts_to_run)} scouts: {', '.join(scouts_to_run)} "
              f"(max {self._scout_max_iters} iters each)")

        reports = {}
        for idx, scout_key in enumerate(scouts_to_run, 1):
            scout_def = SCOUT_DEFINITIONS[scout_key]
            report_path = Path(f"/tmp/scout_report_{scout_key}.md")

            print(f"\n[Scout {idx}/{len(scouts_to_run)}] {scout_def['name']}...")

            manifest_section = self._build_file_manifest_section(
                metrics["file_manifest"], scout_key
            )
            prompt = scout_def["prompt"].format(
                repo_path=self.repo_path,
                file_manifest=manifest_section,
                constraints=self._build_constraints(budget_ratio),
            )

            try:
                conversation = Conversation(
                    agent=self.scout_agent,
                    workspace=str(self.repo_path),
                    max_iteration_per_run=self._scout_max_iters,
                )
                conversation.send_message(prompt)
                conversation.run()

                if report_path.exists():
                    report_text = report_path.read_text()
                    reports[scout_key] = report_text
                    lines = len(report_text.strip().split("\n"))
                    print(f"   [Done] {scout_def['name']}: {lines} lines")
                else:
                    print(f"   [Warning] Scout {scout_key} did not produce a report")
                    reports[scout_key] = f"## Scout Report: {scout_def['name']}\n### Key Findings\nNo report produced.\n"

            except Exception as e:
                print(f"   [Error] Scout {scout_key} failed: {e}")
                reports[scout_key] = f"## Scout Report: {scout_def['name']}\n### Key Findings\nScout failed: {e}\n"

        # Store individual reports for filtered writer access
        self._scout_reports_by_key = reports

        # Concatenate all reports (planner gets everything)
        combined = "\n\n---\n\n".join(reports.values())
        print(f"\n[Scouts] All reports collected: {len(combined)} chars total")
        return combined

    # ------------------------------------------------------------------
    # Tier 1: Planner (pure reasoning, no tools)
    # ------------------------------------------------------------------

    def _planner_think(self, scout_reports: str) -> dict:
        """
        Pure reasoning: Planner reads scout reports and outputs a JSON
        documentation blueprint. No filesystem access — just thinking.
        """
        crate_path = f"{self.collection}{self.repo_name}".rstrip("/")

        doc_types_desc = "\n".join(
            f'  - "{k}": {v["title"]}'
            for k, v in sorted(DOCUMENT_TYPES.items())
        )

        planner_prompt = f"""You are a documentation architect designing a WIKI — not a book.

You have received intelligence reports from scouts who explored a codebase.
Design a rich, interconnected documentation wiki with many SHORT focused pages
organized in a logical folder structure.

SCOUT REPORTS:
{scout_reports}

DESIGN PHILOSOPHY:
Think like a human who spent quality time organizing a knowledge base:
- Each page is SHORT: 1-2 printed pages max. If a topic is big, split it.
- Pages are organized in FOLDERS that mirror the project's architecture.
- Pages are DENSELY WIKILINKED — every page references 10-20+ other pages.
- The structure feels like navigating a well-crafted wiki, not reading a PDF.

FOLDER STRUCTURE:
Use the path field to organize pages. The base path is "{crate_path}".
The path is the FOLDER the document lives in — a file named after the title
will be created inside it.

Rules:
- Use folders to GROUP related documents (2+ docs per folder).
- Standalone pages go directly in "{crate_path}" (no subfolder needed).
- Max 2 levels deep. Never create a subfolder that holds only 1 document.

GOOD example:
  "{crate_path}"                    → Overview
  "{crate_path}"                    → Getting Started
  "{crate_path}"                    → Deployment
  "{crate_path}/architecture"       → Architecture Overview
  "{crate_path}/architecture"       → Backend Architecture
  "{crate_path}/architecture"       → Frontend Architecture
  "{crate_path}/architecture"       → Data Model
  "{crate_path}/api"                → API Overview
  "{crate_path}/api"                → Authentication
  "{crate_path}/api"                → Endpoints Reference
  "{crate_path}/config"             → Configuration
  "{crate_path}/config"             → Environment Variables

BAD (one subfolder per doc):
  "{crate_path}/architecture/backend/backend-architecture"
  "{crate_path}/features/wiki-links/wikilink-system"
  "{crate_path}/deployment/docker/docker-deployment"

MANDATORY PAGES (always include these, no exceptions):
  1. "Overview" at "{crate_path}" — what the project is, key components, system diagram
  2. "Getting Started" at "{crate_path}" — prerequisites, install, run in 5 minutes
  3. "Capabilities & User Stories" at "{crate_path}" — business-facing document describing
     what a user can DO with this tool. Written from the user's perspective, NOT the
     developer's. Include:
     - User stories in "As a [role], I can [action], so that [benefit]" format
     - A functional capability matrix (feature → what it does → who it's for)
     - End-to-end workflows a user would follow
     - Client-facing descriptions suitable for product docs or onboarding material
     This page should read like product documentation, not engineering docs.

These three pages MUST appear first in the documents list. Every other page is up
to your judgement based on the scout reports.

PAGE COUNT GUIDELINES:
  - Small repos (< 10 source files): 5-8 pages
  - Medium repos (10-50 files): 8-15 pages
  - Large repos (50+ files): 15-25 pages
Each page should cover ONE focused topic. When in doubt, split.

WIKILINKS ARE THE MOST IMPORTANT THING:
For each page, list ALL other pages it should link to in wikilinks_out.
Every page should link to 5-15 other pages. The wikilink graph should be
DENSE — a reader should be able to navigate the entire wiki by clicking
through links. Think of it as a dependency/relationship map.

FORMAT CHOICES:
For each section, specify what format best serves comprehension:
  "table:..." — structured data, comparisons, specifications
  "diagram:..." — architecture, flows, relationships, data models
  "code:..." — examples, setup commands, API usage
  "wikilinks:..." — navigation to related pages

OUTPUT INSTRUCTIONS:
Output ONLY a valid JSON object (no markdown fences, no commentary).

{{
  "repo_summary": "One paragraph describing the project",
  "complexity": "small|medium|large",
  "reader_journey": "Overview → Getting Started → Architecture → API → Config",
  "documents": [
    {{
      "doc_type": "overview",
      "title": "Overview",
      "path": "{crate_path}",
      "rationale": "Index page — orients the reader and links to everything",
      "sections": [
        {{
          "heading": "What is this project?",
          "format_rationale": "Prose intro with diagram for immediate mental model",
          "rich_content": ["diagram:high-level system overview"]
        }},
        {{
          "heading": "Key Components",
          "format_rationale": "Table linking to each component's dedicated page",
          "rich_content": ["table:components with links to their pages"]
        }}
      ],
      "key_files_to_read": ["README.md"],
      "wikilinks_out": ["Getting Started", "Architecture", "Backend API", "Configuration"]
    }},
    {{
      "doc_type": "component",
      "title": "Document Service",
      "path": "{crate_path}/architecture",
      "rationale": "Focused page on one core service — keeps pages short",
      "sections": [
        {{
          "heading": "Purpose",
          "format_rationale": "Brief prose explaining what this service does",
          "rich_content": []
        }},
        {{
          "heading": "Interface",
          "format_rationale": "Table of public methods is scannable",
          "rich_content": ["table:public methods with signatures"]
        }}
      ],
      "key_files_to_read": ["app/services/document_service.py"],
      "wikilinks_out": ["Document Repository", "Version Service", "API Endpoints"]
    }}
  ]
}}

SPLITTING RULE — LARGE TOPICS MUST BE SPLIT:
If a topic has more than ~5 distinct items (endpoints, services, config sections,
models), it MUST be split into multiple pages. Examples:
  - "API Reference" with 12 endpoints → split by resource: "Users API", "Documents API", "Auth API"
  - "Architecture" covering frontend + backend + infra → split: "Backend Architecture", "Frontend Architecture", "Infrastructure"
  - "Configuration" with 20+ env vars → split by concern: "Database Config", "Auth Config", "Deployment Config"
ONE page should NEVER try to cover more than one resource group or domain.
The parent/overview page links to the sub-pages with a brief summary table.

CRITICAL RULES:
- Create MANY small pages (see page count guidelines), NOT few large ones
- Each page: 2-4 sections max. Keep it SHORT.
- Every page must have wikilinks_out with 5-15 other page titles
- Use nested paths for folder organization
- doc_type is a loose tag (overview, architecture, api, component, guide, config, data-model, capabilities, etc.)
- Output ONLY the JSON object
"""

        print("[Planner] Analyzing scout reports and designing blueprint...")
        try:
            response = self.planner_llm.completion(
                messages=[
                    Message(role="user", content=[TextContent(text=planner_prompt)])
                ],
            )

            # LLMResponse.message.content is a list of content objects
            raw_text = ""
            for block in response.message.content:
                if hasattr(block, "text"):
                    raw_text += block.text

            # Try to extract JSON from the response
            # Handle cases where the model wraps in ```json fences
            json_text = raw_text.strip()
            if json_text.startswith("```"):
                # Strip markdown code fences
                json_text = re.sub(r"^```(?:json)?\s*\n?", "", json_text)
                json_text = re.sub(r"\n?```\s*$", "", json_text)

            blueprint = json.loads(json_text)

            if isinstance(blueprint, dict) and "documents" in blueprint:
                docs = blueprint["documents"]
                # Ensure path is set on all documents
                for doc in docs:
                    if "path" not in doc:
                        doc["path"] = crate_path
                print(f"[Planner] Blueprint ready: {len(docs)} documents")
                print(f"   Complexity: {blueprint.get('complexity', 'unknown')}")
                print(f"   Journey: {blueprint.get('reader_journey', 'N/A')}")
                for doc in docs:
                    rationale = doc.get("rationale", "")
                    print(f"   - {doc['title']} ({doc['doc_type']}): {rationale[:60]}...")
                return blueprint

            print("[Planner] Response was not a valid blueprint, using fallback")
        except json.JSONDecodeError as e:
            print(f"[Planner] Failed to parse JSON ({e}), using fallback")
        except Exception as e:
            print(f"[Planner] Planning failed ({e}), using fallback")

        return self._fallback_plan(crate_path)

    def _fallback_plan(self, crate_path: str) -> dict:
        """Deterministic fallback when planner fails — generates a basic wiki structure."""
        # Reuse cached metrics from _run_scouts if available, otherwise estimate fresh
        metrics = getattr(self, '_repo_metrics', None) or self._estimate_repo_tokens()
        complexity = metrics["size_label"]

        # Build a wiki-style page set based on complexity
        all_titles = []
        documents = []

        # Always include these core pages
        core_pages = [
            {"doc_type": "overview", "title": "Overview", "path": crate_path,
             "sections": [
                 {"heading": "What is this project?", "rich_content": ["diagram:system overview"]},
                 {"heading": "Key Components", "rich_content": ["table:components"]},
             ], "key_files_to_read": ["README.md"]},
            {"doc_type": "capabilities", "title": "Capabilities & User Stories", "path": crate_path,
             "sections": [
                 {"heading": "User Stories", "rich_content": []},
                 {"heading": "Feature Matrix", "rich_content": ["table:capabilities"]},
                 {"heading": "Key Workflows", "rich_content": ["diagram:user workflows"]},
             ], "key_files_to_read": ["README.md"]},
            {"doc_type": "quickstart", "title": "Getting Started", "path": f"{crate_path}/getting-started",
             "sections": [
                 {"heading": "Prerequisites", "rich_content": ["table:requirements"]},
                 {"heading": "Installation", "rich_content": ["code:install"]},
             ], "key_files_to_read": ["README.md"]},
            {"doc_type": "architecture", "title": "Architecture", "path": f"{crate_path}/architecture",
             "sections": [
                 {"heading": "System Design", "rich_content": ["diagram:architecture"]},
                 {"heading": "Components", "rich_content": ["table:components"]},
             ], "key_files_to_read": ["README.md"]},
            {"doc_type": "api", "title": "API Reference", "path": f"{crate_path}/api",
             "sections": [
                 {"heading": "Endpoints", "rich_content": ["table:endpoints"]},
             ], "key_files_to_read": ["README.md"]},
        ]

        if complexity in ("medium", "large"):
            core_pages.extend([
                {"doc_type": "config", "title": "Configuration", "path": f"{crate_path}/config",
                 "sections": [
                     {"heading": "Environment Variables", "rich_content": ["table:env vars"]},
                     ], "key_files_to_read": ["README.md"]},
                {"doc_type": "guide", "title": "User Guide", "path": f"{crate_path}/guide",
                 "sections": [
                     {"heading": "Core Workflow", "rich_content": ["diagram:workflow"]},
                     ], "key_files_to_read": ["README.md"]},
            ])

        if complexity == "large":
            core_pages.extend([
                {"doc_type": "data-model", "title": "Data Model", "path": f"{crate_path}/architecture/data-model",
                 "sections": [
                     {"heading": "Schema", "rich_content": ["diagram:ER diagram"]},
                     ], "key_files_to_read": ["README.md"]},
                {"doc_type": "contributing", "title": "Contributing", "path": f"{crate_path}/contributing",
                 "sections": [
                     {"heading": "Development Setup", "rich_content": ["code:setup"]},
                     ], "key_files_to_read": ["README.md"]},
            ])

        all_titles = [p["title"] for p in core_pages]
        for page in core_pages:
            page["wikilinks_out"] = [t for t in all_titles if t != page["title"]]
            documents.append(page)

        return {
            "repo_summary": f"Repository {self.repo_name}",
            "complexity": complexity,
            "documents": documents,
        }

    # ------------------------------------------------------------------
    # Scout → Writer relevance mapping
    # ------------------------------------------------------------------

    # Which scout reports are most relevant for each doc type
    _SCOUT_RELEVANCE = {
        "overview":      ["structure", "architecture"],
        "quickstart":    ["structure", "infra"],
        "architecture":  ["architecture", "structure"],
        "api":           ["api", "architecture"],
        "config":        ["infra", "structure"],
        "guide":         ["api", "architecture", "structure"],
        "data-model":    ["architecture", "api"],
        "component":     ["architecture", "api"],
        "contributing":  ["tests", "structure", "infra"],
        "capabilities": ["structure", "api", "architecture"],
    }

    def _get_relevant_scout_reports(self, doc_type: str) -> str:
        """Get scout reports relevant to a specific doc type, falling back to all."""
        if not hasattr(self, "_scout_reports_by_key") or not self._scout_reports_by_key:
            return ""
        relevant_keys = self._SCOUT_RELEVANCE.get(doc_type, list(self._scout_reports_by_key.keys()))
        parts = []
        for key in relevant_keys:
            if key in self._scout_reports_by_key:
                parts.append(self._scout_reports_by_key[key])
        # Always include structure as baseline context if not already included
        if "structure" not in relevant_keys and "structure" in self._scout_reports_by_key:
            parts.append(self._scout_reports_by_key["structure"])
        return "\n\n---\n\n".join(parts) if parts else ""

    # ------------------------------------------------------------------
    # Tier 2: Writers
    # ------------------------------------------------------------------

    def _build_writer_brief(
        self,
        doc_spec: dict,
        blueprint: dict,
        discovery: dict,
        scout_reports: str,
    ) -> str:
        """
        Build a focused brief for a Writer agent based on the planner's
        blueprint for a single document. Includes relevant scout context
        so writers don't need to re-explore everything.
        """
        doc_type = doc_spec["doc_type"]
        title = doc_spec["title"]
        sections = doc_spec.get("sections", [])
        key_files = doc_spec.get("key_files_to_read", [])
        wikilinks_out = doc_spec.get("wikilinks_out", [])

        # Build full wiki page list for wikilink context
        all_page_titles = [d["title"] for d in blueprint["documents"]]
        wikilink_targets = doc_spec.get("wikilinks_out", [])
        # Combine explicit targets with all sibling titles
        all_link_targets = list(set(wikilink_targets + [
            t for t in all_page_titles if t != title
        ]))

        sibling_section = "ALL WIKI PAGES (link to these using [[Title]]):\n"
        for t in sorted(all_link_targets):
            sibling_section += f"  - [[{t}]]\n"

        # Build section directives (with format rationale from planner)
        section_directives = ""
        for sec in sections:
            heading = sec["heading"]
            rich = sec.get("rich_content", [])
            rationale = sec.get("format_rationale", "")
            section_directives += f"\n### {heading}\n"
            if rationale:
                section_directives += f"Format guidance: {rationale}\n"
            if rich:
                section_directives += "Required rich content:\n"
                for item in rich:
                    if item.startswith("table:"):
                        section_directives += f"  - Include a GFM TABLE: {item[6:]}\n"
                    elif item.startswith("diagram:"):
                        section_directives += f"  - Include a MERMAID DIAGRAM: {item[8:]}\n"
                    elif item.startswith("code:"):
                        section_directives += f"  - Include a CODE EXAMPLE: {item[5:]}\n"
                    elif item.startswith("wikilinks:"):
                        section_directives += f"  - Include WIKILINKS to: {item[10:]}\n"
            section_directives += "Write 1-3 concise prose paragraphs for this section.\n"

        # Build key files directive
        files_directive = ""
        if key_files:
            files_directive = "\nKEY FILES TO READ (start your exploration here):\n"
            for f in key_files:
                files_directive += f"  - {f}\n"

        # Existing doc context
        doc_context = self._build_document_context(discovery)

        # Output path supports nested folders from planner
        doc_path = doc_spec.get("path", f"{self.collection}{self.repo_name}".rstrip("/"))
        safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '-').lower()
        output_filename = f"{safe_title}.md"
        output_path = self.notes_dir / doc_path / output_filename
        # Writer sees workspace-relative path (it can't write outside workspace)
        workspace_output = Path("notes") / doc_path / output_filename

        brief = f"""You are a technical documentation writer. Write ONE short, focused wiki page:
"{title}" for the project at {self.repo_path}.

THIS PAGE MUST BE SHORT: 1-2 printed pages maximum. This is a wiki page, not
a book chapter. If you find yourself writing more than ~800 words of prose,
you are writing too much. Be concise. Link to other pages for details.

REPOSITORY CONTEXT:
{blueprint.get('repo_summary', 'A software project.')}

PRE-DIGESTED INTELLIGENCE (from repository scouts — filtered for this page):
{self._get_relevant_scout_reports(doc_type) or scout_reports}

{PROSE_REQUIREMENTS}

{TABLE_REQUIREMENTS}

{DIAGRAM_REQUIREMENTS}

{WIKILINK_REQUIREMENTS}

{doc_context}

{sibling_section}

EXPLORATION STRATEGY:
- The scout reports above contain detailed intelligence about the repo
- Use terminal commands to VERIFY specific details and read source files
- Use terminal ONLY for read-only commands: ls, cat, grep, find, tree, git log
- DO NOT run tests, execute scripts, or start applications
{files_directive}

DOCUMENT STRUCTURE:
Write a markdown page titled "# {title}"
with the following sections:
{section_directives}

DO NOT add a "See Also" section. All wikilinks must be inline in prose.

OUTPUT:
- Create the directory structure first: mkdir -p {workspace_output.parent}
- Write the COMPLETE markdown page to: {workspace_output}
- This path is RELATIVE to your workspace root — do NOT use absolute paths
- Keep it SHORT — this is one page in a larger wiki
- Link to other pages liberally using [[Page Title]] for anything worth expanding on
- Base everything on verified facts from the code you read
- Work AUTONOMOUSLY — do not ask for permission
"""
        return brief

    # ------------------------------------------------------------------
    # Orphan cleanup
    # ------------------------------------------------------------------

    def _snapshot_existing_docs(self) -> dict:
        """Take a pre-generation snapshot of all docs belonging to this repo.

        Returns a dict with:
            doc_ids: set of all doc IDs for this repo
            by_id: dict mapping doc_id → doc summary
            human_edited: set of doc IDs with human edits in the last 7 days
            count: total number of docs
        Returns empty sets on any failure (cleanup will be skipped).
        """
        try:
            existing = self.api_client.get_documents_by_repo(self.repo_url)
            if not existing:
                return {"doc_ids": set(), "by_id": {}, "human_edited": set(), "count": 0}

            doc_ids = set()
            by_id = {}
            human_edited = set()

            for doc in existing:
                doc_id = doc.get("id")
                if not doc_id:
                    continue
                doc_ids.add(doc_id)
                by_id[doc_id] = doc

                # Check version history for human edits within 7 days
                try:
                    versions = self.api_client.get_document_versions(doc_id)
                    for version in versions:
                        author_type = version.get("author_type", "")
                        if author_type == "human":
                            created = version.get("created_at", "")
                            if created:
                                from datetime import timezone
                                version_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                                age = datetime.now(timezone.utc) - version_dt
                                if age.days < 7:
                                    human_edited.add(doc_id)
                                    break
                except Exception:
                    pass  # If we can't check versions, don't mark as human-edited

            print(f"[Snapshot] {len(doc_ids)} existing doc(s) for this repo, {len(human_edited)} human-edited (7d)")
            return {
                "doc_ids": doc_ids,
                "by_id": by_id,
                "human_edited": human_edited,
                "count": len(doc_ids),
            }
        except Exception as e:
            print(f"[Snapshot] Failed to snapshot existing docs: {e}")
            return {"doc_ids": set(), "by_id": {}, "human_edited": set(), "count": 0}

    def _cleanup_orphaned_docs(
        self,
        snapshot: dict,
        generated_ids: set,
        failed_ids: set,
    ) -> dict:
        """Delete orphaned AI-generated docs, preserving human-edited and failed ones.

        Args:
            snapshot: Result from _snapshot_existing_docs().
            generated_ids: Doc IDs that were successfully generated this run.
            failed_ids: Doc IDs that failed generation this run.

        Returns:
            Dict with deleted, preserved_human, preserved_failed, errors counts.
        """
        result = {"deleted": 0, "preserved_human": 0, "preserved_failed": 0, "errors": []}

        if not snapshot["doc_ids"]:
            print("[Cleanup] No snapshot — skipping orphan cleanup")
            return result

        orphans = snapshot["doc_ids"] - generated_ids - failed_ids
        if not orphans:
            print("[Cleanup] No orphaned documents found")
            return result

        human_edited = snapshot["human_edited"]
        to_delete = orphans - human_edited
        preserved_human = orphans & human_edited

        result["preserved_human"] = len(preserved_human)
        result["preserved_failed"] = len(failed_ids & snapshot["doc_ids"])

        if preserved_human:
            for doc_id in preserved_human:
                title = snapshot["by_id"].get(doc_id, {}).get("title", doc_id)
                print(f"[Cleanup] Preserving human-edited: {title} ({doc_id})")

        if not to_delete:
            print(f"[Cleanup] {len(orphans)} orphan(s) found, all preserved (human-edited)")
            return result

        print(f"[Cleanup] Deleting {len(to_delete)} orphaned doc(s)...")
        for doc_id in to_delete:
            title = snapshot["by_id"].get(doc_id, {}).get("title", doc_id)
            print(f"   - {title} ({doc_id})")

        delete_result = self.api_client.batch_delete(list(to_delete))
        result["deleted"] = delete_result.get("succeeded", 0)
        result["errors"] = delete_result.get("errors", [])

        if result["errors"]:
            print(f"[Cleanup] Batch delete had errors: {result['errors']}")

        print(f"[Cleanup] Done: {result['deleted']} deleted, {result['preserved_human']} preserved (human), {result['preserved_failed']} preserved (failed)")
        return result

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _get_current_commit_sha(self) -> str:
        """Get current commit SHA of the repository."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"

    def generate_document(
        self,
        doc_spec: dict,
        blueprint: dict,
        discovery: dict,
        scout_reports: str,
    ) -> dict:
        """
        Generate a single document using a Writer agent.

        Args:
            doc_spec:       One entry from blueprint["documents"]
            blueprint:      The full planner blueprint
            discovery:      Existing documents for cross-referencing
            scout_reports:  Concatenated scout intelligence reports

        Returns:
            Result dict with status, doc_id, etc.
        """
        doc_type = doc_spec["doc_type"]
        title = doc_spec["title"]
        path = doc_spec.get("path", f"{self.collection}{self.repo_name}".rstrip("/"))

        doc_id = generate_doc_id(self.repo_url, path, title, doc_type)
        commit_sha = self._get_current_commit_sha()

        print(f"\n{'='*70}")
        print(f"[Writer] GENERATING: {title} ({doc_type})")
        print(f"{'='*70}")
        print(f"   Doc ID: {doc_id}")

        # Check version priority
        priority_engine = VersionPriorityEngine(
            api_client=self.api_client, repo_path=self.repo_path
        )
        should_generate, reason = priority_engine.should_regenerate(
            doc_id=doc_id, current_commit_sha=commit_sha
        )
        if not should_generate:
            print(f"   [Skip] {reason}")
            return {"status": "skipped", "reason": reason, "doc_id": doc_id}

        print(f"   [Generate] {reason}")

        # Build writer brief (now includes scout reports)
        brief = self._build_writer_brief(doc_spec, blueprint, discovery, scout_reports)

        # Compute output path matching what the writer brief specifies
        doc_path = doc_spec.get("path", f"{self.collection}{self.repo_name}".rstrip("/"))
        safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '-').lower()
        output_filename = f"{safe_title}.md"
        output_file = self.notes_dir / doc_path / output_filename

        try:
            # Ensure output directory exists
            output_file.parent.mkdir(parents=True, exist_ok=True)

            # Run writer agent — iteration limit from budget ratio
            budget_ratio = getattr(self, '_budget_ratio', 0.5)
            if budget_ratio < 0.3:
                writer_max_iters = 30
            elif budget_ratio < 1.0:
                writer_max_iters = 40
            else:
                writer_max_iters = 50
            conversation = Conversation(
                agent=self.writer_agent,
                workspace=str(self.repo_path),
                max_iteration_per_run=writer_max_iters,
            )
            conversation.send_message(brief)
            conversation.run()

            # Find output — writers write relative to workspace (self.repo_path)
            # Primary location: workspace/notes/doc_path/filename.md
            workspace_output_file = self.repo_path / "notes" / doc_path / output_filename
            if workspace_output_file.exists():
                output_file = workspace_output_file
            elif not output_file.exists():
                # Also try notes_dir name instead of "notes"
                workspace_relative = self.repo_path / self.notes_dir.name / doc_path / output_filename
                if workspace_relative.exists():
                    output_file = workspace_relative
                else:
                    # Recursive search for the filename in workspace
                    candidates = list(self.repo_path.rglob(output_filename))
                    if not candidates:
                        candidates = list(self.repo_path.rglob(f"*{safe_title}*.md"))
                    if not candidates:
                        candidates = list(self.repo_path.rglob(f"*{doc_type}*.md"))
                    if candidates:
                        output_file = candidates[0]

            if not output_file.exists():
                print(f"   [Warning] Output file not found")
                return {
                    "status": "warning",
                    "message": f"Output file not found for {title}",
                    "doc_id": doc_id,
                }

            # Read and clean content
            raw_content = output_file.read_text()
            metadata, body = parse_bottomatter(raw_content)
            if not metadata:
                metadata, body = parse_frontmatter(raw_content)

            body = re.sub(r"^\*Documentation Written by.*?\*\n+", "", body)
            clean_content = re.sub(
                r"\n---\n\n\*Documentation.*$", "", body, flags=re.DOTALL
            )

            # Verify rich content
            has_table = "|" in clean_content and "---" in clean_content
            has_mermaid = "```mermaid" in clean_content
            wikilink_count = len(re.findall(r"\[\[.+?\]\]", clean_content))

            print(f"   [Content] Tables: {'yes' if has_table else 'no'} | Diagrams: {'yes' if has_mermaid else 'no'} | Wikilinks: {wikilink_count}")
            if wikilink_count < 5:
                print(f"   [Content] Warning: low wikilink count ({wikilink_count}) — pages should have 10-20+")

            keywords = DOCUMENT_TYPES.get(doc_type, {}).get("keywords", [])

            # POST to API
            doc_data = {
                "repo_url": self.repo_url,
                "repo_name": self.repo_name,
                "path": doc_path,
                "title": title,
                "doc_type": doc_type,
                "content": clean_content,
                "keywords": keywords,
                "author_type": "ai",
                "author_metadata": {
                    "generator": "openhands-three-tier",
                    "scout_model": SCOUT_MODEL,
                    "planner_model": PLANNER_MODEL,
                    "writer_model": WRITER_MODEL,
                    "repo_commit_sha": commit_sha,
                },
            }

            try:
                api_result = self.api_client.create_or_update_document(
                    doc_data=doc_data, fallback_path=output_file
                )
                content_size = len(clean_content.encode("utf-8"))

                if api_result.get("method") == "filesystem":
                    print(f"   [Fallback] Saved to file (API unavailable)")
                else:
                    print(f"   [Success] Posted to API")
                    print(f"   ID: {api_result.get('id', doc_id)}")

                print(f"   Size: {content_size:,} bytes")

                return {
                    "status": "success",
                    "doc_id": api_result.get("id", doc_id),
                    "method": api_result.get("method", "api"),
                    "size": content_size,
                    "api_result": api_result,
                }

            except Exception as e:
                print(f"   [Error] Failed to post: {e}")
                return {
                    "status": "error_fallback",
                    "doc_id": doc_id,
                    "error": str(e),
                    "file": str(output_file),
                }

        except Exception as e:
            print(f"   [Error] Generation failed: {e}")
            import traceback
            traceback.print_exc()
            return {"status": "error", "error": str(e)}

    def generate_all(self, force: bool = False) -> dict:
        """
        Full pipeline: Scouts explore → Planner thinks → Writers execute.
        """
        results = {}

        print("\n" + "=" * 70)
        print("[Pipeline] THREE-TIER DOCUMENTATION GENERATION")
        print("=" * 70)

        # Pre-generation snapshot for orphan cleanup
        snapshot = self._snapshot_existing_docs()

        # Phase 0: Check if this is a regeneration (docs already exist)
        regen_ctx = self._get_regeneration_context()

        if regen_ctx:
            # Check if repo has actually changed
            if not regen_ctx["git_diff"].strip() and not regen_ctx["git_log"].strip():
                # Repo hasn't moved — check if any doc is actually stale
                current_sha = self._get_current_commit_sha()
                if regen_ctx["last_commit_sha"] == current_sha and not force:
                    print("\n[Pipeline] Repository unchanged since last generation — nothing to do.")
                    return results

            # REGENERATION PATH: docs exist, focus on what changed
            print("\n[Phase 1] DIFF SCOUT — Analyzing changes since last generation...")
            scout_reports = self._run_diff_scout(regen_ctx)

            # Append existing doc content summaries for planner context
            existing_summary = "\n\n---\n\n## Existing Documentation Content\n"
            for doc in regen_ctx["existing_docs"]:
                existing_summary += f"\n### {doc['title']} ({doc['doc_type']})\n"
                existing_summary += doc["content"][:3000]
                if len(doc["content"]) > 3000:
                    existing_summary += "\n... [truncated]"
                existing_summary += "\n"
            scout_reports += existing_summary
        else:
            # FIRST-TIME PATH: full exploration
            print("\n[Phase 1] SCOUTS — Exploring repository...")
            scout_reports = self._run_scouts()

        # Phase 2: Planner designs documentation architecture
        print("\n[Phase 2] PLANNER — Designing documentation architecture...")
        blueprint = self._planner_think(scout_reports)

        documents = blueprint.get("documents", [])

        # Reorder: detail/leaf pages first, hub pages last.
        # Hub pages (overview, capabilities, quickstart) link to everything and
        # benefit from all detail pages already existing in discovery.
        _HUB_TYPES = {"overview", "capabilities", "quickstart"}
        detail_docs = [d for d in documents if d.get("doc_type") not in _HUB_TYPES]
        hub_docs = [d for d in documents if d.get("doc_type") in _HUB_TYPES]
        documents = detail_docs + hub_docs

        total = len(documents)
        print(f"\n[Phase 3] WRITERS — Generating {total} documents (detail pages first, hub pages last)...")

        # Discover existing docs (once, shared across writers)
        discovery = self._discover_existing_documents()
        print(f"   Existing documents in system: {discovery['count']}")

        # Phase 3: Writers execute
        generated_doc_ids = set()
        failed_doc_ids = set()

        for idx, doc_spec in enumerate(documents, 1):
            print(f"\n[{idx}/{total}] Dispatching writer for: {doc_spec['title']}")
            result = self.generate_document(
                doc_spec, blueprint, discovery, scout_reports
            )
            results[doc_spec["title"]] = result

            # Track generated/failed doc IDs for orphan cleanup
            doc_id = result.get("doc_id")
            if doc_id:
                status = result.get("status", "")
                if status in ("success", "skipped"):
                    generated_doc_ids.add(doc_id)
                elif status in ("error", "error_fallback", "warning"):
                    failed_doc_ids.add(doc_id)

            # Re-discover after each doc so subsequent writers see earlier ones
            if result.get("status") == "success":
                discovery = self._discover_existing_documents()

        # Summary
        print("\n" + "=" * 70)
        print("[Summary] GENERATION COMPLETE")
        print("=" * 70)

        successes = sum(1 for r in results.values() if r.get("status") == "success")
        skipped = sum(1 for r in results.values() if r.get("status") == "skipped")
        errors = sum(
            1 for r in results.values()
            if r.get("status") in ("error", "error_fallback", "warning")
        )

        print(f"   Pages: {total}  Success: {successes}  Skipped: {skipped}  Errors: {errors}")

        for title, result in results.items():
            status = result.get("status", "unknown")
            doc_id = result.get("doc_id", "")
            print(f"   {title}: {status} ({doc_id})")

        # Phase 4: Orphan cleanup
        if snapshot["count"] > 0:
            print("\n[Phase 4] CLEANUP — Removing orphaned documents...")
            cleanup = self._cleanup_orphaned_docs(snapshot, generated_doc_ids, failed_doc_ids)
            if cleanup["deleted"] or cleanup["preserved_human"]:
                print(f"   Deleted: {cleanup['deleted']}  Preserved (human): {cleanup['preserved_human']}  Preserved (failed): {cleanup['preserved_failed']}")

        return results


# ===================================================================
# CLI Entry Point
# ===================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Three-tier documentation generator (Scouts + Planner + Writers)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --repo https://github.com/facebook/react
  %(prog)s --repo https://github.com/django/django --collection backend
  %(prog)s --repo https://github.com/user/repo --doc-type quickstart
        """,
    )
    parser.add_argument("--repo", required=True, help="GitHub repository URL")
    parser.add_argument(
        "--collection",
        default="",
        help="Optional collection prefix (e.g., 'backend')",
    )
    parser.add_argument(
        "--doc-type",
        default="auto",
        help="Document type to generate, or 'auto' for full pipeline (default: auto)",
    )
    parser.add_argument(
        "--planner-model",
        default=None,
        help="Override planner model",
    )
    parser.add_argument(
        "--writer-model",
        default=None,
        help="Override writer model",
    )
    parser.add_argument(
        "--scout-model",
        default=None,
        help="Override scout model",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override global LLM base URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Override global LLM API key",
    )
    parser.add_argument(
        "--no-native-tools",
        action="store_true",
        help="Disable native tool calling (use text-based fallback)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force regeneration even if repo is unchanged since last run",
    )
    args = parser.parse_args()

    # Override config if specified via CLI
    if args.planner_model:
        os.environ["PLANNER_MODEL"] = args.planner_model
    if args.writer_model:
        os.environ["WRITER_MODEL"] = args.writer_model
    if args.scout_model:
        os.environ["SCOUT_MODEL"] = args.scout_model
    if args.base_url:
        os.environ["LLM_BASE_URL"] = args.base_url
    if args.api_key:
        os.environ["LLM_API_KEY"] = args.api_key
    if args.no_native_tools:
        os.environ["LLM_NATIVE_TOOL_CALLING"] = "false"

    # SECURITY: Validate repository URL
    validator = RepositoryValidator()
    is_valid, error, sanitized_url = validator.validate_repo_url(args.repo)
    if not is_valid:
        print(f"[Security] Repository URL validation failed: {error}")
        sys.exit(1)

    # SECURITY: Validate collection path
    path_validator = PathValidator()
    is_valid, error, sanitized_collection = path_validator.validate_collection(
        args.collection
    )
    if not is_valid:
        print(f"[Security] Collection validation failed: {error}")
        sys.exit(1)

    print("=" * 70)
    print("[DocAgent] THREE-TIER AUTONOMOUS DOCUMENTATION GENERATOR")
    print("=" * 70)
    print(f"Repository: {sanitized_url}")
    if sanitized_collection:
        print(f"Collection: {sanitized_collection}")
    print()

    # Clone repository
    repos_dir = Path(os.getenv("REPOS_DIR", "./repos"))
    repos_dir.mkdir(exist_ok=True)

    try:
        repo_path = clone_repo(sanitized_url, repos_dir)
    except subprocess.CalledProcessError as e:
        print(f"[Error] Failed to clone repository: {e}")
        sys.exit(1)

    # Generate
    generator = OpenHandsDocGenerator(repo_path, sanitized_url, sanitized_collection)

    if args.doc_type == "auto":
        results = generator.generate_all(force=args.force)
    else:
        # Single doc mode — run scouts + planner for context, then one writer
        scout_reports = generator._run_scouts()
        blueprint = generator._planner_think(scout_reports)

        # Find the requested doc in the blueprint, or build a minimal spec
        crate_path = f"{sanitized_collection}/{repo_path.name}".strip("/")
        doc_spec = None
        for doc in blueprint.get("documents", []):
            if doc["doc_type"] == args.doc_type:
                doc_spec = doc
                break

        if not doc_spec:
            title = DOCUMENT_TYPES.get(args.doc_type, {}).get(
                "title", args.doc_type.replace("-", " ").title()
            )
            doc_spec = {
                "doc_type": args.doc_type,
                "title": title,
                "path": f"{crate_path}/{args.doc_type}",
                "sections": [
                    {"heading": "Overview", "rich_content": []},
                   ],
                "key_files_to_read": ["README.md"],
                "wikilinks_out": [],
            }
            blueprint = {
                "repo_summary": blueprint.get("repo_summary", f"Repository {repo_path.name}"),
                "complexity": blueprint.get("complexity", "medium"),
                "documents": [doc_spec],
            }

        discovery = generator._discover_existing_documents()
        result = generator.generate_document(
            doc_spec, blueprint, discovery, scout_reports
        )
        results = {doc_spec["title"]: result}

    # Final output
    api_url = os.getenv("DOC_API_URL", "http://localhost:8000")
    print(f"\n[Info] Documentation available at:")
    print(f"   API: {api_url}/api/docs")
    print(f"   Frontend: http://localhost:3000\n")


if __name__ == "__main__":
    main()
