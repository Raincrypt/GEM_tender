import os
import sys
import hashlib
from datetime import datetime, timedelta

# ══════════════════════════════════════════════════════════════════════════════
#  ⚠️  DEVELOPMENT-ONLY SEED SCRIPT — DO NOT USE IN PRODUCTION
#  This script populates the MongoDB database with sample demo data for
#  testing and development purposes. It will WIPE all existing data.
#  All vendor names, tender numbers, and financial values below are
#  fictional test data used solely for demonstrating the system's features.
# ══════════════════════════════════════════════════════════════════════════════

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import MongoSession, mongo_db
import models
import auth
import blockchain

def seed_iocl_lifecycle():
    # Safety confirmation for data wipe
    if os.environ.get("SEED_CONFIRM") != "yes":
        print("=" * 60)
        print("⚠️  WARNING: DEVELOPMENT-ONLY SEED SCRIPT")
        print("This will WIPE ALL existing data and replace it with demo data.")
        print("To run without prompt, set SEED_CONFIRM=yes environment variable.")
        print("=" * 60)
        confirm = input("Type 'yes' to continue: ").strip().lower()
        if confirm != "yes":
            print("Aborted.")
            return
    # Drop existing SQLite database files if present
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gem_tender.db")
    for ext in ["", "-shm", "-wal"]:
        path = db_path + ext
        if os.path.exists(path):
            try:
                os.remove(path)
                print(f"Removed old SQLite database file: {path}")
            except Exception as e:
                print(f"Could not remove SQLite file {path}: {e}")

    db = MongoSession(mongo_db)
    print("Clearing existing MongoDB collections for a fresh start...")
    mongo_db["users"].delete_many({})
    mongo_db["vendors"].delete_many({})
    mongo_db["tenders"].delete_many({})
    mongo_db["evaluation_criteria"].delete_many({})
    mongo_db["bids"].delete_many({})
    mongo_db["bid_scores"].delete_many({})
    mongo_db["bid_documents"].delete_many({})
    mongo_db["purchase_orders"].delete_many({})
    mongo_db["delivery_records"].delete_many({})
    mongo_db["payment_records"].delete_many({})
    mongo_db["audit_logs"].delete_many({})
    mongo_db["pqc_evaluations"].delete_many({})
    mongo_db["indents"].delete_many({})
    mongo_db["ai_decision_logs"].delete_many({})
    mongo_db["dispute_cases"].delete_many({})
    print("Cleared all MongoDB collections.")

    print("Initializing IOCL Enterprise Lifecycle Seed...")

    # ── 1. Admin User ──────────────────────────────────────────
    admin = db.query(models.User).filter(models.User.username == "admin").first()
    if not admin:
        admin = models.User(username="admin", email="admin@iocl.in", full_name="IOCL Admin",
                            hashed_password=auth.get_password_hash("admin123"), role="Admin")
        db.add(admin)
        db.commit()

    # ── 2. Vendors (8 PSU-Vetted) ──────────────────────────────
    print("Registering 8 PSU-Vetted Vendors...")
    vendor_data = [
        {"gem_reg_no": "GEM/V/BHEL-001",  "company_name": "Bharat Heavy Electricals Ltd (BHEL)",  "category": "Heavy Equipment",  "msme": False, "make_in_india": True,  "performance_score": 92.5},
        {"gem_reg_no": "GEM/V/LT-002",    "company_name": "Larsen & Toubro (L&T)",               "category": "Engineering",      "msme": False, "make_in_india": True,  "performance_score": 88.0},
        {"gem_reg_no": "GEM/V/SAIL-003",   "company_name": "Steel Authority of India (SAIL)",     "category": "Raw Materials",    "msme": False, "make_in_india": True,  "performance_score": 75.0},
        {"gem_reg_no": "GEM/V/GAIL-004",   "company_name": "GAIL India Limited",                 "category": "Pipelines",        "msme": False, "make_in_india": True,  "performance_score": 81.0},
        {"gem_reg_no": "GEM/V/TATA-005",   "company_name": "Tata Projects Ltd",                  "category": "EPC",              "msme": False, "make_in_india": True,  "performance_score": 86.5},
        {"gem_reg_no": "GEM/V/SSM-006",    "company_name": "SmallScale Machining Works",          "category": "Spare Parts",      "msme": True,  "make_in_india": True,  "performance_score": 62.0},
        {"gem_reg_no": "GEM/V/RKM-007",    "company_name": "R.K. Metal Fabricators",              "category": "Fabrication",      "msme": True,  "make_in_india": True,  "performance_score": 45.0},
        {"gem_reg_no": "GEM/V/SHADY-008",  "company_name": "Sunrise Global Trading Co.",          "category": "General",          "msme": False, "make_in_india": False, "performance_score": 28.0, "is_blacklisted": True},
    ]
    vendors = []
    for vd in vendor_data:
        v = models.Vendor(**vd)
        db.add(v)
        db.commit()
        db.refresh(v)
        vendors.append(v)

    # ── 3. Material Indents (3 Indents) ────────────────────────
    print("Generating Material Indents...")
    indents_data = [
        {"indent_number": "IOCL/PR/2026/101", "sap_pr_number": "1000456789", "material_code": "MAT-OIL-001",
         "material_description": "High-Pressure Gate Valve for Haldia Refinery", "quantity": 50.0,
         "unit_of_measurement": "NOS", "estimated_unit_rate": 45000.0, "estimated_total_value": 2250000.0,
         "budget_head": "Capital", "cost_center": "HALDIA-REF-01", "plant_code": "HALDIA",
         "indenting_department": "Maintenance", "indenting_officer": "R.K. Sharma",
         "status": "Approved", "urgency": "Urgent", "created_by": admin.id},
         {"indent_number": "IOCL/PR/2026/102", "sap_pr_number": "1000456790", "material_code": "MAT-PIPE-002",
         "material_description": "SS 304 Seamless Pipes (6 inch) for Paradip Refinery", "quantity": 200.0,
         "unit_of_measurement": "MTR", "estimated_unit_rate": 12000.0, "estimated_total_value": 2400000.0,
         "budget_head": "Revenue", "cost_center": "PARADIP-REF-02", "plant_code": "PARADIP",
         "indenting_department": "Projects", "indenting_officer": "S.K. Patel",
         "status": "Approved", "urgency": "Routine", "created_by": admin.id},
         {"indent_number": "IOCL/PR/2026/103", "sap_pr_number": "1000456791", "material_code": "MAT-IT-003",
         "material_description": "Enterprise Server Rack (42U) for Data Center", "quantity": 10.0,
         "unit_of_measurement": "NOS", "estimated_unit_rate": 350000.0, "estimated_total_value": 3500000.0,
         "budget_head": "Capital", "cost_center": "NOIDA-HQ", "plant_code": "NOIDA",
         "indenting_department": "IT", "indenting_officer": "A.K. Verma",
         "status": "Approved", "urgency": "Urgent", "created_by": admin.id},
    ]
    indents = []
    for id_data in indents_data:
        indent = models.Indent(**id_data)
        db.add(indent)
        db.commit()
        db.refresh(indent)
        indents.append(indent)

    # ── 4. Create 3 Tenders (from 3 Indents) ──────────────────
    print("Creating 3 Tenders from Indents...")
    tenders_data = [
        {"bid_number": "IOCL/TENDER/2026/882", "title": "Procurement of HP Gate Valves (50 Nos) for Haldia",
         "category": "Valves & Fittings", "estimated_value": 2250000.0, "technical_weightage": 70.0,
         "financial_weightage": 30.0, "technical_threshold": 70.0, "status": "Awarded",
         "department": "Haldia Refinery", "ministry": "Ministry of Petroleum",
         "published_date": datetime.utcnow() - timedelta(days=45), "closing_date": datetime.utcnow() - timedelta(days=15)},
        {"bid_number": "IOCL/TENDER/2026/883", "title": "SS 304 Seamless Pipe Supply for Paradip Refinery",
         "category": "Pipes & Fittings", "estimated_value": 2400000.0, "technical_weightage": 60.0,
         "financial_weightage": 40.0, "technical_threshold": 65.0, "status": "Under Evaluation",
         "department": "Paradip Refinery", "ministry": "Ministry of Petroleum",
         "published_date": datetime.utcnow() - timedelta(days=20), "closing_date": datetime.utcnow() - timedelta(days=2)},
        {"bid_number": "IOCL/TENDER/2026/884", "title": "42U Enterprise Server Racks for Noida Data Center",
         "category": "IT Hardware", "estimated_value": 3500000.0, "technical_weightage": 80.0,
         "financial_weightage": 20.0, "technical_threshold": 75.0, "status": "Under Evaluation",
         "department": "IT Division", "ministry": "Ministry of Petroleum",
         "published_date": datetime.utcnow() - timedelta(days=15), "closing_date": datetime.utcnow() - timedelta(days=1)},
    ]
    tenders = []
    for idx, td in enumerate(tenders_data):
        t = models.Tender(**td, created_by=admin.id)
        db.add(t)
        db.commit()
        db.refresh(t)
        indents[idx].tender_id = t.id
        db.add(indents[idx])
        db.commit()
        tenders.append(t)

    # ── 5. Evaluation Criteria per Tender ──────────────────────
    print("Defining Evaluation Criteria...")
    criteria_templates = [
        ("Technical Compliance", "Technical", 30.0, "Adherence to IS/API specs"),
        ("Past Performance", "Technical", 20.0, "Track record with PSUs"),
        ("Delivery Schedule", "Technical", 15.0, "Ability to meet timeline"),
        ("Quality Assurance", "Technical", 15.0, "ISO/QMS certifications"),
        ("Financial Bid (L1)", "Financial", 20.0, "Lowest evaluated cost"),
    ]
    for t in tenders:
        for name, ctype, weight, desc in criteria_templates:
            ec = models.EvaluationCriteria(tender_id=t.id, name=name, criteria_type=ctype,
                                            weight=weight, description=desc, max_score=100.0)
            db.add(ec)
        db.commit()

    # ── 6. BIDS (Multiple per Tender with realistic spread) ───
    print("Simulating Multi-Vendor Competitive Bidding...")

    # Tender 1 (Awarded): 5 bids with clear L1 winner
    bid_configs_t1 = [
        (0, 2100000, 378000, 92, 88, "Awarded", 1, 45),   # BHEL - Winner
        (1, 2180000, 392400, 89, 82, "Evaluated", 2, 50),  # L&T
        (4, 2250000, 405000, 85, 78, "Evaluated", 3, 60),  # Tata
        (2, 2350000, 423000, 72, 70, "Evaluated", 4, 55),  # SAIL
        (5, 2400000, 432000, 68, 65, "Disqualified", None, 90),  # SmallScale - DQ
    ]
    # Tender 2 (Under Eval): 4 bids, close competition
    bid_configs_t2 = [
        (1, 2300000, 414000, 88, 90, "Submitted", None, 40),  # L&T
        (0, 2320000, 417600, 91, 85, "Submitted", None, 35),  # BHEL
        (3, 2280000, 410400, 78, 92, "Submitted", None, 50),  # GAIL
        (6, 2310000, 415800, 55, 88, "Submitted", None, 60),  # RK Metal - low tech
    ]
    # Tender 3 (Under Eval): 6 bids with suspicious cluster
    bid_configs_t3 = [
        (0, 3200000, 576000, 94, 90, "Submitted", None, 30),   # BHEL
        (1, 3250000, 585000, 90, 88, "Submitted", None, 35),   # L&T
        (4, 3180000, 572400, 88, 91, "Submitted", None, 28),   # Tata
        (5, 3400000, 612000, 60, 72, "Submitted", None, 45),   # SmallScale
        (6, 3420000, 615600, 48, 68, "Submitted", None, 50),   # RK Metal
        (7, 2800000, 504000, 30, 95, "Disqualified", None, 15), # Sunrise (blacklisted) - abnormally low
    ]

    all_bids = []
    for tender_idx, configs in [(0, bid_configs_t1), (1, bid_configs_t2), (2, bid_configs_t3)]:
        t = tenders[tender_idx]
        for v_idx, bid_amt, taxes, tech, fin, status, rank, delivery in configs:
            composite = round((tech * t.technical_weightage + fin * t.financial_weightage) / 100, 2)
            b = models.Bid(
                tender_id=t.id, vendor_id=vendors[v_idx].id,
                bid_amount=bid_amt, taxes=taxes, total_amount=bid_amt + taxes,
                technical_score=tech, financial_score=fin, composite_score=composite,
                status=status, rank=rank, delivery_period=delivery,
                is_disqualified=(status == "Disqualified"),
                disqualification_reason="Vendor is blacklisted. Bid rejected per CVC guidelines." if status == "Disqualified" and v_idx == 7 else
                                        "Technical score below threshold (68 < 70)." if status == "Disqualified" else None,
                submitted_at=t.published_date + timedelta(days=3 + (int(hashlib.sha256(f'{t.id}-{v_idx}'.encode()).hexdigest(), 16) % 10)),
            )
            db.add(b)
            db.commit()
            db.refresh(b)
            all_bids.append(b)

            # Generate scores per criteria
            criteria = db.query(models.EvaluationCriteria).filter(
                models.EvaluationCriteria.tender_id == t.id).all()
            for c in criteria:
                h = int(hashlib.sha256(f'{b.id}-{c.id}'.encode()).hexdigest(), 16)
                offset = ((h % 101) - 50) / 10.0
                if c.criteria_type == "Technical":
                    score_val = tech + offset
                else:
                    score_val = fin + ((h % 61) - 30) / 10.0
                score_val = max(0, min(100, score_val))
                bs = models.BidScore(bid_id=b.id, criteria_id=c.id, score=round(score_val, 1),
                                     remarks="Auto-evaluated", evaluated_by=admin.id)
                db.add(bs)
            db.commit()

    # ── 7. Purchase Order (for Awarded Tender 1) ──────────────
    print("Generating Purchase Order for Tender #882...")
    winning_bid = all_bids[0]
    po = models.PurchaseOrder(
        po_number="IOCL/PO/2026/501", sap_po_number="4500098765",
        tender_id=tenders[0].id, vendor_id=vendors[0].id, bid_id=winning_bid.id,
        po_value=2100000.0, taxes_amount=378000.0, total_po_value=2478000.0,
        delivery_address="Haldia Refinery, Purba Medinipur, West Bengal - 721602",
        inspection_clause="Third Party Inspection (TPI) by RITES/EIL mandatory before dispatch",
        status="Issued", is_accepted_by_vendor=True,
        accepted_at=datetime.utcnow() - timedelta(days=5)
    )
    db.add(po)
    db.commit()
    db.refresh(po)

    # ── 8. Delivery (GRN/MRN) ─────────────────────────────────
    print("Recording Delivery & Inspection (GRN)...")
    delivery = models.DeliveryRecord(
        po_id=po.id, grn_number="GRN/2026/991",
        delivery_date=datetime.utcnow() - timedelta(days=1),
        received_quantity=25.0, inspection_status="Passed",
        quality_remarks="Dimensions verified. Hydro-test report attached. Compliance with API 6D confirmed. 2 units minor rectification.",
        mrn_number="MRN-882-HAL"
    )
    db.add(delivery)
    db.commit()

    # ── 9. Payment (3-Way Match) ──────────────────────────────
    print("Processing Payment (3-Way Match: PO vs GRN vs Invoice)...")
    payment = models.PaymentRecord(
        po_id=po.id, invoice_number="INV/BHEL/2026/01",
        invoice_amount=1239000.0, tds_deduction=24780.0, net_payable=1214220.0,
        three_way_match=True, payment_status="Released",
        payment_date=datetime.utcnow(), utr_number="SBI-UTR-882991002"
    )
    db.add(payment)
    db.commit()

    # ── 10. Blockchain Audit Trail ────────────────────────────
    print("Mining Blockchain Audit Entries...")
    audit_actions = [
        ("INDENT_CREATED", "Indent", indents[0].id, "Material indent IOCL/PR/2026/101 raised by R.K. Sharma"),
        ("INDENT_APPROVED", "Indent", indents[0].id, "PAC Committee approved indent for tendering"),
        ("TENDER_PUBLISHED", "Tender", tenders[0].id, "Tender IOCL/TENDER/2026/882 published on GEM portal"),
        ("BID_RECEIVED", "Tender", tenders[0].id, "5 bids received from registered vendors"),
        ("EVALUATION_STARTED", "Tender", tenders[0].id, "Technical evaluation committee convened"),
        ("FINANCIAL_BID_OPENED", "Tender", tenders[0].id, "Financial bids opened after technical qualification"),
        ("TENDER_AWARDED", "Tender", tenders[0].id, "Contract awarded to BHEL (L1) at Rs.24.78L"),
        ("PO_ISSUED", "PurchaseOrder", po.id, "PO IOCL/PO/2026/501 issued to BHEL"),
        ("GRN_RECORDED", "Delivery", 1, "25 units received and inspected at Haldia"),
        ("PAYMENT_RELEASED", "Payment", 1, "Payment of Rs.12.14L released via NEFT (UTR: SBI-UTR-882991002)"),
    ]
    for action, entity, eid, details in audit_actions:
        blockchain.create_audit_log(db, admin.id, action, entity, eid, details)

    print("="*60)
    print("IOCL ENTERPRISE LIFECYCLE SEED COMPLETE!")
    print(f"  Vendors:     {len(vendors)}")
    print(f"  Indents:     {len(indents)}")
    print(f"  Tenders:     {len(tenders)}")
    print(f"  Total Bids:  {len(all_bids)}")
    print(f"  POs:         1")
    print(f"  Deliveries:  1")
    print(f"  Payments:    1")
    print(f"  Audit Logs:  {len(audit_actions)}")
    print("="*60)

if __name__ == "__main__":
    seed_iocl_lifecycle()
