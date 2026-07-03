import os
import json

TBA1_DIR = r"C:\Users\Mrinmoy\Downloads\tender (2)\tender\backend\uploads\TBA1"
ocr_cache_path = os.path.join(TBA1_DIR, "ocr_cache.json")

if os.path.exists(ocr_cache_path):
    with open(ocr_cache_path, "rb") as f:
        content_bytes = f.read()
    content = content_bytes.decode("utf-8", errors="ignore")
    
    print("Original length:", len(content))
    
    # Try backtracking char by char to find the last valid JSON close point
    success = False
    for i in range(len(content), 0, -1):
        test_str = content[:i].strip()
        if not test_str:
            continue
        
        # Try appending closing brackets/braces to make it valid JSON
        # Since it is a dict: { "key": "val", "key2": "val2 ...
        for suffix in ("", "}", '"}', '" }', ' }', '"]}', '"]}'):
            try:
                candidate = test_str + suffix
                data = json.loads(candidate)
                print(f"REPAIR SUCCESS: Found valid JSON boundary at index {i} with suffix '{suffix}'")
                print(f"Recovered {len(data)} entries.")
                
                # Write repaired cache back to file
                repaired_path = ocr_cache_path + ".repaired"
                with open(repaired_path, "w", encoding="utf-8") as f_out:
                    json.dump(data, f_out, indent=2)
                print("Wrote repaired cache to:", repaired_path)
                
                # Replace original file with repaired file
                os.replace(repaired_path, ocr_cache_path)
                print("Replaced corrupted ocr_cache.json with repaired version!")
                success = True
                break
            except Exception:
                pass
        if success:
            break
            
    if not success:
        print("Failed to repair by backtracking.")
