#!/usr/bin/env python3
"""
Create version history index pages for documents in SilverBullet.
Allows users to browse and select different versions of generated docs.
"""

from pathlib import Path
from datetime import datetime
import json

def create_version_index(doc_id: str, repo_name: str, doc_type: str):
    """
    Create a version history index page for a document.

    Args:
        doc_id: Document ID (e.g., doc-016967f9a050-client)
        repo_name: Repository name
        doc_type: Document type (client/softdev)
    """
    history_dir = Path(f"/notes/history/{doc_id}")

    if not history_dir.exists():
        print(f"No history found for {doc_id}")
        return

    # List all archived versions
    versions = sorted(history_dir.glob("*.md"), key=lambda p: p.stem, reverse=True)

    if not versions:
        print(f"No versions found in {history_dir}")
        return

    # Create index page
    index_content = f"""---
id: {doc_id}-history
doc_id: {doc_id}
repo_name: {repo_name}
doc_type: {doc_type}
page_type: version-history
---

# Version History: {repo_name} ({doc_type})

This page lists all generated versions of the **{repo_name} {doc_type}** documentation.

## Available Versions

"""

    for version_file in versions:
        # Parse timestamp from filename
        timestamp_str = version_file.stem
        try:
            # Convert ISO format timestamp (handle the extra precision)
            # Format: 2026-01-29T11-10-49-656819
            parts = timestamp_str.split('T')
            date_part = parts[0]
            time_part = parts[1].replace('-', ':')
            # Reconstruct with colons for time
            iso_str = f"{date_part}T{time_part}"
            dt = datetime.fromisoformat(iso_str)
            display_time = dt.strftime("%d %B %Y at %I:%M%p")
        except Exception as e:
            # Fallback to raw timestamp
            display_time = timestamp_str

        # Create SilverBullet wikilink to version
        page_name = f"history/{doc_id}/{version_file.stem}"
        index_content += f"- [[{page_name}|{display_time}]]\n"

    index_content += f"""

## Current Version

The current version is available at: [[{repo_name}-{doc_type}]]

---

*Version history is automatically maintained. Each time documentation is regenerated, the previous version is archived here.*
"""

    # Write index page
    index_path = Path(f"/notes/{repo_name}-{doc_type}-history.md")
    index_path.write_text(index_content)

    print(f"Created version index: {index_path}")
    print(f"  Total versions: {len(versions)}")

if __name__ == "__main__":
    # Create index for DerivativesGPT docs
    create_version_index(
        "doc-016967f9a050-client",
        "DerivativesGPT",
        "client"
    )
    create_version_index(
        "doc-016967f9a050-softdev",
        "DerivativesGPT",
        "softdev"
    )
