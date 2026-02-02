"""REST API client for posting documents to a backend API.

Deep module: callers pass document data in, get a result back.
Retry logic, auth headers, and filesystem fallback are handled internally.
"""

import logging
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)


class DocumentAPIClient:
    """Client for interacting with the documentation REST API.

    Args:
        api_url: Base URL of the API. Defaults to ``DOC_API_URL`` env var
                 or ``http://backend-api:8000``.
        api_token: Bearer token for authentication. Defaults to ``DOC_API_TOKEN``
                   env var. When empty, requests are sent without auth (dev mode).
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_token: Optional[str] = None,
    ):
        self.api_url = api_url or os.getenv("DOC_API_URL", "http://backend-api:8000")
        self.api_token = api_token or os.getenv("DOC_API_TOKEN", "")
        self.max_retries = 3
        self.timeout = 30

    def _headers(self) -> Dict[str, str]:
        """Build request headers, including auth if a token is configured."""
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    # ----- write operations ------------------------------------------------

    def create_or_update_document(
        self,
        doc_data: Dict[str, Any],
        fallback_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Create or update a document via API with retry and fallback.

        Args:
            doc_data: Document payload (repo_url, repo_name, doc_type, content, …).
            fallback_path: If all retries fail, write content here instead.

        Returns:
            API response dict or fallback status dict.
        """
        endpoint = f"{self.api_url}/api/docs"

        required_fields = ["repo_url", "repo_name", "doc_type", "content"]
        missing = [f for f in required_fields if f not in doc_data]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        for attempt in range(self.max_retries):
            try:
                logger.info("POST %s (attempt %d/%d)", endpoint, attempt + 1, self.max_retries)

                response = requests.post(
                    endpoint,
                    json=doc_data,
                    timeout=self.timeout,
                    headers=self._headers(),
                )
                response.raise_for_status()
                result = response.json()

                logger.info("Document posted", extra={"id": result.get("id"), "status": result.get("status", "created")})
                return result

            except requests.exceptions.RequestException as exc:
                logger.warning("Request failed: %s: %s", type(exc).__name__, exc)

                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    logger.info("Retrying in %ds", wait)
                    time.sleep(wait)
                else:
                    logger.error("All %d attempts failed", self.max_retries)
                    if fallback_path:
                        return self._fallback_to_file(doc_data, fallback_path)
                    raise Exception(f"API POST failed after {self.max_retries} attempts: {exc}")

    # ----- read operations -------------------------------------------------

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get a document by ID. Returns None on 404 or network failure."""
        try:
            response = requests.get(
                f"{self.api_url}/api/docs/{doc_id}",
                timeout=self.timeout,
                headers=self._headers(),
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            logger.warning("Failed to get document %s: %s", doc_id, exc)
            return None

    def get_document_versions(self, doc_id: str) -> list:
        """Get version history for a document. Returns empty list on failure."""
        try:
            response = requests.get(
                f"{self.api_url}/api/docs/{doc_id}/versions",
                timeout=self.timeout,
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            logger.warning("Failed to get versions for %s: %s", doc_id, exc)
            return []

    def get_all_documents(self, limit: int = 1000) -> list:
        """Get all documents. Returns empty list on failure."""
        try:
            response = requests.get(
                f"{self.api_url}/api/docs?limit={limit}",
                timeout=self.timeout,
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            logger.warning("Failed to get all documents: %s", exc)
            return []

    def get_documents_by_repo(self, repo_url: str, limit: int = 100) -> list:
        """Get all documents for a specific repository URL."""
        try:
            response = requests.get(
                f"{self.api_url}/api/docs",
                params={"repo_url": repo_url, "limit": limit},
                timeout=self.timeout,
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            logger.warning("Failed to get documents for repo %s: %s", repo_url, exc)
            return []

    def health_check(self) -> bool:
        """Check if API is healthy."""
        try:
            response = requests.get(f"{self.api_url}/health", timeout=5)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    # ----- batch operations ------------------------------------------------

    def batch_delete(self, doc_ids: list) -> Dict[str, Any]:
        """Soft-delete multiple documents in a single request.

        Args:
            doc_ids: List of document IDs to delete.

        Returns:
            Dict with total, succeeded, failed, errors keys.
        """
        if not doc_ids:
            return {"total": 0, "succeeded": 0, "failed": 0, "errors": []}

        endpoint = f"{self.api_url}/api/docs/batch"
        payload = {"operation": "delete", "doc_ids": doc_ids}

        try:
            response = requests.post(
                endpoint,
                json=payload,
                timeout=self.timeout,
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            logger.error("Batch delete failed: %s", exc)
            return {
                "total": len(doc_ids),
                "succeeded": 0,
                "failed": len(doc_ids),
                "errors": [str(exc)],
            }

    # ----- internal --------------------------------------------------------

    def _fallback_to_file(self, doc_data: Dict[str, Any], file_path: Path) -> Dict[str, Any]:
        """Write document content to disk when the API is unreachable."""
        try:
            logger.info("Fallback: writing to %s", file_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(doc_data["content"])
            logger.info("Fallback write succeeded")
            return {
                "status": "fallback",
                "method": "filesystem",
                "file": str(file_path),
                "message": "API unavailable, wrote to file instead",
            }
        except Exception as exc:
            logger.error("Fallback write failed: %s", exc)
            raise Exception(f"Both API and file fallback failed: {exc}")
