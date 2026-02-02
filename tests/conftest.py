"""Shared fixtures for the agent test suite.

All tests run with zero API calls, zero network access, zero LLM credits.
External deps (OpenHands SDK, OpenRouter, backend API) are mocked.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure doc-agent/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def tmp_workspace(tmp_path):
    """Temp directory mimicking a cloned git repo."""
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "README.md").write_text("# Test Repo\n\nA test project.")
    (workspace / "main.py").write_text("print('hello')")
    (workspace / ".git").mkdir()
    return workspace


@pytest.fixture
def tmp_notes_dir(tmp_path):
    """Temp directory for notes output."""
    notes = tmp_path / "notes"
    notes.mkdir()
    return notes


@pytest.fixture
def generator(tmp_workspace, tmp_notes_dir, monkeypatch):
    """OpenHandsDocGenerator with all external deps mocked.

    Yields (generator, MockConversation, workspace_path, notes_path).
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-fake")
    monkeypatch.setenv("NOTES_DIR", str(tmp_notes_dir))
    monkeypatch.setenv("DOC_API_URL", "http://fake:9999")

    with (
        patch("doc_agent.generator.LLM"),
        patch("doc_agent.generator.Agent"),
        patch("doc_agent.generator.Conversation") as MockConv,
        patch("doc_agent.generator.DocumentRegistry"),
        patch("doc_agent.generator.DocumentAPIClient") as MockAPI,
        patch("doc_agent.generator.VersionPriorityEngine") as MockVPE,
    ):
        from doc_agent.generator import OpenHandsDocGenerator

        MockVPE.return_value.should_regenerate.return_value = (True, "No existing document found")

        gen = OpenHandsDocGenerator(
            repo_path=tmp_workspace,
            repo_url="https://github.com/test/repo",
        )
        gen.api_client = MockAPI.return_value
        gen.api_client.create_or_update_document.return_value = {
            "id": "doc-test-123",
            "status": "created",
        }
        gen.api_client.get_all_documents.return_value = []
        gen.api_client.get_documents_by_repo.return_value = []

        yield gen, MockConv, tmp_workspace, tmp_notes_dir
