"""Automated Test Suite for Dynamic System Path Settings Configuration."""
import requests
import json
import sys
import os
import shutil

os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8')


BASE = "http://127.0.0.1:8000"

def login():
    try:
        r = requests.post(f"{BASE}/token", data={"username": "admin", "password": "admin123"}, timeout=5)
        if r.status_code != 200:
            print(f"[ERROR] LOGIN FAILED: {r.status_code} {r.text}")
            sys.exit(1)
        token = r.json()["access_token"]
        print("✓ Authenticated as Admin successfully.")
        return {"Authorization": f"Bearer {token}"}
    except Exception as e:
        print(f"[ERROR] Could not connect to API server at {BASE}: {e}")
        print("Make sure the FastAPI backend server is running.")
        sys.exit(1)

def run_tests():
    headers = login()
    
    print("\n1. Testing GET /settings/paths...")
    r = requests.get(f"{BASE}/settings/paths", headers=headers, timeout=5)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    res = r.json()
    assert "settings" in res, "Missing 'settings' key"
    assert "verification" in res, "Missing 'verification' key"
    assert "defaults" in res, "Missing 'defaults' key"
    print("✓ GET /settings/paths returns correct schema.")
    print("  Current settings:", json.dumps(res["settings"], indent=2))
    
    original_settings = res["settings"]

    print("\n2. Testing POST /settings/paths saving configuration...")
    # Prepare mock custom paths inside backend directory to test creation and visibility
    base_dir = os.path.dirname(os.path.abspath(__file__))
    test_rules_pdf = os.path.join(base_dir, "uploads", "Rules.pdf") # Keep actual rules PDF to verify
    test_tba1 = os.path.join(base_dir, "uploads", "TBA1")
    test_tba2_temp = os.path.join(base_dir, "uploads", "TBA2_Temp_AutoCreate_Test")

    # Clean up temp folder if it already exists from a previous crash
    if os.path.exists(test_tba2_temp):
        shutil.rmtree(test_tba2_temp)

    payload = {
        "rules_pdf_path": test_rules_pdf,
        "tba1_dir_path": test_tba1,
        "tba2_dir_path": test_tba2_temp
    }

    # Save settings without auto-creating. It should succeed but report TBA2 does not exist.
    print(f"  Saving paths: {payload}")
    r = requests.post(f"{BASE}/settings/paths?auto_create_dirs=false", headers=headers, json=payload, timeout=5)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    print("✓ Path configuration saved in DB successfully.")

    # Retrieve settings and verify status
    r = requests.get(f"{BASE}/settings/paths", headers=headers, timeout=5)
    res = r.json()
    assert res["settings"]["tba2_dir_path"] == test_tba2_temp
    assert res["verification"]["tba2_dir_path"]["exists"] is False, "TBA2 should not exist yet"
    print("✓ Path settings verification correctly flags non-existent folders.")

    # Save settings WITH auto-create. The folder should be created on disk!
    print("\n3. Testing Folder Auto-Creation feature...")
    r = requests.post(f"{BASE}/settings/paths?auto_create_dirs=true", headers=headers, json=payload, timeout=5)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    
    # Verify directory was created on disk
    dir_exists_on_disk = os.path.isdir(test_tba2_temp)
    print(f"  Checking disk for {test_tba2_temp}: {'FOUND' if dir_exists_on_disk else 'MISSING'}")
    assert dir_exists_on_disk, "Folder was not created on disk when auto_create_dirs=true"
    print("✓ Auto-creation of directory successfully verified on physical filesystem.")

    # Check verification endpoint again
    r = requests.get(f"{BASE}/settings/paths", headers=headers, timeout=5)
    res = r.json()
    assert res["verification"]["tba2_dir_path"]["exists"] is True, "TBA2 directory should now exist"
    assert res["verification"]["tba2_dir_path"]["readable"] is True, "TBA2 directory should be readable"
    print("✓ Verification status updated to ready/accessible.")

    # Clean up temp folder from disk
    if os.path.exists(test_tba2_temp):
        shutil.rmtree(test_tba2_temp)
        print("  Cleaned up temp test directory from disk.")

    print("\n4. Testing POST /settings/paths/reset to defaults...")
    r = requests.post(f"{BASE}/settings/paths/reset", headers=headers, timeout=5)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    print("✓ Reset endpoint successfully deleted custom configuration.")

    # Verify defaults are active
    r = requests.get(f"{BASE}/settings/paths", headers=headers, timeout=5)
    res = r.json()
    assert res["settings"]["tba2_dir_path"] == res["defaults"]["tba2_dir_path"]
    print("✓ Settings reverted back to relative defaults.")

    print("\n=======================================================")
    print(" ✓ ALL PATH SETTINGS ENDPOINT TESTS PASSED SUCCESSFULLY ")
    print("=======================================================")

if __name__ == "__main__":
    run_tests()
