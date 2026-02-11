# Auto Doc Agent

Three-tier autonomous documentation generator using the OpenHands SDK. Point it at a repository (URL or local path), and it produces structured markdown documentation.

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
REPOS_DIR=./repos          # where remote repos are cloned
```

## Usage

```bash
# Generate docs from a remote repository (clones automatically)
doc-agent https://github.com/facebook/react

# Generate docs from a local directory
doc-agent /path/to/local/repo

# Custom output directory
doc-agent https://github.com/user/repo -o ./docs

# With a collection prefix and specific doc type
doc-agent /path/to/repo --collection backend --doc-type architecture
```

## Output Structure

```
output/
  {repo-name}/
    overview.md
    architecture.md
    api-reference.md
    ...
```

Each `.md` file includes bottomatter metadata (doc ID, repo URL, commit SHA, generation timestamp) for tracking regeneration state.

## Architecture

1. **Scouts** (parallel) -- explore the repo and produce intelligence reports
2. **Planner** (single, reasoning-only) -- designs documentation structure from scout reports
3. **Writers** (one per document) -- each writes a focused wiki page in flowing prose

Features: git-aware regeneration, wikilinks, mermaid diagrams, GFM tables, security validation.
