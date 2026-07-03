import os
import sys
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))
from backend.routers.reports_pqc import _get_ai_layout_segments, get_pqc_comparison_data

TBA1_DIR = r"C:\Users\Mrinmoy\Downloads\tender (2)\tender\backend\uploads\TBA1"

print("Checking layout_cache.json...")
layout_path = os.path.join(TBA1_DIR, "layout_cache.json")
if os.path.exists(layout_path):
    with open(layout_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print("Vendors in layout cache:", len(data))
    for k in sorted(data.keys()):
        print(f" - {k}: {len(data[k])} segments")
else:
    print("layout_cache.json does NOT exist!")

print("\nProfiling get_pqc_comparison_data()...")
t0 = time.time()
res = get_pqc_comparison_data(refresh=False)
t1 = time.time()
print(f"get_pqc_comparison_data() completed in {t1 - t0:.2f} seconds.")
print("Summary of result:", res.get("summary"))
