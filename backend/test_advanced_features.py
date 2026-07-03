"""Advanced Features Endpoint Tester for the GEM Tender Evaluation System."""
import requests
import sys
import os

os.environ["PYTHONIOENCODING"] = "utf-8"
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass  # In case stdout doesn't support reconfigure in some environments

BASE = "http://127.0.0.1:8000"

def login():
    r = requests.post(f"{BASE}/token", data={"username": "admin", "password": "admin123"})
    if r.status_code != 200:
        print(f"LOGIN FAILED: {r.status_code} {r.text}")
        sys.exit(1)
    token = r.json()["access_token"]
    print(f"[OK] Login successful")
    return {"Authorization": f"Bearer {token}"}

def run_tests():
    headers = login()
    
    # Get a valid tender_id
    r = requests.get(f"{BASE}/tenders", headers=headers)
    assert r.status_code == 200, f"Failed to get tenders: {r.text}"
    tenders = r.json()
    assert len(tenders) > 0, "No tenders found in system!"
    tender_id = tenders[0]["id"]
    print(f"[OK] Isolated target Tender ID: {tender_id}")

    print("\n=== FEATURE 1: INTERACTIVE COLLUSION NETWORK GRAPH ===")
    r = requests.get(f"{BASE}/reports/cartel-graph", headers=headers)
    assert r.status_code == 200, f"Cartel graph failed: {r.text}"
    graph_data = r.json()
    assert "nodes" in graph_data and "edges" in graph_data, "Malformed graph structure!"
    print(f"[OK] Found {len(graph_data['nodes'])} nodes and {len(graph_data['edges'])} edges in network.")
    
    # Verify edge metadata is present
    if len(graph_data["edges"]) > 0:
        first_edge = graph_data["edges"][0]
        assert "collusion_level" in first_edge, "Edge missing collusion_level!"
        assert "signals" in first_edge, "Edge missing collusion signals list!"
        assert "distance_m" in first_edge, "Edge missing distance parameter!"
        print(f"[OK] Edge telemetry matches: collusion_level={first_edge['collusion_level']}, signals={first_edge['signals']}")
    else:
        print("[WARN] No edges found to assert collusion metadata on.")

    print("\n=== FEATURE 2: MULTI-AGENT NEGOTIATION SWARM PLAYGROUND ===")
    swarm_payload = {
        "tender_id": tender_id,
        "message": "Verify compliance and check cost savings potential.",
        "agent": "PLANNER",
        "temperature": 0.3,
        "target_savings_pct": 5.0
    }
    r = requests.post(f"{BASE}/ai-ops/swarm-interactive", headers=headers, json=swarm_payload)
    assert r.status_code == 200, f"Swarm interactive call failed: {r.text}"
    swarm_res = r.json()
    assert "reply" in swarm_res or "debate" in swarm_res, "Swarm did not return debate or reply payload!"
    if "reply" in swarm_res:
        reply_content = swarm_res['reply']['content']
        print(f"[OK] Agent response: {reply_content[:120]}...")
    elif "debate" in swarm_res:
        print(f"[OK] Swarm debate completed with {len(swarm_res['debate'])} contributions.")

    print("\n=== FEATURE 3: DYNAMIC CUSTOM PQC RULE BUILDER ===")
    # 1. Fetch current rules
    r = requests.get(f"{BASE}/reports/pqc-rules", headers=headers)
    assert r.status_code == 200, f"Failed to get PQC rules: {r.text}"
    rules = r.json()
    assert "exp_3_orders_lakhs" in rules, "PQC Rules missing exp_3_orders_lakhs!"
    orig_val = rules["exp_3_orders_lakhs"]
    print(f"[OK] Fetched current PQC rules. Original 3-order value threshold: {orig_val}L")

    # 2. Update rule thresholds
    new_val = orig_val + 5.0
    rules["exp_3_orders_lakhs"] = new_val
    r = requests.post(f"{BASE}/reports/pqc-rules", headers=headers, json={"thresholds": rules})
    assert r.status_code == 200, f"Failed to save PQC rules: {r.text}"
    print(f"[OK] Saved updated PQC rules (new 3-order threshold: {new_val}L)")

    # 3. Verify rule changes synced
    r = requests.get(f"{BASE}/reports/pqc-rules", headers=headers)
    assert r.status_code == 200
    updated_rules = r.json()
    assert updated_rules["exp_3_orders_lakhs"] == new_val, f"Threshold mismatch after sync! Expected {new_val}, got {updated_rules['exp_3_orders_lakhs']}"
    print(f"[OK] Verified MongoDB and file sync of rules successfully.")

    # 4. Revert to original rule threshold to avoid breaking other tests
    rules["exp_3_orders_lakhs"] = orig_val
    r = requests.post(f"{BASE}/reports/pqc-rules", headers=headers, json={"thresholds": rules})
    assert r.status_code == 200
    print(f"[OK] Reverted PQC rules back to original threshold: {orig_val}L")

    print("\n=== FEATURE 4: AUTOMATED PDF AUDIT DOSSIER COMPILER ===")
    r = requests.get(f"{BASE}/reports/download-dossier/{tender_id}", headers=headers)
    assert r.status_code == 200, f"Failed to download PDF dossier: {r.text}"
    assert r.headers.get("content-type") == "application/pdf", f"Unexpected content-type: {r.headers.get('content-type')}"
    pdf_content = r.content
    assert len(pdf_content) > 1000, "Downloaded PDF is suspiciously small!"
    print(f"[OK] Downloaded PDF Dossier successfully. Content size: {len(pdf_content)} bytes")

    print("\n=== FEATURE 5: AUTOMATED DOCUMENT PLAGIARISM & METADATA CROSS-CHECKER ===")
    r = requests.get(f"{BASE}/documents/plagiarism-report", headers=headers)
    assert r.status_code == 200, f"Plagiarism report failed: {r.text}"
    plag_res = r.json()
    assert "summary" in plag_res, "Plagiarism report missing summary!"
    assert "matches" in plag_res, "Plagiarism report missing matches!"
    
    summary = plag_res["summary"]
    assert "total_comparisons" in summary, "Summary missing total_comparisons!"
    assert "risk_level" in summary, "Summary missing risk_level!"
    
    print(f"[OK] Total comparisons run: {summary['total_comparisons']}")
    print(f"[OK] Risk level: {summary['risk_level']}")
    print(f"[OK] Flagged plagiarism matches: {summary['flagged_plagiarism']}")
    print(f"[OK] Flagged metadata matches: {summary['flagged_metadata']}")
    print(f"[OK] Plagiarism report matches count: {len(plag_res['matches'])}")

    print("\n[OK] ALL ADVANCED FEATURES TESTS COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    try:
        run_tests()
    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILURE: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] UNEXPECTED ERROR: {e}")
        sys.exit(1)
