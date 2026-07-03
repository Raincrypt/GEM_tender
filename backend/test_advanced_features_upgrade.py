# ==============================================================================
#  Verification Suite — Advanced Enterprise Upgrades (Zero Chinese Dependencies)
# ==============================================================================

import os
import sys
import json
import shutil
import unittest
import warnings
from unittest.mock import MagicMock

# Suppress warnings from third-party packages to keep output clean
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=ResourceWarning)
try:
    from langchain_core._api import LangChainDeprecationWarning
    warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)
except ImportError:
    pass

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import ai_swarm_engine
import blockchain
from routers.reports_core import cartel_network_analysis

class TestAdvancedUpgrades(unittest.TestCase):

    def setUp(self):
        # Save original env
        self.original_db_env = os.environ.get("RAG_VECTOR_DB")

    def tearDown(self):
        # Restore env
        if self.original_db_env:
            os.environ["RAG_VECTOR_DB"] = self.original_db_env
        else:
            os.environ.pop("RAG_VECTOR_DB", None)
            
        # Clean up temporary test databases
        for test_dir in ["./test_qdrant_db", "./test_rag_index", "./test_rag_meta"]:
            if os.path.exists(test_dir):
                shutil.rmtree(test_dir, ignore_errors=True)

    # ── 1. Test Conflict-of-Interest Swarm Agent ──────────────────────────────
    def test_conflict_of_interest_agent(self):
        print("\n[TEST] Verifying Conflict-of-Interest Swarm Agent...")
        
        # Mock LLM call to avoid Ollama server/model dependencies
        original_call = ai_swarm_engine._call_agent_llm
        ai_swarm_engine._call_agent_llm = MagicMock(return_value="Conflict of Interest detected between Alpha and Beta.")
        
        try:
            # Vendor profiles with a heavy link (shared address + shared director)
            bidders = [
                {
                    "vendor_name": "Alpha Infrastructure",
                    "ip": "192.168.1.10",
                    "email": "bids@alpha-infra.com",
                    "directors": ["Rahul Bajaj", "Sanjay Shah"],
                    "address": "100 Industrial Area, Sector 5, Bangalore",
                    "phone": "+91 80 4422 1100"
                },
                {
                    "vendor_name": "Beta Contracting",
                    "ip": "192.168.1.12", # shared subnet /24
                    "email": "tenders@alpha-infra.com", # Matching domain
                    "directors": ["Sanjay Shah", "Amit Patel"], # Shared Director
                    "address": "100 Industrial Area, Sector 5, Bangalore", # Shared Address
                    "phone": "+91 80 4422 1100" # Shared Phone
                },
                {
                    "vendor_name": "Gamma Solutions",
                    "ip": "10.0.5.4",
                    "email": "orders@gamma-sol.com",
                    "directors": ["Kiran Rao"],
                    "address": "45 Tech Park, Whitefield, Bangalore",
                    "phone": "+91 80 9999 8888"
                }
            ]
            
            # Execute scan
            import asyncio
            result = asyncio.run(ai_swarm_engine.execute_coi_scan(bidders))
            
            # Assertions
            self.assertEqual(result["overall_status"], "CRITICAL")
            self.assertEqual(result["conflict_count"], 1)
            self.assertEqual(result["overlaps"][0]["vendor_a"], "Alpha Infrastructure")
            self.assertEqual(result["overlaps"][0]["vendor_b"], "Beta Contracting")
            self.assertIn("Matching Registered Address", result["overlaps"][0]["links"])
            self.assertIn("Shared Directors (Sanjay Shah)", result["overlaps"][0]["links"])
            print("[OK] Conflict-of-Interest Swarm Agent verified successfully.")
        finally:
            ai_swarm_engine._call_agent_llm = original_call

    # ── 2. Test Louvain Community Detection ───────────────────────────────
    def test_louvain_communities_cartel_graph(self):
        print("\n[TEST] Verifying Louvain community detection in cartel report...")
        
        # Mock DB session
        db = MagicMock()
        
        # Mock Vendor records (8 vendors)
        class MockVendor:
            def __init__(self, id, name, blacklisted=False):
                self.id = id
                self.company_name = name
                self.gem_reg_no = f"GEM-{id:06d}"
                self.is_blacklisted = blacklisted
                self.performance_score = 90
        
        db.query().all.side_effect = [
            # Vendors query
            [
                MockVendor(1, "BHEL"), MockVendor(2, "L&T"), MockVendor(3, "SAIL"),
                MockVendor(4, "GAIL"), MockVendor(5, "Tata Projects"), MockVendor(6, "Metalwork A"),
                MockVendor(7, "Metalwork B"), MockVendor(8, "Sunrise Trading")
            ],
            # Bids query (all bid on same mock tenders to generate edges)
            [],
            # all_bids_db query
            [],
            # all_docs_db query
            []
        ]
        
        # Execute cartel graph analytics
        graph_data = cartel_network_analysis(db)
        
        # Verify community attributes added to nodes
        self.assertIn("nodes", graph_data)
        self.assertIn("edges", graph_data)
        
        for node in graph_data["nodes"]:
            self.assertIn("community_id", node["metadata"])
            self.assertIn("community_members", node["metadata"])
            self.assertTrue(len(node["metadata"]["community_members"]) > 0)
            
        print("[OK] Louvain clustering in Cartel Graph verified successfully.")

    # ── 3. Test ECDSA Asymmetric Cryptographic Signatures ────────────────
    def test_ecdsa_signatures(self):
        print("\n[TEST] Verifying ECDSA asymmetric contract signature verification...")
        
        # Generate keys
        private_pem, public_pem = blockchain.generate_contract_signing_keys()
        self.assertTrue(private_pem.startswith("-----BEGIN PRIVATE KEY-----"))
        self.assertTrue(public_pem.startswith("-----BEGIN PUBLIC KEY-----"))
        
        contract = {
            "tender_id": 4512,
            "awardee": "L&T India",
            "amount": 25000000.0,
            "timestamp": "2026-05-31T12:00:00"
        }
        
        # Sign
        sig = blockchain.sign_contract(private_pem, contract)
        self.assertTrue(len(sig) > 40) # Ensure hex signature produced
        
        # Verify valid signature
        is_valid = blockchain.verify_contract_signature(public_pem, contract, sig)
        self.assertTrue(is_valid)
        
        # Verify tampered contract fails
        tampered_contract = dict(contract)
        tampered_contract["amount"] = 26000000.0 # Altered amount
        is_valid_tampered = blockchain.verify_contract_signature(public_pem, tampered_contract, sig)
        self.assertFalse(is_valid_tampered)
        
        print("[OK] ECDSA signatures generated and verified successfully.")

    # ── 4. Test Qdrant Vector DB Integration ──────────────────────────────
    def test_qdrant_vector_db(self):
        print("\n[TEST] Verifying Qdrant local database indexing & retrieval...")
        
        # Configure env
        os.environ["RAG_VECTOR_DB"] = "qdrant"
        
        import rag_engine
        
        # Reload RAG configs to match test paths
        rag_engine.qdrant_client = None
        rag_engine.RAG_VECTOR_DB = "qdrant"
        rag_engine.QDRANT_URL = ":memory:"
        rag_engine.DEFAULT_INDEX_DIR = "./test_rag_meta"
        os.makedirs("./test_rag_meta", exist_ok=True)
        
        # Re-initialize
        rag_engine.init_rag()
        
        # Sample document
        doc_text = "Standard Operating Procedure for Gas Turbines in IOCL Refinery Projects."
        meta = {"doc_type": "sop", "tender_id": 105, "vendor_id": 4}
        
        # Ingest
        success = rag_engine.add_document_to_index(doc_text, meta)
        self.assertTrue(success)
        
        # Search & verify
        chunks = rag_engine.retrieve_relevant_chunks("Turbines in IOCL", filter_metadata={"tender_id": 105})
        self.assertTrue(len(chunks) > 0)
        self.assertIn("Turbines", chunks[0].page_content)
        self.assertEqual(str(chunks[0].metadata.get("tender_id")), "105")
        
        print("[OK] Qdrant RAG ingestion and retrieval verified successfully.")

    # ── 5. Test PQC Rules Extract ──────────────────────────────────────────────
    def test_pqc_rules_extract(self):
        print("\n[TEST] Verifying LLM structured rule extraction...")
        import llm_client
        from routers.reports_pqc import pqc_rules_extract
        
        # Mock LLM extraction
        mock_extracted = {
            "tender_ref_no": "TEST-1234",
            "relaxation_applicable": True,
            "turnover_lakhs": 50.0,
            "exp_3_orders_lakhs": 10.0,
            "exp_2_orders_lakhs": 20.0,
            "exp_1_order_lakhs": 30.0,
            "annexure_a": {"size_inch": 130, "pixel_pitch_mm": 1.5, "resolution": "1920 x 1080", "contrast_ratio_min": 5000, "brightness_peak_nit": 1000, "warranty_years": 3},
            "annexure_b": {"size_inch": 85, "resolution": "3840 x 2160"}
        }
        
        original_extract = llm_client.extract_structured
        llm_client.extract_structured = MagicMock(return_value=mock_extracted)
        
        try:
            result = pqc_rules_extract()
            self.assertEqual(result["tender_ref_no"], "TEST-1234")
            self.assertEqual(result["turnover_lakhs"], 50.0)
            self.assertEqual(result["annexure_a"]["size_inch"], 130)
            print("[OK] LLM structured rule extraction verified successfully.")
        finally:
            llm_client.extract_structured = original_extract

    # ── 6. Test Explain Clause ─────────────────────────────────────────────────
    def test_explain_clause(self):
        print("\n[TEST] Verifying AI clause explanation & citation...")
        import llm_client
        from routers.reports_pqc import explain_clause
        
        # Mock LLM generation
        mock_explain = {
            "explanation": "This requires Android TV or other OS.",
            "citations": "GFR 2017 Rule 144",
            "risk_score": 10,
            "risk_verdict": "Clearance: Standard operating system clause."
        }
        
        original_json = llm_client.generate_json
        llm_client.generate_json = MagicMock(return_value=mock_explain)
        
        try:
            body = {"clause_text": "OS Android TV/webOS/Tizen", "context": "Tender LED Wall"}
            result = explain_clause(body)
            self.assertEqual(result["explanation"], "This requires Android TV or other OS.")
            self.assertEqual(result["risk_score"], 10)
            self.assertIn("GFR 2017", result["citations"])
            print("[OK] AI clause explanation & citation verified successfully.")
        finally:
            llm_client.generate_json = original_json

if __name__ == '__main__':
    unittest.main()
