# Auto Doc Agent

Three-tier autonomous documentation generator using the OpenHands SDK. Clones a repository, explores it with scout agents, plans documentation architecture, then writes focused markdown pages.

## Setup

```bash
pip install -e .
# or
uv sync
```

## Configuration

Set these environment variables (or use a `.env` file):

```bash
# LLM (required)
LLM_API_KEY=<your-openrouter-or-provider-key>
LLM_BASE_URL=https://openrouter.ai/api/v1   # or local endpoint

# Models (optional, sensible defaults in model_config.py)
SCOUT_MODEL=mistralai/devstral-2512
PLANNER_MODEL=moonshotai/kimi-k2-thinking
WRITER_MODEL=mistralai/devstral-2512

# Per-tier overrides (optional)
SCOUT_BASE_URL=...
SCOUT_API_KEY=...
PLANNER_BASE_URL=...
PLANNER_API_KEY=...
WRITER_BASE_URL=...
WRITER_API_KEY=...

# Output (optional)
OUTPUT_DIR=./output        # where markdown files are written
REPOS_DIR=./repos          # where repos are cloned
```

## Usage

```bash
# Generate docs for a repository
python openhands_doc.py --repo https://github.com/user/repo

# With a collection prefix
python openhands_doc.py --repo https://github.com/user/repo --collection backend/

# Single document type
python openhands_doc.py --repo https://github.com/user/repo --doc-type architecture
```

## Output Structure

```
output/
  {repo-name}/
    overview.md
    architecture.md
    api-reference.md
    ...
  .doc_registry.json       # metadata index
  .versions/
    doc-xxxx-yyyy.json      # per-document version history
```

## Architecture

1. **Scouts** (parallel) -- explore the repo and produce intelligence reports
2. **Planner** (single, reasoning-only) -- designs documentation structure from scout reports
3. **Writers** (one per document) -- each writes a focused wiki page in flowing prose

Features: intelligent regeneration (respects human edits), git change detection, wikilinks, mermaid diagrams, security validation.
