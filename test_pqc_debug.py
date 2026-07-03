import requests
import json
import traceback

BASE = "http://127.0.0.1:8000"

try:
    print("Logging in...")
    r = requests.post(f"{BASE}/token", data={"username": "admin", "password": "admin123"}, timeout=10)
    print("Login response:", r.status_code)
    if r.status_code != 200:
        print("Login failed:", r.text)
        exit(1)
        
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    print("Fetching pqc-comparison-data...")
    res = requests.get(f"{BASE}/reports/pqc-comparison-data", headers=headers, timeout=60)
    print("Response status code:", res.status_code)
    print("Response headers:", res.headers)
    if res.status_code == 200:
        print("Success! First 500 chars of JSON:")
        print(res.text[:500])
    else:
        print("Failed to fetch comparisons:", res.text)
except Exception as e:
    print("Exception occurred:")
    traceback.print_exc()
