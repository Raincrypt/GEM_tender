import os
import sys
import unittest
import asyncio
from unittest.mock import MagicMock

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import llm_client
import ai_swarm_engine
from routers.reports_pqc import explain_clause, generate_gap_analysis

class TestVerbatimCitationGuard(unittest.TestCase):

    def test_vcg_verbatim_matching(self):
        print("\n[TEST] Verifying VCG Verbatim Matching...")
        context = "The bidder must possess a minimum of 5 years experience in supplying LED Video Walls."
        
        # 1. Exact Match
        res1 = llm_client.verify_citations("Answer", "5 years experience", context)
        self.assertTrue(res1["is_verified"])
        self.assertEqual(res1["status"], "VERIFIED")
        
        # 2. Normalized Match (different case and punctuation)
        res2 = llm_client.verify_citations("Answer", "5 Years Experience!", context)
        self.assertTrue(res2["is_verified"])
        
        # 3. Non-Match (hallucination)
        res3 = llm_client.verify_citations("Answer", "10 years experience", context)
        self.assertFalse(res3["is_verified"])
        self.assertEqual(res3["status"], "HALLUCINATION_DETECTED")
        print("[OK] VCG verbatim matching verified.")

    def test_vcg_policy_reference(self):
        print("\n[TEST] Verifying VCG Policy Reference Validation...")
        # 1. Standard valid policy citation
        res1 = llm_client.verify_citations("Answer", "GFR 2017 Rule 173", "Context has nothing")
        self.assertTrue(res1["is_verified"])
        
        # 2. Standard valid CVC citation
        res2 = llm_client.verify_citations("Answer", "CVC Circular 2023/01", "Context has nothing")
        self.assertTrue(res2["is_verified"])
        
        # 3. Arbitrary non-standard string citation
        res3 = llm_client.verify_citations("Answer", "Arbitrary guideline statement", "Context has nothing")
        self.assertFalse(res3["is_verified"])
        print("[OK] VCG policy reference validation verified.")

    def test_score_with_evidence_vcg(self):
        print("\n[TEST] Verifying score_with_evidence VCG Check...")
        
        # Mock generate_json to return a valid evidence quote
        original_generate_json = llm_client.generate_json
        llm_client.generate_json = MagicMock(return_value={
            "score": 10,
            "rationale": "Vendor has required experience",
            "evidence_quote": "5 years experience",
            "confidence": 90,
            "needs_human_review": False
        })
        
        try:
            chunks = ["Vendor has 5 years experience in supply."]
            result = llm_client.score_with_evidence("Experience", 10, chunks)
            self.assertTrue(result["citation_verified"])
            self.assertEqual(result["evidence_quote"], "5 years experience")
            self.assertEqual(result["confidence"], 90)
            
            # Now mock to return a hallucinated quote
            llm_client.generate_json = MagicMock(return_value={
                "score": 10,
                "rationale": "Vendor has required experience",
                "evidence_quote": "12 years experience",
                "confidence": 90,
                "needs_human_review": False
            })
            
            result_hallucinated = llm_client.score_with_evidence("Experience", 10, chunks)
            # The VCG check should fail, and confidence should be clamped/review flagged
            self.assertFalse(result_hallucinated["citation_verified"])
            self.assertTrue(result_hallucinated["needs_human_review"])
            self.assertLessEqual(result_hallucinated["confidence"], 40)
            print("[OK] score_with_evidence VCG verified.")
        finally:
            llm_client.generate_json = original_generate_json

    def test_explain_clause_vcg(self):
        print("\n[TEST] Verifying explain_clause VCG integration...")
        original_generate_json = llm_client.generate_json
        llm_client.generate_json = MagicMock(return_value={
            "explanation": "EMD is required",
            "citations": "GFR 2017 Rule 170",
            "risk_score": 10,
            "risk_verdict": "Clearance"
        })
        
        try:
            body = {"clause_text": "EMD", "context": "Tender details"}
            result = explain_clause(body)
            self.assertTrue(result["citation_verified"])
            self.assertIn("citation_details", result)
            print("[OK] explain_clause VCG verified.")
        finally:
            llm_client.generate_json = original_generate_json

    def test_swarm_critic_grounding(self):
        print("\n[TEST] Verifying Swarm Critic grounding verification...")
        
        # Mock LLM call for swarm agents
        original_call = ai_swarm_engine._call_agent_llm
        
        # Mock different responses for different agents
        def mock_agent_llm(sender, system_prompt, user_prompt, default_text):
            if sender == "NEGOTIATOR":
                return "Counter offer is ₹80,000 based on standard discount."
            elif sender == "AUDITOR":
                return "Complies with GEM Policy Rule 12.1 and GFR 2017."
            elif sender == "CRITIC":
                return "Critic Ξ verified all claims against context."
            return default_text
            
        ai_swarm_engine._call_agent_llm = mock_agent_llm
        
        try:
            context = {
                "vendor_name": "Test Vendor",
                "l1_amount": 100000,
                "estimated_value": 110000,
                "document_text": "Tender specs enforce GEM Policy Rule 12.1 compliance.",
                "tender_id": 999
            }
            
            # Execute Swarm
            res = asyncio.run(ai_swarm_engine.execute_negotiation_swarm(context))
            transcript = res["transcript"]
            
            # Verify execution order: CRITIC should run after NEGOTIATOR and AUDITOR
            critic_idx = -1
            neg_idx = -1
            aud_idx = -1
            
            for i, msg in enumerate(transcript):
                if msg["sender"] == "CRITIC":
                    critic_idx = i
                elif msg["sender"] == "NEGOTIATOR":
                    neg_idx = i
                elif msg["sender"] == "AUDITOR":
                    aud_idx = i
                    
            self.assertTrue(critic_idx > neg_idx, "Critic must run after Negotiator")
            self.assertTrue(critic_idx > aud_idx, "Critic must run after Auditor")
            
            # Extract critic metadata and check that VCG citation_verified is verified 
            # (since GEM Policy Rule 12.1 exists in document_text and GFR 2017 is a valid policy reference)
            critic_msg = next(m for m in transcript if m["sender"] == "CRITIC")
            self.assertTrue(critic_msg["metadata"]["citation_verified"])
            print("[OK] Swarm Critic grounding and execution order verified.")
        finally:
            ai_swarm_engine._call_agent_llm = original_call

    def test_pqc_rules_llm_extraction_vcg(self):
        print("\n[TEST] Verifying PQC Rules LLM Extraction VCG & Fallbacks...")
        from routers.reports_pqc import extract_rules_with_citations
        
        # Mock structured LLM extraction
        mock_extracted = {
            "tender_ref_no": "RHM25R8080",
            "tender_ref_no_citation": "Tender Reference No. RHM25R8080",
            "relaxation_applicable": True,
            "relaxation_applicable_citation": "Relaxation of Norms for Startups and Micro & Small Enterprises",
            "turnover_lakhs": 50.0,
            "turnover_lakhs_citation": "turnover at least INR 50.0 Lakhs",
            "exp_3_orders_lakhs": 10.0,
            "exp_3_orders_lakhs_citation": "Three orders each INR 10.0 Lakhs",
            "exp_2_orders_lakhs": 20.0,
            "exp_2_orders_lakhs_citation": "Two orders each INR 20.0 Lakhs",
            "exp_1_order_lakhs": 30.0,
            "exp_1_order_lakhs_citation": "One order executed for INR 30.0 Lakhs",
            "annexure_a": {
                "size_inch": 130,
                "size_inch_citation": "Size Diagonal (Max) 130 Inch",
                "pixel_pitch_mm": 1.5,
                "pixel_pitch_mm_citation": "Pixel Pitch 1.5 mm",
                "resolution": "1920 x 1080",
                "resolution_citation": "Resolution (LxH) 1920 x 1080",
                "contrast_ratio_min": 5000,
                "contrast_ratio_min_citation": "Contrast Ratio 5000",
                "brightness_peak_nit": 1000,
                "brightness_peak_nit_citation": "Brightness(Peak/Max) 1000 nit",
                "refresh_rate_hz": 3840,
                "refresh_rate_hz_citation": "Refresh Rate 3840 Hz",
                "os_options": ["Android TV", "webOS", "Tizen"],
                "os_options_citation": "OS Android TV/webOS/Tizen",
                "warranty_years": 3,
                "warranty_years_citation": "Warranty 3 years Onsite"
            },
            "annexure_b": {
                "size_inch": 85,
                "size_inch_citation": "Size (Inch) 85",
                "resolution": "3840 x 2160",
                "resolution_citation": "Resolution 3840 x 2160",
                "brightness_nit": 250,
                "brightness_nit_citation": "Brightness (Typ.) 250 nit",
                "contrast_ratio_min": 4700,
                "contrast_ratio_min_citation": "Contrast Ratio (Typ.) 4700",
                "os_options": ["Android TV", "webOS", "Tizen"],
                "os_options_citation": "Operating System Android TV/webOS/Tizen",
                "warranty_years": 3,
                "warranty_years_citation": "Warranty 3 Years Onsite"
            }
        }
        
        original_extract = llm_client.extract_structured
        llm_client.extract_structured = MagicMock(return_value=mock_extracted)
        
        sample_doc_content = (
            "Tender Reference No. RHM25R8080\n"
            "Three orders each INR 10.0 Lakhs\n"
            "Two orders each INR 20.0 Lakhs\n"
            "One order executed for INR 30.0 Lakhs\n"
            "turnover at least INR 50.0 Lakhs\n"
            "Relaxation of Norms for Startups and Micro & Small Enterprises\n"
            "ANNEXURE-A\n"
            "Size Diagonal (Max) 130 Inch\n"
            "Pixel Pitch 1.5 mm\n"
            "Resolution (LxH) 1920 x 1080\n"
            "Contrast Ratio 5000\n"
            "Brightness(Peak/Max) 1000 nit\n"
            "Refresh Rate 3840 Hz\n"
            "OS Android TV/webOS/Tizen\n"
            "Warranty 3 years Onsite\n"
            "ANNEXURE-B\n"
            "Size (Inch) 85\n"
            "Resolution 3840 x 2160\n"
            "Brightness (Typ.) 250 nit\n"
            "Contrast Ratio (Typ.) 4700\n"
            "Operating System Android TV/webOS/Tizen\n"
            "Warranty 3 Years Onsite\n"
        )
        
        try:
            res = extract_rules_with_citations(sample_doc_content)
            # Verify all fields are verified: True
            self.assertTrue(res["citations_metadata"]["tender_ref_no"]["verified"])
            self.assertTrue(res["citations_metadata"]["turnover_lakhs"]["verified"])
            self.assertTrue(res["citations_metadata"]["exp_3_orders_lakhs"]["verified"])
            self.assertTrue(res["citations_metadata"]["annexure_a.size_inch"]["verified"])
            self.assertTrue(res["citations_metadata"]["annexure_b.brightness_nit"]["verified"])
            
            self.assertEqual(res["tender_ref_no"], "RHM25R8080")
            self.assertEqual(res["turnover_lakhs"], 50.0)
            self.assertEqual(res["annexure_a"]["size_inch"], 130)
            self.assertEqual(res["annexure_b"]["brightness_nit"], 250)
            
            # Now simulate a failed citation (hallucination)
            mock_extracted_hallucinated = dict(mock_extracted)
            mock_extracted_hallucinated["turnover_lakhs"] = 999.0
            mock_extracted_hallucinated["turnover_lakhs_citation"] = "turnover at least INR 999.0 Lakhs"  # Not in doc!
            
            llm_client.extract_structured = MagicMock(return_value=mock_extracted_hallucinated)
            
            res_hallucinated = extract_rules_with_citations(sample_doc_content)
            # turnover_lakhs should have verified: False
            self.assertFalse(res_hallucinated["citations_metadata"]["turnover_lakhs"]["verified"])
            # It should have fallen back to the regex-parsed value of 50.0!
            self.assertEqual(res_hallucinated["turnover_lakhs"], 50.0)
            print("[OK] PQC Rules LLM Extraction VCG & Fallbacks verified.")
        finally:
            llm_client.extract_structured = original_extract

    def test_auto_reanalysis_cache_invalidation(self):
        print("\n[TEST] Verifying auto-reanalysis cache invalidation...")
        import routers.reports_pqc as reports_pqc
        from unittest.mock import patch, MagicMock

        # Mock MongoDB find_one and update_one
        mock_mongo = MagicMock()
        mock_cache_coll = MagicMock()
        mock_mongo.__getitem__.return_value = mock_cache_coll

        # Mock filesystem state so it's stable
        mock_exists = MagicMock(return_value=True)
        mock_mtime = MagicMock(side_effect=lambda path: 1000.0 if "ocr_cache.json" in path else 2000.0)
        mock_getsize = MagicMock(return_value=50000)
        mock_listdir = MagicMock(side_effect=lambda path: ["file1.pdf"] if "CYBER INFOSYS" in path else ["CYBER INFOSYS"])
        mock_isdir = MagicMock(side_effect=lambda path: True if "CYBER INFOSYS" in path else False)
        mock_isfile = MagicMock(side_effect=lambda path: True if "file1.pdf" in path or "ocr_cache.json" in path else False)

        with patch('database.mongo_db', mock_mongo), \
             patch('os.path.exists', mock_exists), \
             patch('os.path.getmtime', mock_mtime), \
             patch('os.path.getsize', mock_getsize), \
             patch('os.listdir', mock_listdir), \
             patch('os.path.isdir', mock_isdir), \
             patch('os.path.isfile', mock_isfile), \
             patch('routers.reports_pqc.generate_reasoning', return_value=[]), \
             patch('routers.reports_pqc.compute_risk_profile', return_value={"overall": 90, "compliance": 90, "forensic": 90, "financial": 90, "technical": 90, "collusion_safe": 90, "risk_level": "LOW", "anomaly_count": 0, "avg_auth_score": 90, "rule_score": 90, "max_rule_score": 100}), \
             patch('routers.reports_pqc.generate_gap_analysis', return_value=[]), \
             patch('routers.reports_pqc.load_tender_thresholds', return_value={}):

            # 1. First run, cache has matching state. It should return cached data without generating.
            cached_state = {
                "ocr_cache_mtime": 1000.0,
                "files": {
                    "CYBER INFOSYS/file1.pdf": {"size": 50000, "mtime": 2000.0}
                }
            }
            mock_cache_doc = {
                "cache_id": "latest_matrix",
                "documents_state": cached_state,
                "data": {"mocked_cache": True}
            }
            mock_cache_coll.find_one.return_value = mock_cache_doc

            res1 = reports_pqc.get_pqc_comparison_data(refresh=False)
            self.assertEqual(res1, {"mocked_cache": True})
            # Verify update_one was NOT called since cache hit
            mock_cache_coll.update_one.assert_not_called()

            # 2. Second run, cache has different state (mtime changed).
            # Change the filesystem mtime
            mock_mtime.side_effect = lambda path: 1000.0 if "ocr_cache.json" in path else 2005.0 # file1.pdf is newer!
            
            mock_cache_coll.update_one.reset_mock()
            mock_cache_coll.find_one.return_value = mock_cache_doc # state in database is still old

            res2 = reports_pqc.get_pqc_comparison_data(refresh=False)
            # It should have updated the cache because state mismatched
            self.assertNotEqual(res2, {"mocked_cache": True})
            mock_cache_coll.update_one.assert_called()
            print("[OK] Cache invalidation on file modification verified.")

    def test_dynamic_compare_and_evaluation(self):
        print("\n[TEST] Verifying dynamic compare and single-bid auto-evaluation...")
        from unittest.mock import patch, MagicMock
        from routers.documents import compare_documents
        import models

        # Mock database session
        mock_db = MagicMock()
        mock_tender = MagicMock(id=1)
        mock_bid = MagicMock(id=10, tender_id=1)
        mock_doc = MagicMock(id=100, bid_id=10, file_path="uploads/test_doc.pdf", document_type="MAF")
        
        # Set uploaded_at and file mtime so that file is newer
        from datetime import datetime, timedelta
        mock_doc.uploaded_at = datetime.utcnow() - timedelta(hours=1)
        
        mock_db.query.return_value.filter.return_value.all.side_effect = [
            [mock_bid], # db_bids
            [mock_doc], # db_docs
            [mock_doc], # all_docs for parent bid composite score
        ]
        mock_db.query.return_value.filter.return_value.first.return_value = mock_bid

        # Mock other dependencies
        mock_exists = MagicMock(return_value=True)
        # Mock file mtime to be current (newer than uploaded_at)
        mock_mtime = MagicMock(return_value=datetime.timestamp(datetime.utcnow()))

        # Mock auto_evaluate_single_bid
        mock_auto_eval = MagicMock()
        
        # Mock websocket manager and event loop
        import asyncio
        mock_manager = MagicMock()
        mock_loop = MagicMock()
        mock_new_event_loop = MagicMock(return_value=mock_loop)

        with patch('os.path.exists', mock_exists), \
             patch('os.path.getmtime', mock_mtime), \
             patch('routers.documents.extract_text_from_file', return_value="Fresh MAF content"), \
             patch('routers.documents.redact_pii', return_value="Fresh MAF content redacted"), \
             patch('ai_risk_engine.extract_esg_metrics', return_value={"esg_score": 85.0, "highlights": []}), \
             patch('ai_risk_engine.analyze_risk', return_value={"risk_score": 10.0, "summary": "Low risk"}), \
             patch('routers.evaluation.auto_evaluate_single_bid', mock_auto_eval), \
             patch('main.manager', mock_manager), \
             patch('asyncio.new_event_loop', mock_new_event_loop):

            # Call compare_documents
            res = compare_documents(tender_id=1, db=mock_db, current_user=MagicMock(id=1, role="Admin"))
            
            # Assertions
            # 1. OCR text updated in DB document
            self.assertEqual(mock_doc.ocr_extracted_text, "Fresh MAF content redacted")
            # 2. Database committed
            mock_db.commit.assert_called()
            # 3. auto_evaluate_single_bid was called
            mock_auto_eval.assert_called_with(10, mock_db, 1)
            # 4. WebSocket broadcast was triggered
            mock_manager.broadcast.assert_called()
            
            print("[OK] Dynamic compare and single-bid auto-evaluation verified.")

    def test_find_evidence_source_quoted_extraction(self):
        print("\n[TEST] Verifying find_evidence_source Quoted Extraction...")
        from routers.reports_pqc import find_evidence_source
        
        files = [{
            "name": "audit_report.pdf",
            "ocr_text": "--- Page 1 ---\nFirst Line\nSecond Line\nAverage Annual Turnover is INR 45 Lakhs\n--- Page 2 ---\nNet Worth is Positive\n"
        }]
        
        # Test case 1: Evidence text with quote inside single quotes
        evidence_1 = "Shortfall: Found in financials: 'Average Annual Turnover is INR 45 Lakhs' (which does not satisfy requirement)"
        res1 = find_evidence_source(evidence_1, files)
        self.assertIsNotNone(res1)
        self.assertEqual(res1["file_name"], "audit_report.pdf")
        self.assertEqual(res1["page_number"], 1)
        self.assertEqual(res1["line_number"], 3)
        self.assertEqual(res1["matched_text"], "Average Annual Turnover is INR 45 Lakhs")
        
        # Test case 2: Evidence text with prefix "Non-compliant EMD:"
        evidence_2 = "Non-compliant EMD: 'Earnest Money Deposit of 2.5 Lakhs' (fails requirement)"
        files_emd = [{
            "name": "emd_receipt.pdf",
            "ocr_text": "--- Page 1 ---\nDeclaration\nEarnest Money Deposit of 2.5 Lakhs paid\n"
        }]
        res2 = find_evidence_source(evidence_2, files_emd)
        self.assertIsNotNone(res2)
        self.assertEqual(res2["file_name"], "emd_receipt.pdf")
        self.assertEqual(res2["page_number"], 1)
        self.assertEqual(res2["line_number"], 2)
        print("[OK] find_evidence_source quoted extraction verified.")

if __name__ == '__main__':
    unittest.main()
