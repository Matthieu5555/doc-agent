"""Local filesystem document store.

Drop-in replacement for the former API client. All documents are read from
and written to a local output directory, with metadata tracked in a JSON
registry and per-document version sidecar files.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LocalDocumentStore:
    """Store and retrieve documents as local markdown files.

    Args:
        output_dir: Root directory for generated documents.
                    Defaults to ``OUTPUT_DIR`` env var or ``./output``.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(
            output_dir or os.getenv("OUTPUT_DIR", "./output")
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._registry_path = self.output_dir / ".doc_registry.json"
        self._versions_dir = self.output_dir / ".versions"
        self._versions_dir.mkdir(parents=True, exist_ok=True)

        self._registry = self._load_registry()

    # ---- registry helpers --------------------------------------------------

    def _load_registry(self) -> Dict:
        if self._registry_path.exists():
            try:
                return json.loads(self._registry_path.read_text())
            except Exception:
                pass
        return {"documents": {}, "version": "1.0"}

    def _save_registry(self):
        self._registry_path.write_text(json.dumps(self._registry, indent=2))

    # ---- write operations --------------------------------------------------

    def create_or_update_document(
        self,
        doc_data: Dict[str, Any],
        fallback_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Write a document to disk and update the registry.

        Accepts the same ``doc_data`` shape as the former API endpoint.
        ``fallback_path`` is accepted for interface compatibility but ignored
        (we always write locally).
        """
        required_fields = ["repo_url", "repo_name", "doc_type", "content"]
        missing = [f for f in required_fields if f not in doc_data]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        # Determine file path
        collection = doc_data.get("collection", doc_data["repo_name"])
        slug = doc_data.get("slug") or doc_data["doc_type"]
        title = doc_data.get("title", slug)
        file_dir = self.output_dir / collection
        file_dir.mkdir(parents=True, exist_ok=True)
        file_path = file_dir / f"{slug}.md"

        # Write content
        file_path.write_text(doc_data["content"])
        logger.info("Wrote document to %s", file_path)

        # Compute / reuse doc_id
        doc_id = doc_data.get("doc_id") or doc_data.get("id") or f"doc-{collection}-{slug}"

        # Update registry
        now = datetime.now(timezone.utc).isoformat()
        entry = self._registry["documents"].get(doc_id, {})
        entry.update({
            "id": doc_id,
            "title": title,
            "repo_url": doc_data["repo_url"],
            "repo_name": doc_data["repo_name"],
            "doc_type": doc_data["doc_type"],
            "collection": collection,
            "file_path": str(file_path),
            "updated_at": now,
        })
        if "created_at" not in entry:
            entry["created_at"] = now
        self._registry["documents"][doc_id] = entry
        self._save_registry()

        # Append version sidecar
        self._append_version(doc_id, doc_data, now)

        return {"id": doc_id, "status": "created", "file": str(file_path)}

    def _append_version(self, doc_id: str, doc_data: Dict, timestamp: str):
        sidecar = self._versions_dir / f"{doc_id}.json"
        versions: List[Dict] = []
        if sidecar.exists():
            try:
                versions = json.loads(sidecar.read_text())
            except Exception:
                versions = []

        versions.insert(0, {
            "author_type": doc_data.get("author_type", "ai"),
            "author_metadata": doc_data.get("author_metadata", {}),
            "created_at": timestamp,
            "doc_type": doc_data.get("doc_type"),
        })
        sidecar.write_text(json.dumps(versions, indent=2))

    # ---- read operations ---------------------------------------------------

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get a document by ID from the registry + disk."""
        entry = self._registry["documents"].get(doc_id)
        if not entry:
            return None

        file_path = Path(entry["file_path"])
        content = ""
        if file_path.exists():
            content = file_path.read_text()

        return {
            "id": doc_id,
            "title": entry.get("title", ""),
            "doc_type": entry.get("doc_type", ""),
            "collection": entry.get("collection", ""),
            "repo_url": entry.get("repo_url", ""),
            "repo_name": entry.get("repo_name", ""),
            "content": content,
        }

    def get_document_versions(self, doc_id: str) -> list:
        """Get version history from the sidecar JSON file."""
        sidecar = self._versions_dir / f"{doc_id}.json"
        if not sidecar.exists():
            return []
        try:
            return json.loads(sidecar.read_text())
        except Exception:
            return []

    def get_all_documents(self, limit: int = 1000) -> list:
        """List all documents in the registry."""
        docs = list(self._registry["documents"].values())
        return docs[:limit]

    def get_documents_by_repo(self, repo_url: str, limit: int = 100) -> list:
        """Get documents filtered by repository URL."""
        return [
            doc for doc in self._registry["documents"].values()
            if doc.get("repo_url") == repo_url
        ][:limit]

    def health_check(self) -> bool:
        """Always healthy for local storage."""
        return True

    # ---- batch operations --------------------------------------------------

    def batch_delete(self, doc_ids: list) -> Dict[str, Any]:
        """Delete documents from disk and registry."""
        if not doc_ids:
            return {"total": 0, "succeeded": 0, "failed": 0, "errors": []}

        succeeded = 0
        errors = []
        for doc_id in doc_ids:
            try:
                entry = self._registry["documents"].pop(doc_id, None)
                if entry:
                    fp = Path(entry["file_path"])
                    if fp.exists():
                        fp.unlink()
                # Also remove version sidecar
                sidecar = self._versions_dir / f"{doc_id}.json"
                if sidecar.exists():
                    sidecar.unlink()
                succeeded += 1
            except Exception as exc:
                errors.append(f"{doc_id}: {exc}")

        self._save_registry()
        return {
            "total": len(doc_ids),
            "succeeded": succeeded,
            "failed": len(doc_ids) - succeeded,
            "errors": errors,
        }
