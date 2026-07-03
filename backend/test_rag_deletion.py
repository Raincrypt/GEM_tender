import unittest
import os
import sys
import shutil

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import rag_engine

class TestRagDeletion(unittest.TestCase):

    def setUp(self):
        # Initialize RAG index in memory or a test path
        self.original_db_env = os.environ.get("RAG_VECTOR_DB")
        self.original_index_dir = rag_engine.DEFAULT_INDEX_DIR
        rag_engine.DEFAULT_INDEX_DIR = "./test_deletion_rag_index"
        
        if os.path.exists("./test_deletion_rag_index"):
            shutil.rmtree("./test_deletion_rag_index", ignore_errors=True)
            
        # Re-initialize FAISS in-memory or empty local
        rag_engine.vector_store = None
        rag_engine._doc_hashes = set()
        rag_engine._chunk_count = 0
        rag_engine.init_rag()

    def tearDown(self):
        # Restore environment and clean up
        if self.original_db_env:
            os.environ["RAG_VECTOR_DB"] = self.original_db_env
        else:
            os.environ.pop("RAG_VECTOR_DB", None)
            
        rag_engine.DEFAULT_INDEX_DIR = self.original_index_dir
        if os.path.exists("./test_deletion_rag_index"):
            shutil.rmtree("./test_deletion_rag_index", ignore_errors=True)

    def test_faiss_deletion_flow(self):
        print("\n[TEST] Verifying FAISS document indexing and deletion...")
        
        # Ingest document
        doc_text = "This is a unique test dossier detailing specialized specifications for LED wall display procurement in Chennai."
        metadata = {"vendor_id": 99, "tender_id": 123, "doc_type": "technical_spec", "filename": "led_specs_v1.pdf"}
        
        success = rag_engine.add_document_to_index(doc_text, metadata)
        self.assertTrue(success)
        self.assertEqual(rag_engine._chunk_count, 1)
        
        # Query RAG: should find the text
        chunks = rag_engine.retrieve_relevant_chunks("LED wall display Chennai", filter_metadata={"vendor_id": 99})
        self.assertTrue(len(chunks) > 0)
        self.assertIn("specifications for LED", chunks[0].page_content)
        
        # Now delete the document
        deleted = rag_engine.delete_document_from_index(
            filter_metadata={
                "vendor_id": 99,
                "tender_id": 123,
                "doc_type": "technical_spec"
            }
        )
        self.assertTrue(deleted)
        self.assertEqual(rag_engine._chunk_count, 0)
        
        # Query again: should NOT find the text (filtered out or empty index)
        chunks_after = rag_engine.retrieve_relevant_chunks("LED wall display Chennai", filter_metadata={"vendor_id": 99})
        self.assertEqual(len(chunks_after), 0)
        print("[OK] FAISS indexing and deletion verified successfully.")

if __name__ == '__main__':
    unittest.main()
