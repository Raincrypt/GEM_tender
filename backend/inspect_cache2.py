import os
import json

TBA1_DIR = r"C:\Users\Mrinmoy\Downloads\tender (2)\tender\backend\uploads\TBA1"
ocr_cache_path = os.path.join(TBA1_DIR, "ocr_cache.json")

print("Checking if ocr_cache.json can be loaded...")
try:
    with open(ocr_cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print("Success! Loaded", len(data), "keys from ocr_cache.json.")
except Exception as e:
    print("Failed to load ocr_cache.json:")
    import traceback
    traceback.print_exc()
