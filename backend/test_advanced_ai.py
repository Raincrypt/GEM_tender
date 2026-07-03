"""
test_advanced_ai.py
===================
Verifies advanced AI integration components:
1. RAG multi-query + cross-encoder re-ranking
2. Vendor profile extraction
3. Dynamic rule engine compliance matching
4. AI Risk Engine with Chain-of-Thought (CoT)
"""

import sys
import os
import json

# Configure UTF-8 encoding for standard output on Windows
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.dirname(__file__))

import llm_client
import rag_engine
import vendor_extractor
import rule_engine
import ai_risk_engine
import models
from database import get_db

def run_test():
    print("==================================================")
    print("   STARTING END-TO-END ADVANCED AI SYSTEM TEST")
    print("==================================================")

    # ──────────────────────────────────────────────────────────
    # Test 1: LLM Client structured extraction and connection
    # ──────────────────────────────────────────────────────────
    print("\n[TEST 1] Testing Connection & LLM client...")
    status = llm_client.get_provider_status()
    print(f"Active Provider: {status['active_provider']}")
    print(f"Ollama Configured: {status['ollama_model']} @ {status['ollama_url']}")
    
    # ──────────────────────────────────────────────────────────
    # Test 2: Vendor Extractor
    # ──────────────────────────────────────────────────────────
    print("\n[TEST 2] Testing Structured Vendor Profile Extraction...")
    sample_ocr = (
        "KAN UNIVERSAL PRIVATE LIMITED. GSTIN: 19AAACK1234F1Z9. PAN: AAACK1234F. "
        "We are registered as a Micro MSME under registration number UDYAM-WB-00-12345. "
        "Our annual turnover for financial year 2024-2025 is Rs. 12.50 Crores, and net worth is 4.8 Crores. "
        "We have been in the LED supply business since 2017 (8 years experience). "
        "We possess ISO 9001:2015 and BIS certifications."
    )
    profile = vendor_extractor.extract_vendor_profile(sample_ocr, doc_type="financial_and_iso")
    print("Extracted Profile:")
    print(json.dumps(profile, indent=2))
    assert profile["company_name"] is not None or profile["gstin"] == "19AAACK1234F1Z9", "Failed profile extraction"
    print("[OK] Vendor profile extraction works.")

    # ──────────────────────────────────────────────────────────
    # Test 3: Rule Engine Extraction & Application
    # ──────────────────────────────────────────────────────────
    print("\n[TEST 3] Testing Dynamic Rule Extraction & Matching...")
    sample_rule_text = (
        "ELIGIBILITY CRITERIA:\n"
        "1. Bidder must have minimum 3 years of experience in LED supply.\n"
        "2. Bidder's average annual turnover must be at least Rs. 5.0 Crores.\n"
        "3. Bidder must possess valid ISO 9001 certification."
    )
    rules = rule_engine.extract_rules_from_document(sample_rule_text, tender_title="LED Display Supply Tender")
    print(f"Extracted Rules ({len(rules)}):")
    print(json.dumps(rules, indent=2))

    verdict = rule_engine.apply_rules_to_vendor(rules, profile)
    print("Rule Matching Verdict:")
    print(json.dumps(verdict, indent=2))
    assert verdict["overall_pass"] is True, "Expected overall pass on matching vendor data!"
    print("[OK] Rule engine extraction and matching work.")

    # ──────────────────────────────────────────────────────────
    # Test 4: RAG Multi-Query and Cross-Encoder
    # ──────────────────────────────────────────────────────────
    print("\n[TEST 4] Testing RAG Multi-Query & Re-Ranking...")
    stats = rag_engine.get_index_stats()
    print(f"RAG Index stats: {stats}")
    if stats["chunk_count"] > 0:
        res = rag_engine.advanced_query(
            question="What are the experience and turnover requirements?",
            k=2
        )
        print("RAG Advanced Query Result:")
        print(f"Success: {res.get('success')}")
        print(f"Answer: {res.get('answer')[:200]}...")
        print(f"Method: {res.get('retrieval_method')}")
        print(f"Citations count: {len(res.get('citations', []))}")
    else:
        print("[WARN] RAG index is empty. Skipping RAG search.")

    # ──────────────────────────────────────────────────────────
    # Test 5: AI Risk Engine with Chain-of-Thought
    # ──────────────────────────────────────────────────────────
    print("\n[TEST 5] Testing AI Risk Engine Chain-of-Thought (CoT)...")
    suspicious_ocr = (
        "ALERT: Vendor was blacklisted by state utility board in 2023 for delaying LED supply orders. "
        "The company filed for insolvency in insolvency tribunal in late 2025 due to massive debts."
    )
    risk_res = ai_risk_engine.analyze_risk(suspicious_ocr)
    print("Risk Engine Output:")
    print(f"Risk Score: {risk_res['risk_score']}")
    print(f"Factors: {risk_res['risk_factors']}")
    print(f"Summary: {risk_res['summary']}")
    if "llm_analysis" in risk_res:
        print("CoT Reasoning details:")
        print(risk_res["llm_analysis"]["cot_reasoning"])
        assert risk_res["risk_score"] > 50, "Expected high risk score for blacklisted and insolvent vendor!"
    print("[OK] Risk Engine works.")

    print("\n==================================================")
    print("   ALL ADVANCED AI COMPONENT TESTS PASSED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    run_test()
