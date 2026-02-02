"""Shared test data and helpers for the agent test suite."""

from pathlib import Path


def make_writer_side_effect(workspace: Path, doc_path: str, filename: str, content: str):
    """Create a side_effect that simulates a writer agent creating an output file."""
    def side_effect(*args, **kwargs):
        out = workspace / "notes" / doc_path / filename
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content)
    return side_effect

SAMPLE_BLUEPRINT = {
    "repo_summary": "A documentation management platform with FastAPI backend and Next.js frontend.",
    "complexity": "large",
    "reader_journey": "Overview → Getting Started → Architecture → API → Config",
    "documents": [
        {
            "doc_type": "overview",
            "title": "Overview",
            "path": "IsoCrates",
            "rationale": "Index page",
            "sections": [
                {"heading": "What is IsoCrates?", "format_rationale": "Prose + diagram", "rich_content": ["diagram:system overview"]},
                {"heading": "Key Components", "format_rationale": "Table", "rich_content": ["table:components"]},
            ],
            "key_files_to_read": ["README.md"],
            "wikilinks_out": ["Getting Started", "Architecture"],
        },
        {
            "doc_type": "architecture",
            "title": "Backend Architecture",
            "path": "IsoCrates/architecture/backend",
            "rationale": "Backend deep-dive",
            "sections": [
                {"heading": "Layers", "format_rationale": "Diagram", "rich_content": ["diagram:layers"]},
            ],
            "key_files_to_read": ["backend/app/main.py"],
            "wikilinks_out": ["Overview", "API Reference"],
        },
    ],
}

SAMPLE_SCOUT_REPORTS = """## Scout Report: Structure & Overview
### Key Findings
- Python/TypeScript project
- FastAPI backend, Next.js frontend
### Raw Data
- 120 source files

---

## Scout Report: Architecture & Code
### Key Findings
- Repository pattern, service layer
### Raw Data
- Entry: backend/app/main.py
"""

SAMPLE_DOC_CONTENT = """# Overview

IsoCrates is a documentation management platform built with a [[FastAPI]] backend
and a [[Next.js]] frontend. The system uses a [[three-tier agent architecture]]
for AI-powered documentation generation.

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Backend | FastAPI | REST API |
| Frontend | Next.js | Web UI |
| Agent | OpenHands | Doc generation |

```mermaid
graph TD
    A[Frontend] --> B[Backend API]
    B --> C[Database]
    B --> D[Agent]
```

## See Also

- [[Getting Started]] for setup instructions
- [[Architecture]] for system design
- [[API Reference]] for endpoint details
"""

SAMPLE_DOC_WITH_BOTTOMATTER = SAMPLE_DOC_CONTENT + """
---
id: doc-abc123-def456
repo_url: https://github.com/test/repo
doc_type: overview
---
"""

SAMPLE_DOC_WITH_FRONTMATTER = """---
id: doc-abc123-def456
repo_url: https://github.com/test/repo
doc_type: overview
---
""" + SAMPLE_DOC_CONTENT
