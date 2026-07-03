import os

TBA1_DIR = r"C:\Users\Mrinmoy\Downloads\tender (2)\tender\backend\uploads\TBA1"
ocr_cache_path = os.path.join(TBA1_DIR, "ocr_cache.json")

if os.path.exists(ocr_cache_path):
    with open(ocr_cache_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    print("Length of content:", len(content))
    pos = 7024543
    start = max(0, pos - 150)
    end = min(len(content), pos + 150)
    print("SURROUNDING CONTENT:")
    print(content[start:end])
