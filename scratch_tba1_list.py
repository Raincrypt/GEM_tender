import os
import re
import sys
import json

# Set output encoding to UTF-8
sys.stdout.reconfigure(encoding='utf-8')

# Add backend to path to import settings
sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))
from routers.reports_pqc import get_tba1_dir_path

tba1_dir = get_tba1_dir_path()
print("TBA1 Dir:", tba1_dir)
if not os.path.exists(tba1_dir):
    print("Directory does not exist!")
    sys.exit(1)

subdirs = sorted(os.listdir(tba1_dir))
for s in subdirs:
    if s.upper() in ["OCR_CACHE.JSON", "THUMBNAILS"]:
        continue
    subdir_path = os.path.join(tba1_dir, s)
    if os.path.isdir(subdir_path):
        print("=" * 60)
        print("Vendor folder:", s)
        files = sorted(os.listdir(subdir_path))
        print("Files:")
        for f in files:
            fpath = os.path.join(subdir_path, f)
            print(f"  - {f} ({os.path.getsize(fpath)} bytes)")
