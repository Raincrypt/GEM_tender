import os
import json

TBA1_DIR = r"C:\Users\Mrinmoy\Downloads\tender (2)\tender\backend\uploads\TBA1"
ocr_cache_path = os.path.join(TBA1_DIR, "ocr_cache.json")

with open(ocr_cache_path, "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

print("Content length:", len(content))
try:
    data = json.loads(content)
    print("Loads succeeded!")
except Exception as e:
    print("Loads failed:")
    import traceback
    traceback.print_exc()
