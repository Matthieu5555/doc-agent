"""Tests for the DocumentAPIClient.

Verifies retry logic, filesystem fallback, field validation, and
error handling — all with mocked HTTP via the responses library.
"""

from pathlib import Path

import pytest
import requests.exceptions
import responses

from doc_agent.api_client import DocumentAPIClient


@pytest.fixture
def client():
    return DocumentAPIClient(api_url="http://test:8000", api_token="")


@pytest.fixture
def valid_doc_data():
    return {
        "repo_url": "https://github.com/test/repo",
        "repo_name": "repo",
        "doc_type": "overview",
        "content": "# Overview\n\nTest content.",
        "path": "repo/overview",
        "title": "Overview",
    }


# ---------------------------------------------------------------------------
# create_or_update_document
# ---------------------------------------------------------------------------

class TestCreateDocument:

    @responses.activate
    def test_success(self, client, valid_doc_data):
        responses.add(
            responses.POST, "http://test:8000/api/docs",
            json={"id": "doc-123", "status": "created"}, status=201,
        )

        result = client.create_or_update_document(valid_doc_data)

        assert result["id"] == "doc-123"
        assert result["status"] == "created"
        assert len(responses.calls) == 1

    @responses.activate
    def test_retries_on_failure(self, client, valid_doc_data):
        """Two failures then success → 3 total calls, success returned."""
        responses.add(responses.POST, "http://test:8000/api/docs", body=requests.exceptions.ConnectionError())
        responses.add(responses.POST, "http://test:8000/api/docs", body=requests.exceptions.ConnectionError())
        responses.add(
            responses.POST, "http://test:8000/api/docs",
            json={"id": "doc-123", "status": "created"}, status=201,
        )

        result = client.create_or_update_document(valid_doc_data)

        assert result["id"] == "doc-123"
        assert len(responses.calls) == 3

    @responses.activate
    def test_falls_back_to_file(self, client, valid_doc_data, tmp_path):
        """All retries fail with fallback_path → writes to disk."""
        for _ in range(3):
            responses.add(responses.POST, "http://test:8000/api/docs", body=requests.exceptions.ConnectionError())

        fallback = tmp_path / "fallback.md"
        result = client.create_or_update_document(valid_doc_data, fallback_path=fallback)

        assert result["method"] == "filesystem"
        assert fallback.exists()
        assert fallback.read_text() == valid_doc_data["content"]

    @responses.activate
    def test_all_retries_fail_no_fallback_raises(self, client, valid_doc_data):
        """All retries fail with no fallback → raises Exception."""
        for _ in range(3):
            responses.add(responses.POST, "http://test:8000/api/docs", body=requests.exceptions.ConnectionError())

        with pytest.raises(Exception, match="API POST failed"):
            client.create_or_update_document(valid_doc_data)

    def test_missing_required_fields_raises(self, client):
        """Missing repo_url → ValueError."""
        with pytest.raises(ValueError, match="repo_url"):
            client.create_or_update_document({
                "repo_name": "repo",
                "doc_type": "overview",
                "content": "test",
            })

    def test_missing_content_raises(self, client):
        with pytest.raises(ValueError, match="content"):
            client.create_or_update_document({
                "repo_url": "https://github.com/test/repo",
                "repo_name": "repo",
                "doc_type": "overview",
            })


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

class TestReadOperations:

    @responses.activate
    def test_get_document_success(self, client):
        responses.add(
            responses.GET, "http://test:8000/api/docs/doc-123",
            json={"id": "doc-123", "title": "Test", "content": "# Test"},
        )

        result = client.get_document("doc-123")
        assert result["id"] == "doc-123"

    @responses.activate
    def test_get_document_404_returns_none(self, client):
        responses.add(responses.GET, "http://test:8000/api/docs/doc-999", status=404)

        result = client.get_document("doc-999")
        assert result is None

    @responses.activate
    def test_get_document_network_error_returns_none(self, client):
        responses.add(responses.GET, "http://test:8000/api/docs/doc-123", body=requests.exceptions.ConnectionError())

        result = client.get_document("doc-123")
        assert result is None

    @responses.activate
    def test_get_documents_by_repo(self, client):
        responses.add(
            responses.GET, "http://test:8000/api/docs",
            json=[{"id": "doc-1"}, {"id": "doc-2"}],
        )

        result = client.get_documents_by_repo("https://github.com/test/repo")
        assert len(result) == 2

    @responses.activate
    def test_get_documents_by_repo_failure_returns_empty(self, client):
        responses.add(responses.GET, "http://test:8000/api/docs", body=requests.exceptions.ConnectionError())

        result = client.get_documents_by_repo("https://github.com/test/repo")
        assert result == []

    @responses.activate
    def test_health_check_healthy(self, client):
        responses.add(responses.GET, "http://test:8000/health", status=200)
        assert client.health_check() is True

    @responses.activate
    def test_health_check_unreachable(self, client):
        responses.add(responses.GET, "http://test:8000/health", body=requests.exceptions.ConnectionError())
        assert client.health_check() is False
