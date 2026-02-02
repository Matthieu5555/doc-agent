#!/usr/bin/env python3
"""
Document Registry - ID-based tracking system for generated documentation

This allows users to move/rename documents in SilverBullet without breaking
our ability to find and update them. Each document has a unique ID in its
frontmatter, and we maintain a registry for fast lookups.
"""

import json
import hashlib
import os
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
import re


REGISTRY_FILE = Path(os.getenv("OUTPUT_DIR", "./output")) / ".doc_registry.json"


def generate_doc_id(repo_url: str, path: str = "", title: str = "", doc_type: str = "") -> str:
    """
    Generate a unique, stable ID for a document.

    ⚠️  WARNING: This duplicates logic from backend/app/services/document_service.py
        If you change hash lengths or algorithm, update BOTH places!
        TODO: Extract to shared library or make agent call backend API

    New format: doc-{repo_hash}-{path_hash}
    Example: doc-a1b2c3d4-e5f6g7h8

    Legacy format: doc-{repo_hash}-{type}
    Example: doc-a1b2c3d4-client

    Args:
        repo_url: Repository URL
        path: Folder path (e.g., "User Guide/Advanced")
        title: Document title (e.g., "Async Patterns")
        doc_type: Legacy field (used for backward compatibility)

    Returns:
        Unique document ID
    """
    # Hash lengths - MUST MATCH backend/app/services/document_service.py constants!
    DOC_ID_REPO_HASH_LENGTH = 12  # Collision-resistant for ~10M repos
    DOC_ID_PATH_HASH_LENGTH = 12  # Combined with repo = 24-char unique ID

    repo_hash = hashlib.sha256(repo_url.encode()).hexdigest()[:DOC_ID_REPO_HASH_LENGTH]

    # Use path + title for new hierarchical docs
    if path or title:
        full_path = f"{path}/{title}" if path else title
        path_hash = hashlib.sha256(full_path.encode()).hexdigest()[:DOC_ID_PATH_HASH_LENGTH]
        return f"doc-{repo_hash}-{path_hash}"

    # Legacy fallback: use doc_type
    if doc_type:
        return f"doc-{repo_hash}-{doc_type}"

    # Default fallback
    return f"doc-{repo_hash}-default"


def parse_frontmatter(content: str) -> tuple[Optional[Dict], str]:
    """
    Parse YAML frontmatter from markdown content (legacy, top-of-file).

    Returns:
        (metadata_dict, body_content)
    """
    # Check for frontmatter (starts with ---)
    if not content.startswith("---\n"):
        return None, content

    # Find end of frontmatter
    end_match = re.search(r'\n---\n', content[4:])
    if not end_match:
        return None, content

    end_pos = end_match.end() + 4
    frontmatter_text = content[4:end_pos-4]
    body = content[end_pos:]

    # Parse YAML (simple key: value parsing)
    metadata = {}
    for line in frontmatter_text.split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            metadata[key.strip()] = value.strip().strip('"\'')

    return metadata, body


def parse_bottomatter(content: str) -> tuple[Optional[Dict], str]:
    """
    Parse YAML bottom matter from markdown content (new format).

    Returns:
        (metadata_dict, body_content)
    """
    # Look for bottom matter pattern: \n---\nkey: value\n---\n at end
    pattern = r'\n---\n((?:[^\n]+:[^\n]+\n?)+)---\s*$'
    match = re.search(pattern, content)

    if not match:
        return None, content

    bottomatter_text = match.group(1)
    body = content[:match.start()]

    # Parse YAML (simple key: value parsing)
    metadata = {}
    for line in bottomatter_text.split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            metadata[key.strip()] = value.strip().strip('"\'')

    return metadata, body


def find_document_by_id(doc_id: str, notes_dir: Path = Path(os.getenv("OUTPUT_DIR", "./output"))) -> Optional[Path]:
    """
    Search for a document with the given ID by scanning metadata (frontmatter or bottomatter).

    This is more reliable than registry lookups since users can move files.
    """
    for md_file in notes_dir.rglob("*.md"):
        try:
            content = md_file.read_text()
            # Try bottom matter first (new format)
            metadata, _ = parse_bottomatter(content)
            # Fall back to frontmatter (legacy format)
            if not metadata:
                metadata, _ = parse_frontmatter(content)
            if metadata and metadata.get('id') == doc_id:
                return md_file
        except Exception:
            continue

    return None


class DocumentRegistry:
    """
    Registry for tracking generated documents.

    This is a lightweight index for fast lookups, but the source of truth
    is the document frontmatter itself.
    """

    def __init__(self, registry_path: Path = REGISTRY_FILE):
        self.registry_path = registry_path
        self.data = self._load()

    def _load(self) -> Dict:
        """Load registry from disk."""
        if self.registry_path.exists():
            try:
                return json.loads(self.registry_path.read_text())
            except Exception:
                return {"documents": {}, "version": "1.0"}
        return {"documents": {}, "version": "1.0"}

    def _save(self):
        """Save registry to disk."""
        self.registry_path.write_text(json.dumps(self.data, indent=2))

    def register_document(
        self,
        doc_id: str,
        repo_url: str,
        doc_type: str,
        file_path: str,
        metadata: Optional[Dict] = None
    ):
        """
        Register a newly generated document.

        Args:
            doc_id: Unique document ID
            repo_url: GitHub repository URL
            doc_type: "client" or "softdev"
            file_path: Current path to the document
            metadata: Additional metadata
        """
        self.data["documents"][doc_id] = {
            "id": doc_id,
            "repo_url": repo_url,
            "repo_name": repo_url.rstrip('/').split('/')[-1],
            "doc_type": doc_type,
            "file_path": file_path,
            "generated_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "generation_count": 1,
            "metadata": metadata or {}
        }
        self._save()

    def update_document(self, doc_id: str, file_path: str):
        """Update document location and timestamp."""
        if doc_id in self.data["documents"]:
            doc = self.data["documents"][doc_id]
            doc["file_path"] = file_path
            doc["updated_at"] = datetime.utcnow().isoformat()
            doc["generation_count"] = doc.get("generation_count", 1) + 1
            self._save()

    def find_document(self, doc_id: str) -> Optional[Dict]:
        """Find document by ID in registry."""
        return self.data["documents"].get(doc_id)

    def find_by_repo(self, repo_url: str) -> List[Dict]:
        """Find all documents for a given repository."""
        return [
            doc for doc in self.data["documents"].values()
            if doc["repo_url"] == repo_url
        ]

    def list_all(self) -> List[Dict]:
        """List all registered documents."""
        return list(self.data["documents"].values())


def create_document_with_metadata(
    content: str,
    doc_id: str,
    repo_url: str,
    doc_type: str,
    collection: str = "",
    additional_metadata: Optional[Dict] = None
) -> str:
    """
    Wrap document content with YAML metadata at the bottom (bottom matter).

    Args:
        content: Markdown content of the document
        doc_id: Unique document ID
        repo_url: GitHub repository URL
        doc_type: "client" or "softdev"
        collection: Optional collection prefix
        additional_metadata: Extra metadata to include

    Returns:
        Complete markdown with bottom matter metadata
    """
    repo_name = repo_url.rstrip('/').split('/')[-1]

    metadata = {
        "id": doc_id,
        "repo_url": repo_url,
        "repo_name": repo_name,
        "doc_type": doc_type,
        "collection": collection,
        "generated_at": datetime.utcnow().isoformat(),
        "generator": "openhands-autonomous-agent",
        "version": "1.0"
    }

    if additional_metadata:
        metadata.update(additional_metadata)

    # Build YAML bottom matter
    bottomatter_lines = ["", "---"]
    for key, value in metadata.items():
        if value:  # Skip empty values
            # Quote values that might contain special characters
            if isinstance(value, str) and (' ' in value or ':' in value):
                bottomatter_lines.append(f'{key}: "{value}"')
            else:
                bottomatter_lines.append(f'{key}: {value}')
    bottomatter_lines.append("---")

    return content + '\n'.join(bottomatter_lines)


# Example usage and testing
if __name__ == "__main__":
    # Test ID generation
    repo_url = "https://github.com/django/django"
    doc_id = generate_doc_id(repo_url, "client")
    print(f"Generated ID: {doc_id}")

    # Test document creation
    content = "# Django\n\nDjango is a web framework..."
    doc_with_metadata = create_document_with_metadata(
        content=content,
        doc_id=doc_id,
        repo_url=repo_url,
        doc_type="client",
        collection="backend"
    )
    print("\nDocument with metadata:")
    print(doc_with_metadata[:500])

    # Test registry
    registry = DocumentRegistry()
    registry.register_document(
        doc_id=doc_id,
        repo_url=repo_url,
        doc_type="client",
        file_path="/notes/backend/django-client.md"
    )
    print(f"\nRegistered document: {doc_id}")

    found = registry.find_document(doc_id)
    print(f"Found in registry: {found}")
