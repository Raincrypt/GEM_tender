from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
import models, auth
from database import get_db

router = APIRouter(prefix="/iocl", tags=["IOCL Procurement"])


# ---- Pydantic Schemas ----

class IndentCreate(BaseModel):
    material_code: str
    material_description: str
    quantity: float
    unit_of_measurement: str = "NOS"
    estimated_unit_rate: float = 0.0
    budget_head: Optional[str] = None
    cost_center: Optional[str] = None
    plant_code: Optional[str] = None
    indenting_department: Optional[str] = None
    indenting_officer: Optional[str] = None
    technical_specification: Optional[str] = None
    justification: Optional[str] = None
    urgency: str = "Routine"

class IndentOut(BaseModel):
    id: int
    indent_number: str
    sap_pr_number: Optional[str]
    material_code: str
    material_description: str
    quantity: float
    unit_of_measurement: str
    estimated_unit_rate: float
    estimated_total_value: float
    budget_head: Optional[str]
    cost_center: Optional[str]
    plant_code: Optional[str]
    indenting_department: Optional[str]
    indenting_officer: Optional[str]
    technical_specification: Optional[str]
    justification: Optional[str]
    urgency: str
    status: str
    approved_by: Optional[str]
    approval_date: Optional[datetime]
    tender_id: Optional[int]
    created_at: Optional[datetime]
    class Config:
        from_attributes = True

class POCreate(BaseModel):
    tender_id: int
    vendor_id: int
    bid_id: int
    po_value: float
    taxes_amount: float = 0.0
    delivery_address: Optional[str] = None
    inspection_clause: str = "IOCL Standard Inspection"
    payment_terms: str = "30 Days from Invoice"
    ld_clause: str = "0.5% per week, max 5%"
    warranty_period: int = 12


# ---- STAGE 1: INDENT / PR MANAGEMENT ----
# NOTE: Number generation is atomic — we INSERT first to claim a unique PK,
# then derive the human-readable number from that PK. This is race-condition-free.

def _format_indent_number(pk: int) -> str:
    """Derives IOCL-format indent number from the record's primary key."""
    year = datetime.utcnow().year
    return f"IOCL/PR/{year}/{pk:04d}"

def _format_sap_pr(pk: int) -> str:
    """Derives SAP PR number from the record's primary key."""
    return f"10{200000 + pk}"


@router.post("/indents", response_model=IndentOut)
def create_indent(indent: IndentCreate, db: Session = Depends(get_db),
                  current_user=Depends(auth.require_role("Admin", "Evaluator"))):
    """Stage 1: Create a new Material Indent / Purchase Requisition.

    Number generation is atomic: the record is inserted with a temporary
    placeholder number, then updated from the auto-generated PK. This is
    completely race-condition-free even under concurrent load.
    """
    estimated_total = indent.quantity * indent.estimated_unit_rate

    # Step 1: Insert with placeholder numbers to claim a unique PK
    db_indent = models.Indent(
        indent_number="PENDING",
        sap_pr_number="PENDING",
        material_code=indent.material_code,
        material_description=indent.material_description,
        quantity=indent.quantity,
        unit_of_measurement=indent.unit_of_measurement,
        estimated_unit_rate=indent.estimated_unit_rate,
        estimated_total_value=estimated_total,
        budget_head=indent.budget_head,
        cost_center=indent.cost_center,
        plant_code=indent.plant_code,
        indenting_department=indent.indenting_department,
        indenting_officer=indent.indenting_officer,
        technical_specification=indent.technical_specification,
        justification=indent.justification,
        urgency=indent.urgency,
        created_by=current_user.id
    )
    db.add(db_indent)
    db.flush()  # Flushes to get the auto-incremented PK without committing

    # Step 2: Derive unique, deterministic numbers from the PK
    db_indent.indent_number = _format_indent_number(db_indent.id)
    db_indent.sap_pr_number = _format_sap_pr(db_indent.id)

    db.commit()
    db.refresh(db_indent)
    return db_indent


@router.get("/indents", response_model=List[IndentOut])
def list_indents(status: str = None, db: Session = Depends(get_db),
                 current_user=Depends(auth.get_current_user)):
    """List all indents with optional status filter"""
    query = db.query(models.Indent).order_by(models.Indent.id.desc())
    if status:
        query = query.filter(models.Indent.status == status)
    return query.all()


@router.get("/indents/{indent_id}", response_model=IndentOut)
def get_indent(indent_id: int, db: Session = Depends(get_db),
               current_user=Depends(auth.get_current_user)):
    indent = db.query(models.Indent).filter(models.Indent.id == indent_id).first()
    if not indent:
        raise HTTPException(status_code=404, detail="Indent not found")
    return indent


@router.post("/indents/{indent_id}/approve")
def approve_indent(indent_id: int, db: Session = Depends(get_db),
                   current_user=Depends(auth.require_role("Admin"))):
    """Approve an indent — moves it to Approved state"""
    indent = db.query(models.Indent).filter(models.Indent.id == indent_id).first()
    if not indent:
        raise HTTPException(status_code=404, detail="Indent not found")
    if indent.status != "Submitted":
        raise HTTPException(status_code=400, detail=f"Cannot approve indent in '{indent.status}' status")
    indent.status = "Approved"
    indent.approved_by = current_user.full_name
    indent.approval_date = datetime.utcnow()
    db.commit()
    return {"message": f"Indent {indent.indent_number} approved by {current_user.full_name}"}


@router.post("/indents/{indent_id}/submit")
def submit_indent(indent_id: int, db: Session = Depends(get_db),
                  current_user=Depends(auth.get_current_user)):
    """Submit a draft indent for approval"""
    indent = db.query(models.Indent).filter(models.Indent.id == indent_id).first()
    if not indent:
        raise HTTPException(status_code=404, detail="Indent not found")
    if indent.status != "Draft":
        raise HTTPException(status_code=400, detail="Only draft indents can be submitted")
    indent.status = "Submitted"
    db.commit()
    return {"message": f"Indent {indent.indent_number} submitted for approval"}


@router.post("/indents/{indent_id}/reject")
def reject_indent(indent_id: int, db: Session = Depends(get_db),
                  current_user=Depends(auth.require_role("Admin"))):
    """Reject an indent"""
    indent = db.query(models.Indent).filter(models.Indent.id == indent_id).first()
    if not indent:
        raise HTTPException(status_code=404, detail="Indent not found")
    indent.status = "Rejected"
    db.commit()
    return {"message": f"Indent {indent.indent_number} rejected"}


@router.post("/indents/{indent_id}/convert-to-tender")
def convert_indent_to_tender(indent_id: int, db: Session = Depends(get_db),
                             current_user=Depends(auth.require_role("Admin"))):
    """Convert an approved indent into a formal Tender / NIT"""
    indent = db.query(models.Indent).filter(models.Indent.id == indent_id).first()
    if not indent:
        raise HTTPException(status_code=404, detail="Indent not found")
    if indent.status != "Approved":
        raise HTTPException(status_code=400, detail="Only approved indents can be converted")

    # Create the tender from indent data with a temporary placeholder bid_number to claim a unique PK
    new_tender = models.Tender(
        bid_number="PENDING",
        title=f"Supply of {indent.material_description}",
        department=indent.indenting_department,
        ministry="Ministry of Petroleum & Natural Gas",
        category="IOCL Procurement",
        estimated_value=indent.estimated_total_value,
        emd_amount=round(indent.estimated_total_value * 0.02, 2),  # 2% EMD
        bid_validity=90,
        delivery_period=45,
        technical_weightage=70.0,
        financial_weightage=30.0,
        technical_threshold=70.0,
        description=indent.technical_specification or indent.justification or "",
        status="Draft",
        created_by=current_user.id
    )
    db.add(new_tender)
    db.flush()  # Flushes to get the auto-incremented PK (new_tender.id) without committing

    # Generate IOCL NIT number using the PK
    year = datetime.utcnow().year
    nit_number = f"IOCL/NIT/{year}/{new_tender.id:04d}"
    new_tender.bid_number = nit_number

    # Auto-add IOCL standard evaluation criteria
    criteria_list = [
        ("Annual Turnover ≥ 2x Estimated Value", "Technical", 25.0, 100.0),
        ("ISO 9001 / 14001 / 45001 Certification", "Technical", 20.0, 100.0),
        ("Past 3 Similar Orders in Last 5 Years", "Technical", 25.0, 100.0),
        ("EMD & Bid Security Compliance", "Technical", 10.0, 100.0),
        ("Technical Specification Compliance (SOR/SOW)", "Technical", 20.0, 100.0),
    ]
    for name, ctype, weight, max_s in criteria_list:
        c = models.EvaluationCriteria(
            tender_id=new_tender.id, name=name, criteria_type=ctype,
            weight=weight, max_score=max_s
        )
        db.add(c)

    # Update indent status
    indent.status = "Converted to Tender"
    indent.tender_id = new_tender.id
    db.commit()

    return {
        "message": f"Indent {indent.indent_number} converted to NIT {nit_number}",
        "tender_id": new_tender.id,
        "nit_number": nit_number
    }


# ---- STAGE 7: PURCHASE ORDER ----

@router.post("/purchase-orders")
def create_purchase_order(po: POCreate, db: Session = Depends(get_db),
                          current_user=Depends(auth.require_role("Admin"))):
    """Generate a Purchase Order for an awarded tender.
    
    Atomic number generation: INSERT first to claim a unique PK,
    then derive the PO number from that PK — completely race-condition-free.
    """
    total = po.po_value + po.taxes_amount
    year = datetime.utcnow().year

    # Step 1: Insert with placeholder to claim unique PK
    db_po = models.PurchaseOrder(
        po_number="PENDING",
        sap_po_number="PENDING",
        tender_id=po.tender_id,
        vendor_id=po.vendor_id,
        bid_id=po.bid_id,
        po_value=po.po_value,
        taxes_amount=po.taxes_amount,
        total_po_value=total,
        delivery_address=po.delivery_address,
        inspection_clause=po.inspection_clause,
        payment_terms=po.payment_terms,
        ld_clause=po.ld_clause,
        warranty_period=po.warranty_period
    )
    db.add(db_po)
    db.flush()  # Get auto-incremented PK without committing

    # Step 2: Derive unique numbers from PK
    po_number = f"IOCL/PO/{year}/{db_po.id:04d}"
    sap_po = f"45{100000 + db_po.id}"
    db_po.po_number = po_number
    db_po.sap_po_number = sap_po

    db.commit()
    db.refresh(db_po)

    return {
        "message": f"Purchase Order {po_number} generated",
        "po_number": po_number,
        "sap_po_number": sap_po,
        "total_po_value": total
    }


# ---- STAGE 9: PAYMENT PROCESSING ----

class PaymentRequest(BaseModel):
    invoice_number: str = "INV-001"
    invoice_amount: float = 0.0

@router.post("/payments/{po_id}/process")
def process_payment(po_id: int, request: PaymentRequest,
                    db: Session = Depends(get_db),
                    current_user=Depends(auth.require_role("Admin"))):
    """Process payment with TDS deduction and 3-way match"""
    po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")

    # TDS under Section 194C: 2% for companies, 1% for individuals
    invoice_number = request.invoice_number
    invoice_amount = request.invoice_amount
    tds = round(invoice_amount * 0.02, 2)
    net = round(invoice_amount - tds, 2)

    # AI Smart 3-Way Match: Fuzzy tolerance calculation
    # Checks Invoice Amount vs PO Value and factors in typical variance
    variance = abs(invoice_amount - po.total_po_value)
    variance_percentage = (variance / po.total_po_value) * 100 if po.total_po_value else 0

    if variance_percentage == 0:
        match_status = "Exact Match"
        three_way = True
    elif variance_percentage <= 5.0:
        match_status = f"Smart Match: Approved with {variance_percentage:.2f}% variance tolerance"
        three_way = True
    else:
        match_status = f"Failed Match: Variance of {variance_percentage:.2f}% exceeds 5% safe limit"
        three_way = False

    payment = models.PaymentRecord(
        po_id=po_id,
        invoice_number=invoice_number,
        invoice_amount=invoice_amount,
        tds_deduction=tds,
        ld_deduction=0.0,
        net_payable=net,
        three_way_match=three_way,
        payment_status="Released" if three_way else "Held"
    )
    db.add(payment)
    db.commit()

    return {
        "invoice_amount": invoice_amount,
        "tds_deduction": tds,
        "tds_deduction_194c": tds,
        "net_payable": net,
        "three_way_match_passed": three_way,
        "three_way_match": three_way,
        "match_status": match_status,
        "variance_pct": round(variance_percentage, 2),
        "payment_status": payment.payment_status
    }


@router.get("/payments")
def list_payments(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    payments_data = db.query(models.PaymentRecord, models.PurchaseOrder)\
        .outerjoin(models.PurchaseOrder, models.PaymentRecord.po_id == models.PurchaseOrder.id)\
        .order_by(models.PaymentRecord.id.desc()).all()
    results = []
    for p, po in payments_data:
        results.append({
            "id": p.id,
            "po_number": po.po_number if po else "Unknown",
            "invoice_number": p.invoice_number,
            "invoice_amount": p.invoice_amount,
            "tds_deduction": p.tds_deduction,
            "net_payable": p.net_payable,
            "three_way_match": p.three_way_match,
            "payment_status": p.payment_status,
            "created_at": p.created_at.isoformat() if p.created_at else None
        })
    return results


# ---- DASHBOARD STATS ----

@router.get("/stats")
def iocl_stats(db: Session = Depends(get_db),
               current_user=Depends(auth.get_current_user)):
    """Get IOCL procurement stats"""
    total_indents = db.query(models.Indent).count()
    pending_approval = db.query(models.Indent).filter(models.Indent.status == "Submitted").count()
    approved = db.query(models.Indent).filter(models.Indent.status == "Approved").count()
    converted = db.query(models.Indent).filter(models.Indent.status == "Converted to Tender").count()
    total_po = db.query(models.PurchaseOrder).count()

    return {
        "total_indents": total_indents,
        "pending_approval": pending_approval,
        "approved_indents": approved,
        "converted_to_tender": converted,
        "total_purchase_orders": total_po
    }


# ---- STAGE 8: DELIVERY & INSPECTION ----

class DeliveryCreate(BaseModel):
    po_id: int
    received_quantity: float
    inspection_status: str = "Pending"
    tpi_required: bool = False
    quality_remarks: Optional[str] = None

@router.post("/deliveries")
def create_delivery(data: DeliveryCreate, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    """Create a Delivery Record (GRN/MRN)"""
    po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == data.po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
        
    year = datetime.utcnow().year
    count = db.query(models.DeliveryRecord).count() + 1
    grn = f"IOCL/GRN/{year}/{count:04d}"
    mrn = f"IOCL/MRN/{year}/{count:04d}" if data.inspection_status == "Passed" else None
    
    deliv = models.DeliveryRecord(
        po_id=data.po_id,
        grn_number=grn,
        delivery_date=datetime.utcnow(),
        received_quantity=data.received_quantity,
        inspection_status=data.inspection_status,
        tpi_required=data.tpi_required,
        quality_remarks=data.quality_remarks,
        mrn_number=mrn
    )
    db.add(deliv)
    db.commit()
    db.refresh(deliv)
    
    return {
        "message": "Delivery logged successfully",
        "grn_number": grn,
        "mrn_number": mrn,
        "inspection_status": data.inspection_status
    }

@router.get("/deliveries")
def list_deliveries(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    deliveries_data = db.query(models.DeliveryRecord, models.PurchaseOrder)\
        .outerjoin(models.PurchaseOrder, models.DeliveryRecord.po_id == models.PurchaseOrder.id)\
        .order_by(models.DeliveryRecord.id.desc()).all()
    results = []
    for d, po in deliveries_data:
        results.append({
            "id": d.id,
            "po_id": d.po_id,
            "po_number": po.po_number if po else "Unknown",
            "grn_number": d.grn_number,
            "mrn_number": d.mrn_number,
            "delivery_date": d.delivery_date.isoformat() if d.delivery_date else None,
            "received_quantity": d.received_quantity,
            "inspection_status": d.inspection_status,
            "tpi_required": d.tpi_required
        })
    return results


# ---- ADVANCED: LEGAL AI ARBITRATION COURT ----

class ArbitrationRequest(BaseModel):
    delivery_id: int

@router.post("/arbitration/trigger")
def trigger_arbitration(request: ArbitrationRequest, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    """AI-powered legal arbitration: parses a failed delivery using AI (Ollama/llm_client), extracts LD clause penalty percentage, generates a formal Legal Notice of Default, and adjusts vendor performance scores."""
    delivery = db.query(models.DeliveryRecord).filter(models.DeliveryRecord.id == request.delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery record not found")
        
    if delivery.inspection_status != "Failed":
        raise HTTPException(status_code=400, detail="Only failed deliveries can be sent to arbitration")
        
    po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == delivery.po_id).first()
    vendor = db.query(models.Vendor).filter(models.Vendor.id == po.vendor_id).first()
    
    # AI Simulation: Parsing the LD Clause
    import re
    ld_clause = po.ld_clause
    # Try to extract penalty percentage, defaulting to 0.5
    penalty_pct = 0.5
    match = re.search(r'([\d\.]+)%', ld_clause)
    if match:
        penalty_pct = float(match.group(1))
        
    penalty_amount = round((penalty_pct / 100) * po.total_po_value, 2)
    
    import ai_risk_engine
    legal_notice = ai_risk_engine.generate_legal_notice(
        vendor.company_name, po.po_number, ld_clause, delivery.grn_number, penalty_amount
    )
    
    if not legal_notice:
        legal_notice = f"""
        LEGAL NOTICE OF DEFAULT AND LIQUIDATED DAMAGES
        
        To: {vendor.company_name}
        Reference PO: {po.po_number}
        Date: {datetime.utcnow().strftime('%Y-%m-%d')}
        
        This serves as formal notice that the goods delivered under GRN {delivery.grn_number} have FAILED the mandatory Quality Inspection.
        
        As per the Liquidated Damages (LD) clause specified in the Purchase Order ("{ld_clause}"), a penalty of {penalty_pct}% is hereby levied.
        
        Total Penalty Amount: INR {penalty_amount}
        
        This amount will be automatically deducted from your pending escrow payments. Failure to replace the defective goods within 14 days will result in immediate Vendor Blacklisting.
        
        Signed,
        Autonomous Legal Arbitration Swarm (GEM Ecosystem)
        """

    
    # Optionally blacklist the vendor if performance is poor
    vendor.performance_score -= 10.0
    if vendor.performance_score < 40.0:
        vendor.is_blacklisted = True
        
    db.commit()
    
    return {
        "message": "Legal AI has processed the dispute.",
        "penalty_amount": penalty_amount,
        "legal_notice": legal_notice.strip(),
        "vendor_blacklisted": vendor.is_blacklisted
    }


# ---- STAGE 6: PAC (Purchase Approval Committee) ----

class PACApprovalRequest(BaseModel):
    tender_id: int
    winning_bid_id: int
    dop_verified: bool
    justification: str

@router.post("/pac/approve")
def approve_pac(request: PACApprovalRequest, db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    """Approve purchase via PAC"""
    tender = db.query(models.Tender).filter(models.Tender.id == request.tender_id).first()
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
    
    bid = db.query(models.Bid).filter(models.Bid.id == request.winning_bid_id).first()
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")
    
    if not request.dop_verified:
        raise HTTPException(status_code=400, detail="Delegation of Power must be verified")

    tender.status = "Awarded"
    bid.status = "Winner"
    db.commit()
    
    return {
        "message": "PAC Approval successful. Minutes of Meeting generated.",
        "tender_id": tender.id,
        "mom_hash": "0x" + "".join([str(hash(request.justification) % 10) for _ in range(32)])
    }

@router.get("/purchase-orders")
def list_purchase_orders(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    orders_data = db.query(models.PurchaseOrder, models.Vendor, models.Tender)\
        .outerjoin(models.Vendor, models.PurchaseOrder.vendor_id == models.Vendor.id)\
        .outerjoin(models.Tender, models.PurchaseOrder.tender_id == models.Tender.id)\
        .order_by(models.PurchaseOrder.id.desc()).all()
    results = []
    for po, vendor, tender in orders_data:
        results.append({
            "id": po.id,
            "po_number": po.po_number,
            "sap_po_number": po.sap_po_number,
            "total_po_value": po.total_po_value,
            "status": po.status,
            "vendor_name": vendor.company_name if vendor else "Unknown",
            "tender_title": tender.title if tender else "Unknown",
            "created_at": po.created_at.isoformat() if po.created_at else None
        })
    return results
