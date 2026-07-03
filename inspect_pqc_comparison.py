import re
import sys

# Reconfigure stdout to use UTF-8 to prevent UnicodeEncodeError on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

filepath = 'frontend/pqc_comparison.html'
with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

print("File length:", len(content))

# Look for search-vendor or urlParams patterns
print("Searching for search-vendor or urlParams...")
lines = content.split('\n')
for i, line in enumerate(lines):
    if "search-vendor" in line or "urlParams" in line or "search" in line.lower() and "input" in line.lower():
        print(f"Line {i+1}: {line.strip()}")

