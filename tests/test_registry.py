"""Tests for document ID generation and metadata parsing.

These are pure functions — no mocking needed.
"""

import pytest

from doc_agent.registry import generate_doc_id, parse_frontmatter, parse_bottomatter


# ---------------------------------------------------------------------------
# Document ID generation
# ---------------------------------------------------------------------------

class TestDocIdGeneration:

    def test_deterministic(self):
        """Same inputs always produce the same ID."""
        id1 = generate_doc_id("https://github.com/test/repo", "path/a", "Title", "overview")
        id2 = generate_doc_id("https://github.com/test/repo", "path/a", "Title", "overview")
        assert id1 == id2

    def test_unique_across_paths(self):
        """Different paths → different IDs."""
        id1 = generate_doc_id("https://github.com/test/repo", "path/a", "Title", "overview")
        id2 = generate_doc_id("https://github.com/test/repo", "path/b", "Title", "overview")
        assert id1 != id2

    def test_unique_across_titles(self):
        """Different titles → different IDs."""
        id1 = generate_doc_id("https://github.com/test/repo", "path", "Title A", "overview")
        id2 = generate_doc_id("https://github.com/test/repo", "path", "Title B", "overview")
        assert id1 != id2

    def test_unique_across_repos(self):
        """Different repos → different IDs."""
        id1 = generate_doc_id("https://github.com/test/repo-a", "path", "Title", "overview")
        id2 = generate_doc_id("https://github.com/test/repo-b", "path", "Title", "overview")
        assert id1 != id2

    def test_format(self):
        """ID has format doc-{12chars}-{12chars}."""
        doc_id = generate_doc_id("https://github.com/test/repo", "path", "Title", "overview")
        assert doc_id.startswith("doc-")
        parts = doc_id.split("-")
        # doc-{repo_hash}-{path_hash}
        assert len(parts) == 3
        assert len(parts[1]) == 12
        assert len(parts[2]) == 12

    def test_legacy_fallback_uses_doc_type(self):
        """No path or title → falls back to doc_type."""
        doc_id = generate_doc_id("https://github.com/test/repo", "", "", "overview")
        assert doc_id.endswith("-overview")


# ---------------------------------------------------------------------------
# Bottomatter parsing
# ---------------------------------------------------------------------------

class TestParseBottomatter:

    def test_extracts_metadata(self):
        content = "# Title\n\nBody text.\n\n---\nid: doc-123\ntype: overview\n---\n"
        metadata, body = parse_bottomatter(content)

        assert metadata is not None
        assert metadata["id"] == "doc-123"
        assert metadata["type"] == "overview"
        assert "# Title" in body
        assert "doc-123" not in body

    def test_body_preserved(self):
        content = "# Title\n\nParagraph one.\n\nParagraph two.\n\n---\nid: x\n---\n"
        metadata, body = parse_bottomatter(content)

        assert "Paragraph one" in body
        assert "Paragraph two" in body

    def test_no_bottomatter_returns_none(self):
        content = "# Title\n\nJust plain markdown.\n"
        metadata, body = parse_bottomatter(content)

        assert metadata is None
        assert body == content

    def test_empty_content(self):
        metadata, body = parse_bottomatter("")
        assert metadata is None
        assert body == ""


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

class TestParseFrontmatter:

    def test_extracts_metadata(self):
        content = "---\nid: doc-123\ntype: overview\n---\n# Title\n\nBody."
        metadata, body = parse_frontmatter(content)

        assert metadata is not None
        assert metadata["id"] == "doc-123"
        assert "# Title" in body
        assert "doc-123" not in body

    def test_no_frontmatter_returns_none(self):
        content = "# Title\n\nJust markdown."
        metadata, body = parse_frontmatter(content)

        assert metadata is None
        assert body == content

    def test_handles_quoted_values(self):
        content = '---\nid: "doc-123"\ntitle: \'My Title\'\n---\nBody.'
        metadata, body = parse_frontmatter(content)

        assert metadata["id"] == "doc-123"
        assert metadata["title"] == "My Title"
