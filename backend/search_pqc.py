import os

def main():
    path = "uploads/pqc_text.txt"
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return
        
    print(f"Searching in {path}...")
    queries = ["40.00L", "\u20b940.00L", "40.00", "40L", "40,00,000", "4000000", "40.00 Lakh", "40 Lakh"]
    
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
        
    found = False
    for idx, line in enumerate(lines):
        for q in queries:
            if q.lower() in line.lower():
                found = True
                print(f"Match found for term '{q}' at line {idx+1}:")
                start = max(0, idx - 2)
                end = min(len(lines), idx + 3)
                for i in range(start, end):
                    prefix = ">>> " if i == idx else "    "
                    print(f"{prefix}{lines[i].strip()}")
                print("-" * 40)
                break
                
    if not found:
        print("No matches found in pqc_text.txt")

if __name__ == "__main__":
    main()
