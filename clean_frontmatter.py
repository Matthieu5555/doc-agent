#!/usr/bin/env python3
import re

# Read the file
with open('/notes/DerivativesGPT-client.md', 'r') as f:
    content = f.read()

# Extract just the content (after all frontmatter)
match = re.search(r'^# DerivativesGPT', content, re.MULTILINE)
if not match:
    print("ERROR: Could not find content start")
    exit(1)

clean_content = content[match.start():]

# Create new frontmatter
frontmatter = """---
id: doc-016967f9a050-client
repo_url: "https://github.com/Matthieu5555/DerivativesGPT"
repo_name: DerivativesGPT
doc_type: client
generated_at: "2026-01-29T11:10:49.656819"
generator: openhands-autonomous-agent
version: 1.0
agent: openhands-autonomous
model: mistralai/devstral-2512
---

"""

# Combine and write
with open('/notes/DerivativesGPT-client.md', 'w') as f:
    f.write(frontmatter + clean_content)

print("File cleaned successfully!")
print(f"New size: {len(frontmatter + clean_content)} bytes")
