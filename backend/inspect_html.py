import re
import sys

# Reconfigure stdout to use UTF-8 to prevent UnicodeEncodeError on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def analyze_file(filepath):
    print(f"=== Analyzing {filepath} ===")
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    lines = content.split('\n')
    for idx, line in enumerate(lines):
        line_num = idx + 1
        if any(term in line for term in ['card', 'panel', 'section', 'tab-', 'chart', 'plot']) and ('class=' in line or 'id=' in line):
            if any(term in line.lower() for term in ['header', 'title', 'heading', 'nav', 'tab', 'h1', 'h2', 'h3', 'h4', 'h5']):
                print(f"Line {line_num}: {line.strip()}")
        elif '<!--' in line and any(term in line.lower() for term in ['section', 'tab', 'chart', 'card', 'module', 'analytics', 'forensic', 'plagiarism', 'predictive', 'forecast', 'rag', 'doc', 'rule', 'compliance']):
            print(f"Line {line_num}: {line.strip()}")

analyze_file('../frontend/tender_rules_understanding.html')
analyze_file('../frontend/dynamic_rule_analyzer.html')
