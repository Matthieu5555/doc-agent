#!/usr/bin/env python3
import re

# Read the file
with open('/notes/DerivativesGPT-softdev.md', 'r') as f:
    content = f.read()

# Extract just the content (after all frontmatter)
match = re.search(r'^# DerivativesGPT', content, re.MULTILINE)
if not match:
    print("ERROR: Could not find content start")
    exit(1)

clean_content = content[match.start():]

# Create new frontmatter
frontmatter = """---
id: doc-016967f9a050-softdev
repo_url: "https://github.com/Matthieu5555/DerivativesGPT"
repo_name: DerivativesGPT
doc_type: softdev
generated_at: "2026-01-29T11:03:14.633324"
generator: openhands-autonomous-agent
version: 1.0
agent: openhands-autonomous
model: mistralai/devstral-2512
---

"""

# Combine and write
with open('/notes/DerivativesGPT-softdev.md', 'w') as f:
    f.write(frontmatter + clean_content)

print("Softdev file cleaned successfully!")
print(f"New size: {len(frontmatter + clean_content)} bytes")
