"""Comprehensive endpoint tester for the GEM Tender Evaluation System."""
import requests
import json
import sys
import os
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding='utf-8')

BASE = "http://127.0.0.1:8000"

def login():
    r = requests.post(f"{BASE}/token", data={"username": "admin", "password": "admin123"})
    if r.status_code != 200:
        print(f"LOGIN FAILED: {r.status_code} {r.text}")
        sys.exit(1)
    token = r.json()["access_token"]
    print(f"✓ Login OK")
    return {"Authorization": f"Bearer {token}"}

def test_get(endpoint, headers, label=None):
    try:
        r = requests.get(f"{BASE}{endpoint}", headers=headers, timeout=120)
        status = "✓" if r.status_code == 200 else "✗"
        detail = ""
        if r.status_code != 200:
            try:
                detail = r.json().get("detail", "")[:80]
            except:
                detail = r.text[:80]
        print(f"  {status} GET {endpoint}: {r.status_code} {detail}")
        return r.status_code, r.json() if r.status_code == 200 else None
    except Exception as e:
        print(f"  ✗ GET {endpoint}: EXCEPTION {e}")
        return 0, None

def test_post(endpoint, headers, data=None, label=None):
    try:
        r = requests.post(f"{BASE}{endpoint}", headers=headers, json=data, timeout=120)
        status = "✓" if r.status_code == 200 else "✗"
        detail = ""
        if r.status_code != 200:
            try:
                detail = r.json().get("detail", "")[:80]
            except:
                detail = r.text[:80]
        print(f"  {status} POST {endpoint}: {r.status_code} {detail}")
        return r.status_code, r.json() if r.status_code == 200 else None
    except Exception as e:
        print(f"  ✗ POST {endpoint}: EXCEPTION {e}")
        return 0, None

h = login()

print("\n=== CORE ENDPOINTS ===")
test_get("/", h)
test_get("/reports/dashboard-stats", h)
test_get("/tenders", h)

print("\n=== ANALYTICS ===")
test_get("/analytics/kpi-summary", h)
test_get("/analytics/ai-insights", h)

print("\n=== IOCL PROCUREMENT ===")
test_get("/iocl/stats", h)
test_get("/iocl/indents", h)
test_get("/iocl/purchase-orders", h)
test_get("/iocl/deliveries", h)
test_get("/iocl/payments", h)

print("\n=== C3 COMMAND CENTER ===")
test_get("/c3/metrics", h)
test_get("/c3/iot-nodes", h)
test_get("/c3/agent-heartbeat", h)
test_post("/c3/ask-ai", h, {"query": "show vendor status"})
test_post("/c3/chat", h, {"message": "who won the latest tender?"})

print("\n=== REPORTS & FORENSICS ===")
test_get("/reports/fraud-analysis", h)
test_get("/reports/cartel-graph", h)
test_get("/reports/pqc-comparison-data", h)
test_get("/reports/deep-forensics", h)
test_get("/reports/bid-timing-forensics", h)
test_get("/reports/advanced-bid-analysis", h)
test_get("/reports/predictive-forecast", h)
test_post("/reports/chat", h, {"message": "how many tenders are active?"})
test_get("/reports/command-center", h)

print("\n=== AI OPERATIONS ===")
test_get("/ai-ops/swarm-registry", h)
test_get("/ai-ops/threat-intel", h)
test_get("/ai-ops/anomaly-scan", h)
test_get("/ai-ops/market-intelligence", h)

print("\n=== SECURITY ===")
test_get("/security/blockchain/verify", h)
test_get("/security/audit-logs", h)
test_get("/security/mongodb/status", h)


print("\n=== VENDORS ===")
code, data = test_get("/tenders", h)
if data and len(data) > 0:
    tid = data[0]["id"]
    print(f"\n=== TENDER-SPECIFIC (tender_id={tid}) ===")
    test_get(f"/evaluation/comparative/{tid}", h)
    test_get(f"/reports/cycle-dossier/{tid}", h)
    test_get(f"/analytics/tender-timeline/{tid}", h)
    test_get(f"/reports/advanced-bid-analysis?tender_id={tid}", h)

print("\n=== VENDOR RISK & KYC FORENSICS ===")
# Find a vendor
r = requests.get(f"{BASE}/vendors/", headers=h, timeout=25)
if r.status_code == 200 and r.json():
    vendors = r.json()
    if len(vendors) > 0:
        vid = vendors[0]["id"]
        print(f"Testing vendor intelligence & KYC deepfake checks for vendor {vid} ({vendors[0]['company_name']})")
        test_get(f"/vendors/{vid}/intelligence", h)
        test_get(f"/vendors/{vid}/risk-profile", h)
        
        # Test 1: Secure/Valid KYC Scan (no virtual device, good liveness, proper FPS, resolution, timestamp)
        import datetime
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        valid_kyc_data = {
            "video_hash": "0xABC123456789DEF",
            "liveness_score": 92.5,
            "video_metadata": {
                "is_virtual_device": False,
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "fps": 30.0,
                "resolution": "1280x720"
            },
            "captured_at": now_str
        }
        test_post(f"/vendors/{vid}/kyc-deepfake-scan", h, valid_kyc_data)
        
        # Test 2: Spoofed/Virtual Device KYC Scan (should detect OBS and fail)
        spoofed_kyc_data = {
            "video_hash": "0xABC123456789DEF",
            "liveness_score": 92.5,
            "video_metadata": {
                "is_virtual_device": True,
                "user_agent": "obs-studio virtual camera",
                "fps": 30.0,
                "resolution": "1280x720"
            },
            "captured_at": now_str
        }
        test_post(f"/vendors/{vid}/kyc-deepfake-scan", h, spoofed_kyc_data)

print("\n=== RAG & ADVANCED CLAUSE ENGINE ===")
# Test RAG query
test_post("/ai-ops/rag-query", h, {"question": "turnover requirement for LFD display"})

# Test PQC Clause query
test_post("/reports/pqc-clause-query", h, {"query": "turnover"})
test_post("/reports/pqc-clause-query", h, {"query": "Samsung", "vendor_name": "Samsung"})

print("\nDONE - All endpoints tested.")

