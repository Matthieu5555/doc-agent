#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import shutil
import re

# Archive current softdev doc
softdev_path = Path("/notes/DerivativesGPT-softdev.md")
if softdev_path.exists():
    content = softdev_path.read_text()

    # Extract timestamp from frontmatter
    match = re.search(r'generated_at: "([^"]+)"', content)
    if match:
        timestamp = match.group(1).replace(':', '-').replace('.', '-')
    else:
        timestamp = datetime.utcnow().isoformat().replace(':', '-').replace('.', '-')

    # Create history directory
    history_dir = Path("/notes/history/doc-016967f9a050-softdev")
    history_dir.mkdir(parents=True, exist_ok=True)

    # Archive file
    archive_path = history_dir / f"{timestamp}.md"
    shutil.copy2(softdev_path, archive_path)

    print(f"Archived softdev doc to: {archive_path}")
    print(f"File size: {archive_path.stat().st_size} bytes")
else:
    print("ERROR: Softdev doc not found")
