with open('frontend/pqc_comparison.html', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

start = 1500
end = 1570
for i in range(start, min(end, len(lines))):
    print(f"Line {i+1}: {lines[i].rstrip()}")
