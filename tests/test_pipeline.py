"""Integration tests for the documentation generation pipeline.

Tests the contract between writer agents, file finder, content cleaner,
and local file output. All LLM/agent calls are mocked — zero credits spent.
"""

import re
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from tests.fixtures import (
    SAMPLE_BLUEPRINT,
    SAMPLE_DOC_CONTENT,
    SAMPLE_DOC_WITH_BOTTOMATTER,
    SAMPLE_DOC_WITH_FRONTMATTER,
    SAMPLE_SCOUT_REPORTS,
    make_writer_side_effect,
)


# ---------------------------------------------------------------------------
# File finder tests — the $20 bug
# ---------------------------------------------------------------------------

class TestWriterOutputResolution:
    """The writer agent creates a file; generate_document() must find it."""

    def test_writer_output_found_in_workspace(self, generator):
        """File at workspace/notes/{path}/{file}.md is found and written to output."""
        gen, MockConv, workspace, output = generator
        doc_spec = SAMPLE_BLUEPRINT["documents"][0]  # Overview

        # Simulate writer creating the file in the workspace
        safe_title = re.sub(r'[^\w\s-]', '', doc_spec["title"]).strip().replace(' ', '-').lower()
        filename = f"{safe_title}.md"
        doc_path = doc_spec["path"]

        conv_instance = MockConv.return_value
        conv_instance.run.side_effect = make_writer_side_effect(
            workspace, doc_path, filename, SAMPLE_DOC_CONTENT
        )

        result = gen.generate_document(
            doc_spec, SAMPLE_BLUEPRINT, {"all_docs": [], "related_docs": [], "count": 0, "related_count": 0},
            SAMPLE_SCOUT_REPORTS,
        )

        assert result["status"] == "success", f"Expected success, got {result}"
        assert result["method"] == "filesystem"
        # Output file should exist
        output_file = Path(result["file"])
        assert output_file.exists()
        content = output_file.read_text()
        assert "Overview" in content or "IsoCrates" in content

    def test_writer_output_found_via_rglob_fallback(self, generator):
        """File at unexpected workspace location is found via rglob."""
        gen, MockConv, workspace, output = generator
        doc_spec = SAMPLE_BLUEPRINT["documents"][0]

        safe_title = re.sub(r'[^\w\s-]', '', doc_spec["title"]).strip().replace(' ', '-').lower()
        filename = f"{safe_title}.md"

        # Write to an unexpected path inside workspace
        def write_unexpected(*args, **kwargs):
            out = workspace / "unexpected" / filename
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(SAMPLE_DOC_CONTENT)

        conv_instance = MockConv.return_value
        conv_instance.run.side_effect = write_unexpected

        result = gen.generate_document(
            doc_spec, SAMPLE_BLUEPRINT, {"all_docs": [], "related_docs": [], "count": 0, "related_count": 0},
            SAMPLE_SCOUT_REPORTS,
        )

        assert result["status"] == "success", f"rglob fallback failed: {result}"

    def test_writer_output_not_found_returns_warning(self, generator):
        """Agent writes nothing → warning status, no crash."""
        gen, MockConv, workspace, output = generator
        doc_spec = SAMPLE_BLUEPRINT["documents"][0]

        # Conversation.run() does nothing
        conv_instance = MockConv.return_value
        conv_instance.run.return_value = None

        result = gen.generate_document(
            doc_spec, SAMPLE_BLUEPRINT, {"all_docs": [], "related_docs": [], "count": 0, "related_count": 0},
            SAMPLE_SCOUT_REPORTS,
        )

        assert result["status"] == "warning"
        assert "not found" in result["message"].lower()


# ---------------------------------------------------------------------------
# Writer brief tests
# ---------------------------------------------------------------------------

class TestWriterBrief:
    """The brief sent to the writer agent must use correct paths."""

    def test_brief_uses_workspace_relative_path(self, generator):
        """Brief must NOT contain absolute paths — only workspace-relative."""
        gen, MockConv, workspace, output = generator
        doc_spec = SAMPLE_BLUEPRINT["documents"][1]  # Backend Architecture

        brief = gen._build_writer_brief(
            doc_spec, SAMPLE_BLUEPRINT,
            {"all_docs": [], "related_docs": [], "count": 0, "related_count": 0},
            SAMPLE_SCOUT_REPORTS,
        )

        # Must contain workspace-relative path
        assert "notes/" in brief
        # Must NOT contain the absolute output_dir path
        assert str(output) not in brief, (
            f"Brief contains absolute path {output}. "
            "Writer can't write outside its workspace."
        )

    def test_safe_title_special_chars(self, generator):
        """Titles with special characters produce valid filenames."""
        gen, *_ = generator

        test_cases = [
            ("API Reference", "api-reference"),
            ("Getting Started!", "getting-started"),
            ("C++ Guide (Advanced)", "c-guide-advanced"),
            ("Data Model: v2.0", "data-model-v20"),
            ("  Spaces  ", "spaces"),
        ]

        for title, expected in test_cases:
            safe = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '-').lower()
            assert safe == expected, f"Title '{title}' → '{safe}', expected '{expected}'"


# ---------------------------------------------------------------------------
# Content cleaning tests
# ---------------------------------------------------------------------------

class TestContentCleaning:
    """Content from writer agents is cleaned before writing to output."""

    def test_strips_bottomatter(self, generator):
        gen, MockConv, workspace, output = generator
        doc_spec = SAMPLE_BLUEPRINT["documents"][0]

        safe_title = re.sub(r'[^\w\s-]', '', doc_spec["title"]).strip().replace(' ', '-').lower()
        filename = f"{safe_title}.md"

        conv_instance = MockConv.return_value
        conv_instance.run.side_effect = make_writer_side_effect(
            workspace, doc_spec["path"], filename, SAMPLE_DOC_WITH_BOTTOMATTER
        )

        result = gen.generate_document(
            doc_spec, SAMPLE_BLUEPRINT, {"all_docs": [], "related_docs": [], "count": 0, "related_count": 0},
            SAMPLE_SCOUT_REPORTS,
        )

        assert result["status"] == "success"
        # Read the output file and check content
        output_file = Path(result["file"])
        content = output_file.read_text()
        # Old stale bottomatter ID should be replaced with fresh metadata
        assert "# Overview" in content

    def test_strips_frontmatter(self, generator):
        gen, MockConv, workspace, output = generator
        doc_spec = SAMPLE_BLUEPRINT["documents"][0]

        safe_title = re.sub(r'[^\w\s-]', '', doc_spec["title"]).strip().replace(' ', '-').lower()
        filename = f"{safe_title}.md"

        conv_instance = MockConv.return_value
        conv_instance.run.side_effect = make_writer_side_effect(
            workspace, doc_spec["path"], filename, SAMPLE_DOC_WITH_FRONTMATTER
        )

        result = gen.generate_document(
            doc_spec, SAMPLE_BLUEPRINT, {"all_docs": [], "related_docs": [], "count": 0, "related_count": 0},
            SAMPLE_SCOUT_REPORTS,
        )

        assert result["status"] == "success"
        output_file = Path(result["file"])
        content = output_file.read_text()
        assert "# Overview" in content


# ---------------------------------------------------------------------------
# Output file metadata tests
# ---------------------------------------------------------------------------

class TestOutputFile:
    """Output files must contain proper bottomatter metadata."""

    def _generate_and_get_file(self, gen, MockConv, workspace, doc_spec):
        safe_title = re.sub(r'[^\w\s-]', '', doc_spec["title"]).strip().replace(' ', '-').lower()
        filename = f"{safe_title}.md"

        conv_instance = MockConv.return_value
        conv_instance.run.side_effect = make_writer_side_effect(
            workspace, doc_spec["path"], filename, SAMPLE_DOC_CONTENT
        )

        result = gen.generate_document(
            doc_spec, SAMPLE_BLUEPRINT,
            {"all_docs": [], "related_docs": [], "count": 0, "related_count": 0},
            SAMPLE_SCOUT_REPORTS,
        )

        assert result["status"] == "success"
        return Path(result["file"])

    def test_output_file_has_metadata(self, generator):
        gen, MockConv, workspace, output = generator
        output_file = self._generate_and_get_file(gen, MockConv, workspace, SAMPLE_BLUEPRINT["documents"][0])

        content = output_file.read_text()
        # Should have bottomatter with key metadata
        assert "repo_url:" in content
        assert "doc_type:" in content
        assert "author_type: ai" in content

    def test_output_file_has_repo_url(self, generator):
        gen, MockConv, workspace, output = generator
        output_file = self._generate_and_get_file(gen, MockConv, workspace, SAMPLE_BLUEPRINT["documents"][0])

        content = output_file.read_text()
        assert "https://github.com/test/repo" in content

    def test_output_preserves_title(self, generator):
        gen, MockConv, workspace, output = generator
        doc_spec = SAMPLE_BLUEPRINT["documents"][1]
        output_file = self._generate_and_get_file(gen, MockConv, workspace, doc_spec)

        content = output_file.read_text()
        assert "Backend Architecture" in content


# ---------------------------------------------------------------------------
# generate_all flow tests
# ---------------------------------------------------------------------------

class TestGenerateAllFlow:
    """Full pipeline flow: scouts → planner → writers."""

    def test_early_bailout_unchanged_repo(self, generator):
        """If repo unchanged since last gen, return immediately with no writer calls."""
        gen, MockConv, workspace, output = generator

        # Mock regeneration context: docs exist, repo unchanged
        regen_ctx = {
            "last_commit_sha": "abc123",
            "existing_docs": [{"title": "Overview", "doc_type": "overview", "content": "old"}],
            "git_diff": "",
            "git_log": "",
        }

        with (
            patch.object(gen, "_get_regeneration_context", return_value=regen_ctx),
            patch.object(gen, "_get_current_commit_sha", return_value="abc123"),
            patch.object(gen, "generate_document") as mock_gen_doc,
        ):
            results = gen.generate_all()

        assert results == {}
        mock_gen_doc.assert_not_called()

    def test_first_time_runs_scouts_then_planner_then_writers(self, generator):
        """First-time generation: full scouts → planner → N writers."""
        gen, MockConv, workspace, output = generator

        with (
            patch.object(gen, "_get_regeneration_context", return_value=None),
            patch.object(gen, "_run_scouts", return_value=SAMPLE_SCOUT_REPORTS) as mock_scouts,
            patch.object(gen, "_planner_think", return_value=SAMPLE_BLUEPRINT) as mock_planner,
            patch.object(gen, "generate_document", return_value={"status": "success"}) as mock_gen,
            patch.object(gen, "_discover_existing_documents", return_value={
                "all_docs": [], "related_docs": [], "count": 0, "related_count": 0,
            }),
        ):
            results = gen.generate_all()

        mock_scouts.assert_called_once()
        mock_planner.assert_called_once()
        assert mock_gen.call_count == len(SAMPLE_BLUEPRINT["documents"])

    def test_regen_uses_diff_scout_not_full_scouts(self, generator):
        """Regeneration path: diff scout, NOT full scouts."""
        gen, MockConv, workspace, output = generator

        regen_ctx = {
            "last_commit_sha": "abc123",
            "existing_docs": [{"title": "Overview", "doc_type": "overview", "content": "old content"}],
            "git_diff": "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-old\n+new",
            "git_log": "def456 Add new feature",
        }

        with (
            patch.object(gen, "_get_regeneration_context", return_value=regen_ctx),
            patch.object(gen, "_run_scouts") as mock_scouts,
            patch.object(gen, "_run_diff_scout", return_value="## Diff Report\nChanges found.") as mock_diff,
            patch.object(gen, "_planner_think", return_value=SAMPLE_BLUEPRINT),
            patch.object(gen, "generate_document", return_value={"status": "success"}),
            patch.object(gen, "_discover_existing_documents", return_value={
                "all_docs": [], "related_docs": [], "count": 0, "related_count": 0,
            }),
        ):
            results = gen.generate_all()

        mock_diff.assert_called_once()
        mock_scouts.assert_not_called()
