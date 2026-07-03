import re

def find_endpoints(filepath):
    print(f"=== Endpoints in {filepath} ===")
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # Find endpoints in fetches or requests
    matches = re.finditer(r'/(?:reports|ai-ops|documents|tenders)/[a-zA-Z0-9_/-]*', content)
    found = set(m.group(0) for m in matches)
    for f in sorted(found):
        print(f"  - {f}")

find_endpoints('../frontend/tender_rules_understanding.html')
find_endpoints('../frontend/dynamic_rule_analyzer.html')
find_endpoints('../frontend/ai_intelligence.html')
find_endpoints('../frontend/pqc_comparison.html')
