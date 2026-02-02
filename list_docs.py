#!/usr/bin/env python3
"""
Document Registry Utility

List, search, and manage documents by ID.
Demonstrates that documents can be moved/renamed without breaking the system.
"""

import sys
from pathlib import Path
from doc_registry import DocumentRegistry, find_document_by_id, parse_frontmatter


def list_all_documents():
    """List all registered documents."""
    registry = DocumentRegistry()
    docs = registry.list_all()

    if not docs:
        print("No documents registered yet.\n")
        return

    print("="*80)
    print("[Registry] REGISTERED DOCUMENTS")
    print("="*80)

    for doc in docs:
        print(f"\n[ID] ID: {doc['id']}")
        print(f"   Repository: {doc['repo_name']}")
        print(f"   Type: {doc['doc_type']}")
        print(f"   File: {doc['file_path']}")
        print(f"   Generated: {doc['generated_at']}")
        print(f"   Updated: {doc['updated_at']}")
        print(f"   Generations: {doc.get('generation_count', 1)}")

    print(f"\n[Summary] Total: {len(docs)} documents\n")


def search_by_repo(repo_url: str):
    """Find all documents for a repository."""
    registry = DocumentRegistry()
    docs = registry.find_by_repo(repo_url)

    print(f"[Search] Documents for: {repo_url}\n")

    if not docs:
        print("No documents found.\n")
        return

    for doc in docs:
        print(f"  • {doc['doc_type'].upper()}: {doc['file_path']} (ID: {doc['id']})")

    print()


def verify_document(doc_id: str):
    """
    Verify a document exists and show its location.

    This demonstrates that we can find documents even if they've been moved.
    """
    print(f"[Search] Searching for document: {doc_id}\n")

    # Check registry
    registry = DocumentRegistry()
    reg_doc = registry.find_document(doc_id)

    if reg_doc:
        print(f"[Task] Registry Entry:")
        print(f"   File: {reg_doc['file_path']}")
        print(f"   Repository: {reg_doc['repo_name']}")
        print(f"   Type: {reg_doc['doc_type']}\n")

    # Scan filesystem (source of truth)
    actual_path = find_document_by_id(doc_id, Path("/notes"))

    if actual_path:
        print(f"[Success] Document Found on Filesystem:")
        print(f"   Location: {actual_path}")

        # Read metadata
        content = actual_path.read_text()
        metadata, _ = parse_frontmatter(content)

        if metadata:
            print(f"\n[File] Document Metadata:")
            for key, value in metadata.items():
                print(f"   {key}: {value}")

        # Check if location matches registry
        if reg_doc and str(actual_path) != reg_doc['file_path']:
            print(f"\n[Warning]  LOCATION MISMATCH:")
            print(f"   Registry says: {reg_doc['file_path']}")
            print(f"   Actually at:   {actual_path}")
            print(f"   (User moved the file - this is OK! We can still track it by ID)")

    else:
        print(f"[Error] Document not found in /notes")

    print()


def scan_all_documents():
    """Scan /notes directory for all documents with IDs."""
    print("[Search] Scanning /notes for documents with IDs...\n")

    notes_dir = Path("/notes")
    found_docs = []

    for md_file in notes_dir.rglob("*.md"):
        if md_file.name.startswith('.'):
            continue

        try:
            content = md_file.read_text()
            metadata, _ = parse_frontmatter(content)

            if metadata and 'id' in metadata:
                found_docs.append({
                    'file': md_file,
                    'id': metadata['id'],
                    'repo': metadata.get('repo_name', 'Unknown'),
                    'type': metadata.get('doc_type', 'Unknown')
                })
        except Exception:
            continue

    if not found_docs:
        print("No documents with IDs found.\n")
        return

    print(f"Found {len(found_docs)} documents:\n")
    for doc in found_docs:
        print(f"  [ID] {doc['id']}")
        print(f"     {doc['repo']} ({doc['type']})")
        print(f"     [File] {doc['file']}\n")


def main():
    """Main CLI."""
    if len(sys.argv) < 2:
        print("Document Registry Utility\n")
        print("Usage:")
        print("  python list_docs.py list              - List all registered documents")
        print("  python list_docs.py scan              - Scan filesystem for documents")
        print("  python list_docs.py verify <doc_id>   - Verify document location")
        print("  python list_docs.py repo <repo_url>   - Find docs for repository")
        sys.exit(1)

    command = sys.argv[1]

    if command == "list":
        list_all_documents()
    elif command == "scan":
        scan_all_documents()
    elif command == "verify" and len(sys.argv) > 2:
        verify_document(sys.argv[2])
    elif command == "repo" and len(sys.argv) > 2:
        search_by_repo(sys.argv[2])
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
