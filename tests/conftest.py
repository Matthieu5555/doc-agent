"""Shared fixtures for the agent test suite.

All tests run with zero API calls, zero network access, zero LLM credits.
External deps (OpenHands SDK) are mocked.
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
def tmp_output_dir(tmp_path):
    """Temp directory for output."""
    output = tmp_path / "output"
    output.mkdir()
    return output


@pytest.fixture
def generator(tmp_workspace, tmp_output_dir, monkeypatch):
    """OpenHandsDocGenerator with all external deps mocked.

    Yields (generator, MockConversation, workspace_path, output_path).
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-fake")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_output_dir))

    with (
        patch("doc_agent.generator.LLM"),
        patch("doc_agent.generator.Agent"),
        patch("doc_agent.generator.Conversation") as MockConv,
        patch("doc_agent.generator.LLMSummarizingCondenser"),
        patch("doc_agent.generator.DocumentRegistry"),
    ):
        import doc_agent.generator as gen_mod

        # Module-level config is read at import time; override for tests
        monkeypatch.setattr(gen_mod, "SCOUT_MODEL", "test/scout-model")
        monkeypatch.setattr(gen_mod, "PLANNER_MODEL", "test/planner-model")
        monkeypatch.setattr(gen_mod, "WRITER_MODEL", "test/writer-model")
        monkeypatch.setattr(gen_mod, "LLM_BASE_URL", "http://test:1234")

        from doc_agent.generator import OpenHandsDocGenerator

        gen = OpenHandsDocGenerator(
            repo_path=tmp_workspace,
            repo_url="https://github.com/test/repo",
            output_dir=str(tmp_output_dir),
        )

        yield gen, MockConv, tmp_workspace, tmp_output_dir
