"""Tests for the planner tier: blueprint parsing, JSON extraction, fallback plan.

All LLM calls are mocked.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tests.fixtures import SAMPLE_BLUEPRINT, SAMPLE_SCOUT_REPORTS


# ---------------------------------------------------------------------------
# Blueprint JSON extraction
# ---------------------------------------------------------------------------

class TestBlueprintParsing:

    def test_parse_clean_json(self, generator):
        """LLM returns clean JSON string → valid blueprint."""
        gen, *_ = generator

        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = json.dumps(SAMPLE_BLUEPRINT)
        mock_response.message.content = [mock_block]
        gen.planner_llm.completion.return_value = mock_response

        result = gen._planner_think(SAMPLE_SCOUT_REPORTS)

        assert "documents" in result
        assert len(result["documents"]) == 2
        assert result["documents"][0]["title"] == "Overview"

    def test_parse_markdown_fenced_json(self, generator):
        """LLM wraps JSON in ```json fences → still parsed correctly."""
        gen, *_ = generator

        fenced = "```json\n" + json.dumps(SAMPLE_BLUEPRINT) + "\n```"
        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = fenced
        mock_response.message.content = [mock_block]
        gen.planner_llm.completion.return_value = mock_response

        result = gen._planner_think(SAMPLE_SCOUT_REPORTS)

        assert "documents" in result
        assert len(result["documents"]) == 2

    def test_default_path_when_missing(self, generator):
        """Docs missing 'path' field get a default path."""
        gen, *_ = generator

        blueprint_no_path = {
            "repo_summary": "Test",
            "complexity": "small",
            "documents": [
                {"doc_type": "overview", "title": "Overview", "sections": [], "key_files_to_read": [], "wikilinks_out": []},
            ],
        }

        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = json.dumps(blueprint_no_path)
        mock_response.message.content = [mock_block]
        gen.planner_llm.completion.return_value = mock_response

        result = gen._planner_think(SAMPLE_SCOUT_REPORTS)

        # Should have a path set (defaults to repo_name)
        assert "path" in result["documents"][0]
        assert result["documents"][0]["path"] != ""

    def test_invalid_json_falls_back(self, generator):
        """Garbage LLM output → fallback plan, no crash."""
        gen, *_ = generator

        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "This is not JSON at all, just random text from the LLM."
        mock_response.message.content = [mock_block]
        gen.planner_llm.completion.return_value = mock_response

        result = gen._planner_think(SAMPLE_SCOUT_REPORTS)

        # Should fall back gracefully
        assert "documents" in result
        assert len(result["documents"]) > 0

    def test_llm_exception_falls_back(self, generator):
        """LLM call raises exception → fallback plan."""
        gen, *_ = generator

        gen.planner_llm.completion.side_effect = Exception("API timeout")

        result = gen._planner_think(SAMPLE_SCOUT_REPORTS)

        assert "documents" in result
        assert len(result["documents"]) > 0


# ---------------------------------------------------------------------------
# Fallback plan
# ---------------------------------------------------------------------------

class TestFallbackPlan:

    def test_small_repo(self, generator):
        gen, _, workspace, _ = generator

        with patch("openhands_doc.subprocess.run") as mock_run:
            # Simulate 5 source files
            mock_run.return_value = MagicMock(stdout="a.py\nb.py\nc.py\nd.py\ne.py", returncode=0)
            result = gen._fallback_plan("test/repo")

        assert result["complexity"] == "small"
        assert len(result["documents"]) == 4  # core pages only
        # All pages should have wikilinks_out
        for doc in result["documents"]:
            assert "wikilinks_out" in doc
            assert len(doc["wikilinks_out"]) > 0

    def test_large_repo(self, generator):
        gen, _, workspace, _ = generator

        with patch("openhands_doc.subprocess.run") as mock_run:
            # Simulate 60 source files
            lines = "\n".join(f"file{i}.py" for i in range(60))
            mock_run.return_value = MagicMock(stdout=lines, returncode=0)
            result = gen._fallback_plan("test/repo")

        assert result["complexity"] == "large"
        assert len(result["documents"]) == 8  # core + medium + large pages
        # Should have nested paths
        paths = [d["path"] for d in result["documents"]]
        assert any("/" in p.replace("test/repo", "") for p in paths), (
            f"Large repo should have nested paths, got: {paths}"
        )


# ---------------------------------------------------------------------------
# Scout report filtering
# ---------------------------------------------------------------------------

class TestScoutReportFiltering:

    def test_api_doc_gets_relevant_scouts_only(self, generator):
        """api doc type gets api + architecture scouts, NOT infra/tests."""
        gen, *_ = generator

        gen._scout_reports_by_key = {
            "structure": "## Structure\nstuff",
            "architecture": "## Architecture\nstuff",
            "api": "## API\nstuff",
            "infra": "## Infra\nstuff",
            "tests": "## Tests\nstuff",
        }

        result = gen._get_relevant_scout_reports("api")

        assert "API" in result
        assert "Architecture" in result
        # Infra and tests should NOT be included for api doc type
        assert "Infra" not in result
        assert "Tests" not in result

    def test_unknown_doc_type_gets_all_scouts(self, generator):
        gen, *_ = generator

        gen._scout_reports_by_key = {
            "structure": "## Structure",
            "api": "## API",
        }

        result = gen._get_relevant_scout_reports("unknown-type")

        assert "Structure" in result
        assert "API" in result

    def test_empty_scout_reports_returns_empty(self, generator):
        gen, *_ = generator

        gen._scout_reports_by_key = {}

        result = gen._get_relevant_scout_reports("overview")
        assert result == ""
