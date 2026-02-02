#!/usr/bin/env python3
"""
Add version history section to generated documents.

Scans history/ folder and adds links at the bottom of the main document.
"""

from pathlib import Path
from datetime import datetime
import re


def format_timestamp(timestamp_str: str) -> str:
    """Convert ISO timestamp filename to readable format."""
    try:
        # Remove the file extension and handle the modified ISO format
        ts = timestamp_str.replace('.md', '').replace('-', ':', 2).replace('-', '.', 1)
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%B %d, %Y at %I:%M:%S %p UTC")
    except:
        return timestamp_str


def build_version_history_section(doc_id: str, notes_dir: Path = Path("/notes")) -> str:
    """
    Build version history section with links to archived versions.

    Args:
        doc_id: Document ID (e.g., "doc-016967f9a050-client")
        notes_dir: Root notes directory

    Returns:
        Markdown string with version history section
    """
    history_dir = notes_dir / "history" / doc_id

    if not history_dir.exists():
        return ""

    # Find all version files
    version_files = sorted(history_dir.glob("*.md"), key=lambda p: p.stem, reverse=True)

    if not version_files:
        return ""

    # Build section
    section = "\n\n---\n\n## Version History\n\n"
    section += "Previous versions of this documentation:\n\n"

    for version_file in version_files:
        timestamp_filename = version_file.stem
        readable_date = format_timestamp(timestamp_filename)

        # Create SilverBullet wiki link to the history file
        relative_path = f"history/{doc_id}/{version_file.name}"
        section += f"- [[{relative_path}|{readable_date}]]\n"

    return section


def add_version_history_to_doc(doc_path: Path, doc_id: str):
    """
    Add version history section to a document (before bottom matter).

    Args:
        doc_path: Path to the main document
        doc_id: Document ID for finding history
    """
    if not doc_path.exists():
        print(f"[Error] Document not found: {doc_path}")
        return

    content = doc_path.read_text()

    # Remove any existing version history section
    content = re.sub(
        r'\n---\n\n## Version History\n\n.*?(?=\n---\n[a-z_]+:|$)',
        '',
        content,
        flags=re.DOTALL
    )

    # Find the bottom matter (metadata at end)
    # Pattern: \n---\nkey: value\n---\n at end
    bottomatter_pattern = r'(\n---\n(?:[^\n]+:[^\n]+\n?)+---\s*)$'
    bottomatter_match = re.search(bottomatter_pattern, content)

    if not bottomatter_match:
        print(f"[Warning] No bottom matter found in {doc_path}")
        return

    # Build version history section
    version_section = build_version_history_section(doc_id)

    if not version_section:
        print(f"[Info] No version history found for {doc_id}")
        return

    # Insert version history BEFORE bottom matter
    insert_pos = bottomatter_match.start()
    new_content = content[:insert_pos] + version_section + content[insert_pos:]

    # Write back
    doc_path.write_text(new_content)
    print(f"[Updated] Added version history to: {doc_path}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python add_version_history.py <doc_path> <doc_id>")
        sys.exit(1)

    doc_path = Path(sys.argv[1])
    doc_id = sys.argv[2]

    add_version_history_to_doc(doc_path, doc_id)
