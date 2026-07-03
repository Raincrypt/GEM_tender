import os
import re

filepath_frontend = 'frontend'
for root, dirs, files in os.walk(filepath_frontend):
    for file in files:
        if file.endswith(('.html', '.js')):
            path = os.path.join(root, file)
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            if 'pqc-comparison-data' in content:
                print(f"Found in {path}")
                # Print lines containing it
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if 'pqc-comparison-data' in line:
                        print(f"  Line {i+1}: {line.strip()}")
