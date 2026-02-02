#!/usr/bin/env python3
import re
from pathlib import Path

def clean_document(file_path):
    """Remove accumulated footers and clean frontmatter."""
    content = Path(file_path).read_text()

    # Strip frontmatter
    if content.startswith("---\n"):
        end_match = re.search(r'\n---\n', content[4:])
        if end_match:
            end_pos = end_match.end() + 4
            frontmatter_text = content[4:end_pos-4]
            body = content[end_pos:]
        else:
            body = content
    else:
        body = content
        frontmatter_text = ""

    # Extract just the main content (strip all footers)
    # Find the first footer marker and remove everything after it
    footer_pattern = r'\n---\n\n\*Documentation.*'
    body_clean = re.split(footer_pattern, body, maxsplit=1)[0]

    # Get metadata from first frontmatter block
    metadata = {}
    for line in frontmatter_text.split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            metadata[key.strip()] = value.strip().strip('"\'')

    # Rebuild frontmatter
    frontmatter_lines = ["---"]
    for key in ['id', 'repo_url', 'repo_name', 'doc_type', 'generated_at', 'generator', 'version', 'agent', 'model']:
        if key in metadata:
            value = metadata[key]
            if ' ' in value or ':' in value:
                frontmatter_lines.append(f'{key}: "{value}"')
            else:
                frontmatter_lines.append(f'{key}: {value}')
    frontmatter_lines.append("---\n")

    # Write back
    Path(file_path).write_text('\n'.join(frontmatter_lines) + body_clean.lstrip())

    print(f"Cleaned: {file_path}")
    print(f"  Frontmatter keys: {list(metadata.keys())}")
    print(f"  Content length: {len(body_clean)} bytes")

# Clean both docs
clean_document('/notes/DerivativesGPT-client.md')
clean_document('/notes/DerivativesGPT-softdev.md')

print("\nDone!")
