import os
import sys
import time
from datetime import datetime

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import database
import models
import rag_engine
import ai_risk_engine

# Mock slow LLM calls for testing
ai_risk_engine.analyze_risk = lambda text: {"risk_score": 10.0, "summary": "mocked", "risk_factors": []}
ai_risk_engine.extract_esg_metrics = lambda text: {"esg_score": 80.0, "highlights": []}
ai_risk_engine.generate_ai_score_suggestion = lambda name, max_score, docs: {"score": max_score, "rationale": "mocked"}

from routers.documents import compare_documents

def main():
    print("=== STARTING OJAS AUTOMATIC SYNC TEST ===")
    db = database.SessionLocal()
    
    # 1. Get OJAS vendor and bid documents
    v = db.query(models.Vendor).filter(models.Vendor.company_name.ilike('%OJAS%')).first()
    if not v:
        print("Error: OJAS vendor not found.")
        return
        
    print(f"Found Vendor: ID={v.id}, Name={v.company_name}")
    
    b = db.query(models.Bid).filter(models.Bid.vendor_id == v.id, models.Bid.tender_id == 1).first()
    if not b:
        print("Error: OJAS bid for Tender 1 not found.")
        return
        
    docs = db.query(models.BidDocument).filter(models.BidDocument.bid_id == b.id).all()
    if not docs:
        print("Error: OJAS has no documents in the database.")
        return
        
    target_doc = docs[0]
    print(f"Target Document: ID={target_doc.id}, Type={target_doc.document_type}, Path={target_doc.file_path}")
    
    # Ensure RAG is initialized
    rag_engine.init_rag()
    
    # Check current chunks in RAG for this vendor
    initial_chunks = rag_engine.retrieve_relevant_chunks(
        "OJAS", 
        filter_metadata={"vendor_id": v.id},
        k=50
    )
    print(f"Initial RAG chunks for OJAS: {len(initial_chunks)}")
    
    # Adjust path if running inside backend folder
    actual_path = target_doc.file_path
    if actual_path.startswith("backend/") and os.path.basename(os.getcwd()) == "backend":
        actual_path = actual_path[8:]
        
    if not os.path.exists(actual_path):
        print(f"Error: File not found at {actual_path}")
        return
        
    target_doc.file_path = actual_path
            
    # Set the DB uploaded_at to be in the past so the file is seen as "newer"
    # Set DB time to 1 hour ago
    from datetime import timedelta
    target_doc.uploaded_at = datetime.utcnow() - timedelta(hours=1)
    db.add(target_doc)
    
    # Set other documents' uploaded_at to the future so they are not triggered
    other_docs = db.query(models.BidDocument).filter(models.BidDocument.id != target_doc.id).all()
    for od in other_docs:
        od.uploaded_at = datetime.utcnow() + timedelta(days=1)
        db.add(od)
        
    db.commit()
    
    # Touch the file on disk to update mtime to now
    os.utime(target_doc.file_path, None)
    print(f"Touched file on disk: {target_doc.file_path} (mtime updated)")
    
    # 3. Trigger the automatic sync by calling compare_documents logic
    print("Triggering compare_documents sync logic...")
    # Mock current_user role
    class MockUser:
        id = 1
        role = "Admin"
        
    compare_documents(tender_id=1, db=db, current_user=MockUser())
    
    # 4. Verify RAG index updated
    db.refresh(target_doc)
    print(f"Updated DB uploaded_at: {target_doc.uploaded_at}")
    
    new_chunks = rag_engine.retrieve_relevant_chunks(
        "OJAS", 
        filter_metadata={"vendor_id": v.id},
        k=50
    )
    print(f"Post-Sync RAG chunks for OJAS: {len(new_chunks)}")
    
    if len(new_chunks) > 0:
        print("=== SUCCESS: OJAS auto-sync verification passed! ===")
    else:
        print("=== FAILURE: No chunks found in RAG after sync ===")
        
    db.close()

if __name__ == "__main__":
    main()
