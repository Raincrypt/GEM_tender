import requests, json, sys
sys.stdout.reconfigure(encoding='utf-8')

r = requests.get('http://127.0.0.1:8000/reports/pqc-comparison-data', headers={'Authorization': 'Bearer test'})
d = r.json()

for i, v in enumerate(d['vendors'][:4]):
    print(f"\n=== VENDOR {i}: {v['name']} ===")
    print(f"  status: {v['status']}")
    print(f"  baseline: {v.get('baseline_status')}")
    print(f"  confidence: {v.get('confidence')}")
    print(f"  docs: maf={v.get('has_maf')}, cred={v.get('has_credentials')}, annex={v.get('has_annexure')}, fin={v.get('has_financials')}, cert={v.get('has_certificate')}")
    am = v.get('advanced_metadata', {})
    print(f"  monetary: {am.get('monetary_values', [])[:3]}")
    print(f"  risk: {v.get('risk_profile',{}).get('risk_level','?')} overall={v.get('risk_profile',{}).get('overall','?')}")
    print(f"  verdict: {v.get('verdict_reason','')[:120]}")
    print(f"  EVALS ({len(v.get('evaluations',[]))}):")
    for e in v.get('evaluations', []):
        rn = e.get('rule',{}).get('name','?')[:40].encode('ascii','replace').decode()
        print(f"    {e['rule']['id']}: {rn} -> {e['status']} | {e.get('remark','')[:50].encode('ascii','replace').decode()}")
    print(f"  FILES: {[f['type'] for f in v.get('files',[])]}")

print(f"\n\nTOTAL VENDORS: {len(d['vendors'])}")
print("ALL NAMES:", [v['name'] for v in d['vendors']])
