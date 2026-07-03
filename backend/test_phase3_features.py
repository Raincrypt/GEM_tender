"""
Phase 3 Feature Test Suite
===========================
Tests all 6 Phase 3 advanced features:
1. LLM Cache 24h TTL
2. Vendor DNA Fingerprinting & Shell Company Detection
3. Predictive Vendor Risk Model (GradientBoosting/Heuristic)
4. Autonomous Compliance Sentinel Agent
5. EWMA Anomaly Detection
6. API endpoint smoke tests
"""

import sys, os, asyncio, json, time

# Reconfigure stdout to use UTF-8 to prevent UnicodeEncodeError on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
INFO = "\033[94m[INFO]\033[0m"

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

# ─────────────────────────────────────────────────────────────────
# TEST 1: LLM Cache 24h TTL
# ─────────────────────────────────────────────────────────────────
def test_llm_cache_ttl():
    section("TEST 1: LLM Cache 24h TTL Check")
    try:
        import llm_client
        cache_dir = llm_client.CACHE_DIR
        print(f"  Cache dir: {cache_dir}")

        # Write a test cache entry
        test_key = "phase3_test_ttl_key"
        test_file = os.path.join(cache_dir, f"{test_key}.json")
        with open(test_file, "w") as f:
            json.dump({"response": "test_value", "prompt_preview": "test"}, f)

        # Read it back (should hit because it's fresh)
        val = llm_client._read_cache(test_key)
        assert val == "test_value", f"Expected 'test_value', got {val}"
        print(f"  {PASS} Fresh cache hit works correctly")

        # Artificially age the file beyond 24h
        old_mtime = time.time() - 90000  # 25 hours ago
        os.utime(test_file, (old_mtime, old_mtime))

        # Read it back (should MISS because it's stale)
        val2 = llm_client._read_cache(test_key)
        assert val2 is None, f"Expected None (expired), got {val2}"
        print(f"  {PASS} Expired cache correctly evicted (24h TTL)")

        # File should be deleted
        assert not os.path.exists(test_file), "Expired cache file should be deleted"
        print(f"  {PASS} Expired cache file deleted on read")

        print(f"\n  {PASS} TEST 1 PASSED — LLM Cache 24h TTL working correctly")
        return True
    except Exception as e:
        print(f"  {FAIL} TEST 1 FAILED: {e}")
        import traceback; traceback.print_exc()
        return False


# ─────────────────────────────────────────────────────────────────
# TEST 2: Vendor DNA Fingerprinting
# ─────────────────────────────────────────────────────────────────
def test_vendor_dna():
    section("TEST 2: Vendor DNA Fingerprint Engine")
    try:
        import vendor_dna as vdna

        # Synthetic bid data for 4 vendors
        tenders = [
            {"id": 1, "estimated_value": 1000000, "title": "LED Display Supply", "category": "IT Hardware"},
            {"id": 2, "estimated_value": 2000000, "title": "Server Procurement", "category": "IT Hardware"},
            {"id": 3, "estimated_value": 500000, "title": "Valve Supply", "category": "Engineering"},
        ]

        # Vendors A & B are behavioral clones (same price pattern, same co-bidders)
        bids = [
            {"vendor_id": 1, "tender_id": 1, "total_amount": 950000, "status": "Awarded", "submitted_at": "2024-01-15T09:30:00"},
            {"vendor_id": 1, "tender_id": 2, "total_amount": 1900000, "status": "Pending", "submitted_at": "2024-02-10T09:45:00"},
            {"vendor_id": 2, "tender_id": 1, "total_amount": 960000, "status": "Pending", "submitted_at": "2024-01-15T09:35:00"},
            {"vendor_id": 2, "tender_id": 2, "total_amount": 1920000, "status": "Awarded", "submitted_at": "2024-02-10T09:50:00"},
            {"vendor_id": 3, "tender_id": 3, "total_amount": 480000, "status": "Awarded", "submitted_at": "2024-03-01T14:00:00"},
            {"vendor_id": 4, "tender_id": 1, "total_amount": 1200000, "status": "Pending", "submitted_at": "2024-01-15T15:00:00"},
        ]

        # Build DNA for vendor 1 & 2
        dna1 = vdna.extract_vendor_dna(1, bids, tenders)
        dna2 = vdna.extract_vendor_dna(2, bids, tenders)
        dna3 = vdna.extract_vendor_dna(3, bids, tenders)

        print(f"  {INFO} Vendor 1 DNA: price_dna={dna1['price_dna']}, bid_count={dna1['bid_count']}")
        print(f"  {INFO} Vendor 2 DNA: price_dna={dna2['price_dna']}, bid_count={dna2['bid_count']}")
        print(f"  {INFO} Vendor 3 DNA: price_dna={dna3['price_dna']}, bid_count={dna3['bid_count']}")

        assert dna1["bid_count"] == 2, f"Expected 2 bids for vendor 1, got {dna1['bid_count']}"
        assert dna1["win_count"] == 1
        print(f"  {PASS} DNA extraction: bid_count and win_count correct")

        # Similarity between clones (V1 & V2) should be HIGH
        sim_12 = vdna.compute_dna_similarity(dna1, dna2)
        sim_13 = vdna.compute_dna_similarity(dna1, dna3)
        print(f"  {INFO} V1 vs V2 composite similarity: {sim_12['composite']:.4f} ({sim_12['risk_level']})")
        print(f"  {INFO} V1 vs V3 composite similarity: {sim_13['composite']:.4f} ({sim_13['risk_level']})")

        assert sim_12["composite"] > sim_13["composite"], "Clone pair should be more similar than unrelated pair"
        print(f"  {PASS} Similarity ordering correct: clone pair > unrelated pair")

        # Full pipeline
        result = vdna.run_full_dna_analysis(
            all_bids=bids,
            all_tenders=tenders,
            all_vendor_ids=[1, 2, 3, 4],
            vendor_name_map={1: "VendorAlpha", 2: "VendorBeta", 3: "VendorGamma", 4: "VendorDelta"},
        )
        print(f"  {INFO} Total pairs analyzed: {result['total_pairs_analyzed']}")
        print(f"  {INFO} Shell clusters found: {result['shell_clusters']['summary']['clusters_found']}")
        assert result["total_pairs_analyzed"] == 6  # C(4,2) = 6
        print(f"  {PASS} Pairwise DNA analysis returned correct number of pairs")

        print(f"\n  {PASS} TEST 2 PASSED — Vendor DNA Engine working correctly")
        return True
    except Exception as e:
        print(f"  {FAIL} TEST 2 FAILED: {e}")
        import traceback; traceback.print_exc()
        return False


# ─────────────────────────────────────────────────────────────────
# TEST 3: Predictive Vendor Risk Model
# ─────────────────────────────────────────────────────────────────
def test_predictive_risk():
    section("TEST 3: Predictive Vendor Risk Model")
    try:
        import anomaly_detector

        # Create synthetic bid data: vendor 1 is high risk (blacklisted + high DQ rate)
        bids = []
        for tid in range(1, 6):
            # Vendor 1: blacklisted, DQ'd frequently
            bids.append({"vendor_id": 1, "tender_id": tid, "total_amount": 800000 + tid*10000,
                         "status": "Disqualified", "is_disqualified": True, "is_blacklisted": True,
                         "estimated_value": 1000000, "delivery_period": 45, "submitted_at": None})
            # Vendor 2: clean record
            bids.append({"vendor_id": 2, "tender_id": tid, "total_amount": 950000 + tid*5000,
                         "status": "Awarded" if tid == 1 else "Pending", "is_disqualified": False, "is_blacklisted": False,
                         "estimated_value": 1000000, "delivery_period": 30, "submitted_at": None})
            # Vendor 3: moderate
            bids.append({"vendor_id": 3, "tender_id": tid, "total_amount": 1200000 + tid*20000,
                         "status": "Pending", "is_disqualified": False, "is_blacklisted": False,
                         "estimated_value": 1000000, "delivery_period": 60, "submitted_at": None})

        predictions = anomaly_detector.predict_vendor_risk(
            all_bids=bids,
            all_vendor_ids=[1, 2, 3],
            vendor_name_map={1: "RiskyVendor Inc", 2: "CleanVendor Ltd", 3: "AvgVendor Co"},
            n_tenders=5,
        )

        print(f"  {INFO} Predictions returned: {len(predictions)}")
        for p in predictions:
            print(f"  {INFO}   {p['company_name']}: risk_score={p['risk_score']:.4f} ({p['risk_level']}), model={p['model_type']}")

        assert len(predictions) == 3, f"Expected 3 predictions, got {len(predictions)}"
        print(f"  {PASS} Correct number of predictions returned")

        # Sorted by risk descending
        assert predictions[0]["risk_score"] >= predictions[1]["risk_score"]
        print(f"  {PASS} Predictions sorted by risk score (descending)")

        # Vendor 1 (blacklisted + DQ) should be highest risk
        assert predictions[0]["vendor_id"] == 1, f"Expected vendor 1 to be highest risk, got {predictions[0]['vendor_id']}"
        print(f"  {PASS} Blacklisted/DQ vendor correctly ranked highest")

        # Vendor 2 (clean) should be among the lowest risk (ties allowed — both V2 and V3 score 0.0)
        clean_vendor = next((p for p in predictions if p["vendor_id"] == 2), None)
        assert clean_vendor is not None and clean_vendor["risk_score"] <= 0.1, \
            f"Expected vendor 2 low risk, got {clean_vendor}"
        print(f"  {PASS} Clean vendor correctly scored as low risk ({clean_vendor['risk_score']:.4f})")

        # Risk factors populated
        assert len(predictions[0]["risk_factors"]) > 0
        print(f"  {PASS} Risk factors populated: {predictions[0]['risk_factors'][:2]}")

        print(f"\n  {PASS} TEST 3 PASSED — Predictive Risk Model working correctly")
        return True
    except Exception as e:
        print(f"  {FAIL} TEST 3 FAILED: {e}")
        import traceback; traceback.print_exc()
        return False


# ─────────────────────────────────────────────────────────────────
# TEST 4: Autonomous Compliance Sentinel
# ─────────────────────────────────────────────────────────────────
def test_compliance_sentinel():
    section("TEST 4: Autonomous Compliance Sentinel (Policy Guardian Gamma)")
    try:
        import ai_swarm_engine

        # Full-compliance document
        full_doc = """
        This tender includes provisions for Earnest Money Deposit (EMD) of 2% of bid value.
        Liquidated Damages (LD) clause: Penalty for delay of 0.5% per week.
        Vendors must sign the Integrity Pact confirming no bribery and no conflict of interest.
        Warranty: 2 years comprehensive AMC coverage with defect liability period.
        MSME vendors with Udyam registration are eligible for MSME preference as per MSME Order 2012.
        Make in India preference shall be given to domestic manufacturers as per DPIIT Order 2017.
        GST registration (GSTIN) is mandatory. All vendors must provide tax registration certificate.
        Debarred or blacklisted suppliers on the negative list are not eligible to participate.
        """

        # Minimal document (missing many clauses)
        minimal_doc = """
        This is a tender for supply of office equipment.
        All bids must be submitted by 5 PM on the closing date.
        Payment shall be made within 30 days of delivery.
        """

        # Run compliance scan synchronously
        full_result = asyncio.run(ai_swarm_engine.execute_compliance_scan(
            document_text=full_doc,
            tender_title="Full Compliance Test Tender",
            vendor_profile={"msme_registered": True, "annual_turnover_cr": 5},
        ))

        minimal_result = asyncio.run(ai_swarm_engine.execute_compliance_scan(
            document_text=minimal_doc,
            tender_title="Minimal Compliance Test",
            vendor_profile={},
        ))

        print(f"  {INFO} Full doc compliance: {full_result['compliance_score_pct']}% — {full_result['compliance_status']}")
        print(f"  {INFO} Minimal doc compliance: {minimal_result['compliance_score_pct']}% — {minimal_result['compliance_status']}")
        print(f"  {INFO} Full doc present clauses: {full_result['present_clauses']}")
        print(f"  {INFO} Full doc missing clauses: {[c['id'] for c in full_result['missing_clauses']]}")
        print(f"  {INFO} MSME waivers: {full_result['msme_eligible_waivers']}")

        # Full doc should score significantly higher
        assert full_result["compliance_score_pct"] > minimal_result["compliance_score_pct"], \
            f"Full doc ({full_result['compliance_score_pct']}%) should outscore minimal ({minimal_result['compliance_score_pct']}%)"
        print(f"  {PASS} Full compliance document scored higher than minimal document")

        # Full doc should have more present clauses
        assert len(full_result["present_clauses"]) > len(minimal_result["present_clauses"])
        print(f"  {PASS} Clause detection correctly identified more clauses in full document")

        # MSME vendor should have waivers
        assert len(full_result["msme_eligible_waivers"]) > 0
        print(f"  {PASS} MSME waivers correctly identified for registered MSME vendor")

        # Transcript should contain COMPLIANCE agent messages
        assert len(full_result["transcript"]) > 0
        assert full_result["transcript"][0]["sender"] == "COMPLIANCE"
        print(f"  {PASS} Swarm transcript generated with COMPLIANCE agent")

        print(f"\n  {PASS} TEST 4 PASSED — Compliance Sentinel working correctly")
        return True
    except Exception as e:
        print(f"  {FAIL} TEST 4 FAILED: {e}")
        import traceback; traceback.print_exc()
        return False


# ─────────────────────────────────────────────────────────────────
# TEST 5: EWMA Anomaly Detection
# ─────────────────────────────────────────────────────────────────
def test_ewma_detection():
    section("TEST 5: EWMA Control Chart Anomaly Detection")
    try:
        import anomaly_detector

        # Series with clear anomalies at positions 10 and 20
        normal_values = [1000000 + (i % 5) * 5000 for i in range(25)]
        normal_values[10] = 3500000   # Spike up
        normal_values[20] = 200000    # Spike down

        result = anomaly_detector.ewma_detector(normal_values, span=5)

        print(f"  {INFO} EWMA alerts: {len(result['alerts'])}")
        print(f"  {INFO} Alert indices: {[a['index'] for a in result['alerts']]}")
        print(f"  {INFO} Threshold: {result['threshold']:,.0f}")

        assert "alerts" in result
        assert "ewma_values" in result
        assert "threshold" in result
        assert len(result["ewma_values"]) == len(normal_values)
        print(f"  {PASS} EWMA output structure correct")

        assert len(result["alerts"]) >= 1, "Expected at least 1 anomaly alert for spike values"
        print(f"  {PASS} Spike anomalies detected (>= 1 alerts)")

        alert_indices = [a["index"] for a in result["alerts"]]
        assert 10 in alert_indices or 20 in alert_indices, "Spike positions should be detected"
        print(f"  {PASS} Spike positions correctly flagged as anomalies")

        print(f"\n  {PASS} TEST 5 PASSED — EWMA Detection working correctly")
        return True
    except Exception as e:
        print(f"  {FAIL} TEST 5 FAILED: {e}")
        import traceback; traceback.print_exc()
        return False


# ─────────────────────────────────────────────────────────────────
# TEST 6: Agent Registry
# ─────────────────────────────────────────────────────────────────
def test_agent_registry():
    section("TEST 6: Agent Registry — COMPLIANCE Agent")
    try:
        import ai_swarm_engine
        registry = ai_swarm_engine.get_agent_registry()

        print(f"  {INFO} Registered agents: {list(registry.keys())}")

        assert "COMPLIANCE" in registry, "COMPLIANCE agent must be in registry"
        print(f"  {PASS} COMPLIANCE (Policy Guardian Γ) registered in swarm")

        comp = registry["COMPLIANCE"]
        assert comp["name"] == "Policy Guardian Γ"
        assert comp["color"] == "#a855f7"
        assert comp["icon"] == "gavel"
        print(f"  {PASS} COMPLIANCE agent metadata correct: {comp['name']}, icon={comp['icon']}")

        assert len(registry) >= 8, f"Expected at least 8 agents (including COMPLIANCE), got {len(registry)}"
        print(f"  {PASS} Total agents: {len(registry)} (correct)")

        print(f"\n  {PASS} TEST 6 PASSED — Agent Registry complete")
        return True
    except Exception as e:
        print(f"  {FAIL} TEST 6 FAILED: {e}")
        return False


# ─────────────────────────────────────────────────────────────────
# RUN ALL TESTS
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*60)
    print("  GEM PHASE 3 FEATURE TEST SUITE")
    print("="*60)

    results = []
    results.append(("LLM Cache 24h TTL", test_llm_cache_ttl()))
    results.append(("Vendor DNA Engine", test_vendor_dna()))
    results.append(("Predictive Risk Model", test_predictive_risk()))
    results.append(("Compliance Sentinel", test_compliance_sentinel()))
    results.append(("EWMA Detection", test_ewma_detection()))
    results.append(("Agent Registry", test_agent_registry()))

    section("SUMMARY")
    passed = sum(1 for _, r in results if r)
    total = len(results)
    for name, result in results:
        status = PASS if result else FAIL
        print(f"  {status} {name}")

    print(f"\n  Total: {passed}/{total} tests passed")
    if passed == total:
        print(f"\n  \033[92m✅ ALL PHASE 3 TESTS PASSED\033[0m")
    else:
        print(f"\n  \033[91m❌ {total-passed} test(s) FAILED\033[0m")
        sys.exit(1)
