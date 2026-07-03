import os
import sys
import json
import re

# ══════════════════════════════════════════════════════════════════════════════
#  ⚠️  DEVELOPMENT-ONLY SEED SCRIPT — DO NOT USE IN PRODUCTION
#  This script indexes bidder documents from the TBA1 uploads folder into
#  the RAG (Retrieval-Augmented Generation) knowledge base for testing.
#  It also creates vendor and bid records if they don't already exist.
#  All data created is for development/demo purposes only.
# ══════════════════════════════════════════════════════════════════════════════

# Add backend directory to path
sys.path.append(os.path.abspath('backend'))
sys.path.append(os.path.abspath('backend/routers'))

from database import SessionLocal
import models
import rag_engine
from routers.documents import extract_text_from_file, redact_pii

def classify_file(filename: str) -> str:
    """Classify a file based on its name to determine RAG doc_type."""
    fu = filename.upper()
    if any(kw in fu for kw in ["MAF", "MANUFACTURER AUTHORIZATION", "AUTHORIZATION", "OEM AUTHORI", "OEM_AUTH"]):
        return "compliance"  # Maps to options in frontend (compliance)
    if any(kw in fu for kw in ["CREDENTIAL", " - PO", "PURCHASE ORDER", "WORK ORDER", "COMPLETION", "CONTRACT"]):
        return "contract"    # Maps to options in frontend (contract)
    if any(kw in fu for kw in ["ANNEX", "ATC", "COMPLIANCE", "DECLARATION", "UNDERTAKING"]):
        return "technical"   # Maps to options in frontend (technical)
    if any(kw in fu for kw in ["FINANCIAL", "BALANCE", "TURNOVER", "NETWORTH", "CA ", "AUDIT", "ITR", "PROFIT", "LOSS"]):
        return "financial"   # Maps to options in frontend (financial)
    if any(kw in fu for kw in ["ISO", "CERT", "QUALITY", "BIS"]):
        return "compliance"
    return "general"

def seed_rag_index():
    print("=== SEEDING RAG INDEX ===")
    
    # Monkey-patch save_index and add_document_to_index to bypass slow CPU neural embedding during db setup
    # real_save_index = rag_engine.save_index
    # rag_engine.save_index = lambda *args, **kwargs: True
    
    # real_add_document = rag_engine.add_document_to_index
    # rag_engine.add_document_to_index = lambda *args, **kwargs: True

    db = SessionLocal()
    
    TBA1_DIR = r"C:\Users\Mrinmoy\Downloads\tender (2)\tender\backend\uploads\TBA1"
    ocr_cache_path = os.path.join(TBA1_DIR, "ocr_cache.json")
    
    if not os.path.exists(ocr_cache_path):
        print(f"Error: ocr_cache.json not found at {ocr_cache_path}")
        return
        
    with open(ocr_cache_path, "r", encoding="utf-8") as f:
        ocr_cache = json.load(f)
        
    print(f"Loaded OCR Cache with {len(ocr_cache)} entries.")
    
    # 1. First, register all subdirectories under TBA1 as folder vendors in the database if not present
    tba1_folders = []
    if os.path.exists(TBA1_DIR):
        for entry in os.listdir(TBA1_DIR):
            full_entry_path = os.path.join(TBA1_DIR, entry)
            if os.path.isdir(full_entry_path) and not entry.startswith('.') and entry.lower() not in ['ocr_cache', 'layout_cache']:
                tba1_folders.append(entry)
    else:
        print(f"Error: TBA1_DIR not found at {TBA1_DIR}")
        return

    print(f"Discovered {len(tba1_folders)} vendor folders under TBA1.")
    
    vendor_id_map = {}
    for folder_name in tba1_folders:
        clean_name = folder_name
        if "NOT ACCEPTED" in clean_name.upper():
            clean_name = re.sub(r'[-\s]+NOT ACCEPTED.*', '', clean_name, flags=re.IGNORECASE).strip()
        clean_name = clean_name.replace("_", " ").strip()
        
        # Find if vendor already exists
        vendor = db.query(models.Vendor).filter(models.Vendor.company_name.ilike(clean_name)).first()
        if not vendor:
            # Create a new vendor record
            gem_reg = "GEM/V/" + "".join(c for c in clean_name if c.isalnum())[:10].upper()
            vendor = models.Vendor(
                gem_reg_no=gem_reg,
                company_name=clean_name,
                category="IT Hardware & Services",
                msme=True,
                make_in_india=True,
                performance_score=82.0,
                is_blacklisted=False
            )
            db.add(vendor)
            db.commit()
            db.refresh(vendor)
            print(f"Created vendor in DB: {clean_name} (ID: {vendor.id})")
        else:
            print(f"Vendor already in DB: {clean_name} (ID: {vendor.id})")
        
        # Seed manual baseline bids for Tender 1
        bid = db.query(models.Bid).filter(models.Bid.vendor_id == vendor.id, models.Bid.tender_id == 1).first()
        if not bid:
            is_disq = (
                clean_name.upper() in ["OJAS", "UNIQUE SERVICES PRIVATE LIMITED", "VISHWANJALI TECHNOLOGY PRIVATE LIMITED"]
                or "NOT ACCEPTED" in folder_name.upper()
            )
            status = "Disqualified" if is_disq else "Submitted"
            disq_reason = "Manual forensic audit checklist verification failed." if is_disq else None
            
            bid = models.Bid(
                tender_id=1,
                vendor_id=vendor.id,
                bid_amount=45.0 + (hash(clean_name) % 15),
                tax_amount=4.5,
                technical_score=85.0 if not is_disq else 45.0,
                financial_score=0.0,
                status=status,
                is_disqualified=is_disq,
                disqualification_reason=disq_reason
            )
            db.add(bid)
            db.commit()
            print(f"Created bid for vendor {clean_name} (ID: {vendor.id}, Status: {status})")

        vendor_id_map[folder_name.upper()] = vendor.id

    # 2. Seed bidder documents
    indexed_count = 0
    skipped_count = 0
    
    for folder_name in tba1_folders:
        folder_path = os.path.join(TBA1_DIR, folder_name)
        if not os.path.exists(folder_path):
            print(f"Warning: directory {folder_path} does not exist.")
            continue
            
        v_id = vendor_id_map.get(folder_name.upper())
        
        for fname in os.listdir(folder_path):
            file_path = os.path.join(folder_path, fname)
            if not os.path.isfile(file_path):
                continue
                
            # Lookup in OCR cache
            fu = fname.upper()
            
            # Find in ocr_cache (keys are full paths or filenames)
            text = ""
            for cache_key, cache_val in ocr_cache.items():
                clean_key = cache_key.replace("\\", "/").split("/")[-1].upper()
                if clean_key == fu:
                    text = cache_val
                    break
                    
            if not text:
                print(f"Text not found in cache for {fname}, attempting direct extraction...")
                try:
                    text = extract_text_from_file(file_path)
                    text = redact_pii(text)
                except Exception as e:
                    print(f"Failed to extract text for {fname}: {e}")
                    
            if text and text.strip():
                doc_type = classify_file(fname)
                metadata = {
                    "vendor_id": v_id,
                    "tender_id": 1,  # PQC is evaluated for Tender 1
                    "doc_type": doc_type,
                    "filename": fname
                }
                
                success = rag_engine.add_document_to_index(text[:30000], metadata=metadata)
                if success:
                    print(f"Indexed document: {fname} (Vendor ID: {v_id}, Type: {doc_type})")
                    indexed_count += 1
                    
                    # Also register BidDocument record in database
                    # First check if bid exists for this vendor and tender_id=1
                    bid_rec = db.query(models.Bid).filter(
                        models.Bid.vendor_id == v_id,
                        models.Bid.tender_id == 1
                    ).first()
                    if bid_rec:
                        # Map filename keywords to nice document type labels
                        clean_type = "Manufacturer Authorization Form (MAF)" if "MAF" in fu else \
                                     "Enquiry Cum Offer" if "ENQUIRY" in fu or "OFFER" in fu else \
                                     "Annexure A" if "ANNEXURE A" in fu or "ANNEX_A" in fu else \
                                     "Annexure B" if "ANNEXURE B" in fu or "ANNEX_B" in fu else \
                                     "Annexure X" if "ANNEXURE X" in fu or "ANNEX_X" in fu or "ATC" in fu else \
                                     doc_type.capitalize()
                        
                        db_doc = models.BidDocument(
                            bid_id=bid_rec.id,
                            document_type=clean_type,
                            file_path=file_path.replace("\\", "/"),
                            ocr_extracted_text=text,
                            verified=True
                        )
                        db.add(db_doc)
                        db.commit()
                        print(f"  [DB] Created BidDocument record for {fname} (Type: {clean_type})")
                else:
                    print(f"Failed to index: {fname}")
            else:
                print(f"Skipped empty document: {fname}")
                skipped_count += 1
                
    # 3. Seed Tender Rules and tender description documents
    rules_pdf_path = r"C:\Users\Mrinmoy\Downloads\tender (2)\tender\backend\uploads\Rules.pdf"
    if os.path.exists(rules_pdf_path):
        print("Extracting and indexing Rules.pdf...")
        try:
            rules_text = extract_text_from_file(rules_pdf_path)
            rules_text = redact_pii(rules_text)
            if rules_text and rules_text.strip():
                metadata = {
                    "tender_id": 1,
                    "doc_type": "compliance",
                    "filename": "Rules.pdf"
                }
                success = rag_engine.add_document_to_index(rules_text, metadata=metadata)
                if success:
                    print("Indexed Rules.pdf successfully.")
                    indexed_count += 1
        except Exception as e:
            print(f"Failed to index Rules.pdf: {e}")

    pqc_text_path = r"C:\Users\Mrinmoy\Downloads\tender (2)\tender\backend\uploads\pqc_text.txt"
    if os.path.exists(pqc_text_path):
        print("Extracting and indexing pqc_text.txt...")
        try:
            with open(pqc_text_path, "r", encoding="utf-8") as f:
                pqc_text = f.read()
            pqc_text = redact_pii(pqc_text)
            if pqc_text and pqc_text.strip():
                metadata = {
                    "tender_id": 1,
                    "doc_type": "compliance",
                    "filename": "pqc_text.txt"
                }
                success = rag_engine.add_document_to_index(pqc_text, metadata=metadata)
                if success:
                    print("Indexed pqc_text.txt successfully.")
                    indexed_count += 1
        except Exception as e:
            print(f"Failed to index pqc_text.txt: {e}")

    # Restore and save final index once at the end
    rag_engine.add_document_to_index = real_add_document
    rag_engine.save_index = real_save_index
    rag_engine.save_index()
    
    print("=" * 40)
    print(f"Seeding completed: {indexed_count} documents indexed, {skipped_count} skipped.")
    print("RAG Index Stats:")
    print(rag_engine.get_index_stats())
    print("=" * 40)
    
    db.close()

if __name__ == "__main__":
    seed_rag_index()
