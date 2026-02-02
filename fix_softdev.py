#!/usr/bin/env python3
from pathlib import Path

# Read softdev doc
softdev_path = Path("/notes/DerivativesGPT-softdev.md")
lines = softdev_path.read_text().split('\n')

# Find the header line
header_found = False
content_start = 0

for i, line in enumerate(lines):
    if line.startswith('*Documentation Written'):
        header_found = True
    elif header_found and line.startswith('#'):
        # Found the content start
        content_start = i
        break

if content_start == 0:
    print("ERROR: Could not find content start")
    exit(1)

# Find bottom matter
bottom_matter_start = 0
for i in range(len(lines) - 1, 0, -1):
    if lines[i] == '---' and i > content_start:
        # Check if this is the bottom matter
        if any(':' in lines[j] for j in range(i-10, i)):
            bottom_matter_start = i - 10  # Approximate start
            # Find exact start
            for j in range(i-1, content_start, -1):
                if lines[j] == '' and j < i - 1:
                    bottom_matter_start = j + 1
                    break
            break

if bottom_matter_start == 0:
    print("ERROR: Could not find bottom matter")
    exit(1)

# Rebuild: header + content + bottom matter
header = lines[0]
content = '\n'.join(lines[content_start:bottom_matter_start])
bottom_matter = '\n'.join(lines[bottom_matter_start:])

# Clean up extra blank lines
while content.startswith('\n'):
    content = content[1:]
while content.endswith('\n\n\n'):
    content = content[:-1]

new_content = f"{header}\n\n{content}{bottom_matter}"

softdev_path.write_text(new_content)

print(f"Fixed softdev doc")
print(f"Header: line 0")
print(f"Content: lines {content_start} to {bottom_matter_start}")
print(f"Bottom matter: lines {bottom_matter_start} to end")
