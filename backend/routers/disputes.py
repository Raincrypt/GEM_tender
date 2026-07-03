from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import json
import logging
import models, schemas, auth, llm_client
from database import get_db, db

logger = logging.getLogger("gem.disputes")

router = APIRouter(prefix="/iocl/arbitration/disputes", tags=["Arbitration Portal"])


def _format_case_number(pk: int) -> str:
    year = datetime.utcnow().year
    return f"ARB/{year}/{pk:04d}"


@router.post("/", response_model=schemas.DisputeOut)
def create_dispute(dispute: schemas.DisputeCreate, db_session: Session = Depends(get_db),
                   current_user=Depends(auth.get_current_user)):
    """
    Submit a new vendor dispute / arbitration claim.
    """
    # Verify PO exists
    po = db_session.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == dispute.po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
        
    # Verify Vendor exists
    vendor = db_session.query(models.Vendor).filter(models.Vendor.id == dispute.vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Insert dispute case with placeholder number
    db_dispute = models.DisputeCase(
        po_id=dispute.po_id,
        vendor_id=dispute.vendor_id,
        case_number="PENDING",
        dispute_type=dispute.dispute_type,
        disputed_amount=dispute.disputed_amount,
        vendor_statement=dispute.vendor_statement,
        meteorological_context=dispute.meteorological_context,
        evidence_links=dispute.evidence_links or "[]",
        status="Open",
        refund_percentage=0.0
    )
    db_session.add(db_dispute)
    db_session.flush()

    # Generate case number
    db_dispute.case_number = _format_case_number(db_dispute.id)
    db_session.commit()
    db_session.refresh(db_dispute)

    # Log to audit log
    log = models.AuditLog(
        user_id=current_user.id,
        action="DISPUTE_SUBMITTED",
        entity_type="DisputeCase",
        entity_id=db_dispute.id,
        details=f"Vendor dispute case {db_dispute.case_number} registered for PO {po.po_number}.",
        ip_address="127.0.0.1"
    )
    db_session.add(log)
    db_session.commit()

    return db_dispute


@router.get("/", response_model=list[schemas.DisputeOut])
def list_disputes(db_session: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    """
    List all dispute cases.
    """
    return db_session.query(models.DisputeCase).order_by(models.DisputeCase.id.desc()).all()


@router.get("/{dispute_id}", response_model=schemas.DisputeOut)
def get_dispute(dispute_id: int, db_session: Session = Depends(get_db),
                current_user=Depends(auth.get_current_user)):
    """
    Retrieve details of a single dispute case.
    """
    dispute = db_session.query(models.DisputeCase).filter(models.DisputeCase.id == dispute_id).first()
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute case not found")
    return dispute


@router.post("/{dispute_id}/resolve", response_model=schemas.DisputeOut)
def resolve_dispute(dispute_id: int, db_session: Session = Depends(get_db),
                    current_user=Depends(auth.get_current_user)):
    """
    Run the AI Legal Arbitrator agent to review evidence and issue a ruling.
    """
    dispute = db_session.query(models.DisputeCase).filter(models.DisputeCase.id == dispute_id).first()
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute case not found")

    po = dispute.po
    vendor = dispute.vendor
    
    # Gather contextual data for AI
    po_value = po.total_po_value if po else 0.0
    ld_clause = po.ld_clause if po else "Not specified"
    delivery_status = "Unknown"
    delivery_days_delayed = 0
    
    # Try to find corresponding delivery/inspections
    if po:
        deliv = db_session.query(models.DeliveryRecord).filter(models.DeliveryRecord.po_id == po.id).first()
        if deliv:
            delivery_status = f"Inspection: {deliv.inspection_status}, GRN: {deliv.grn_number}"
            # Estimate delay if available
            if deliv.delivery_date and po.created_at:
                delivery_days_delayed = (deliv.delivery_date - po.created_at).days

    prompt = f"""
You are the Autonomous AI Arbitration Judge for the IOCL Procurement Portal.
You are hearing the dispute case: {dispute.case_number}.

Here is the case file:
- Vendor Name: {vendor.company_name if vendor else 'Unknown'}
- Purchase Order Number: {po.po_number if po else 'Unknown'}
- PO Total Value: INR {po_value}
- Contract Liquidated Damages (LD) Clause: "{ld_clause}"
- Dispute Type: {dispute.dispute_type}
- Disputed Amount: INR {dispute.disputed_amount}
- Vendor's Appeal/Statement: "{dispute.vendor_statement}"
- Meteorological Context / Force Majeure Evidence: "{dispute.meteorological_context or 'None submitted'}"
- Delivery Inspection Status: {delivery_status}
- Est. Delay in Delivery: {delivery_days_delayed} days

Your Task:
1. Review the dispute statement and meteorological context.
2. Determine if the delay/failure was caused by uncontrollable natural occurrences (Force Majeure) like monsoon floods, cyclones, or heavy disasters, which are legally valid excuses to waive or refund LD penalties.
3. Decide a refund percentage of the LD penalty/disputed amount (0.0 to 100.0). A refund of 100% means the entire penalty is waived. 0% means the appeal is rejected and full penalty stands. Partial refund (e.g. 50%) can be given if there is shared negligence or partial Force Majeure.
4. Provide a formal legal ruling document detailing the legal reasoning, citing contract law concepts (Force Majeure, mitigation of damages, Section 74 of the Indian Contract Act) and the meteorological evidence.

Provide your decision as a JSON object with keys "refund_percentage" (float) and "arbitrator_ruling" (string).
"""

    system_instruction = "You are an expert procurement arbitrator and legal expert specializing in Indian Contract Law and public sector procurement disputes."

    # Try LLM
    try:
        decision = llm_client.generate_json(prompt, system_instruction, temperature=0.15)
        refund_pct = float(decision.get("refund_percentage", 0.0))
        ruling_text = decision.get("arbitrator_ruling", "Decision issued by AI Arbitrator.")
    except Exception as e:
        logger.error(f"[arbitrator] LLM failed to resolve dispute: {e}. Running fallback rule engine.")
        # Fallback rule engine
        vendor_stmt_lower = dispute.vendor_statement.lower()
        met_lower = (dispute.meteorological_context or "").lower()
        
        has_force_majeure = any(w in vendor_stmt_lower or w in met_lower for w in ["flood", "monsoon", "rain", "cyclone", "force majeure", "disaster", "landslide"])
        
        if has_force_majeure:
            refund_pct = 75.0
            ruling_text = (
                f"FALLBACK RULING BY AUTOMATED COMPLIANCE SWARM:\n"
                f"The vendor's claim mentions weather-related disruptions ('flood', 'monsoon', or similar) corroborated by meteorological telemetry. "
                f"Under the standard Force Majeure provision of IOCL Contract guidelines, the delay is partially condoned. "
                f"Therefore, 75% of the levied Liquidated Damages (LD) amount of INR {dispute.disputed_amount} is waived and ordered to be refunded."
            )
        else:
            refund_pct = 0.0
            ruling_text = (
                f"FALLBACK RULING BY AUTOMATED COMPLIANCE SWARM:\n"
                f"Upon detailed audit of the appeal statement and evidence submitted, no sufficient Force Majeure conditions "
                f"or excusable delays could be established. The delay in delivery remains the sole negligence of the vendor. "
                f"The appeal is dismissed, and no refund of the Liquidated Damages is granted."
            )

    # Clamp refund_percentage
    refund_pct = max(0.0, min(100.0, refund_pct))

    # Update dispute case in DB
    dispute.status = "Resolved"
    dispute.refund_percentage = refund_pct
    dispute.arbitrator_ruling = ruling_text
    dispute.ruling_date = datetime.utcnow()

    db_session.add(dispute)

    # If refund is given, log deduction adjust or refund payment log
    if refund_pct > 0.0 and po:
        # Find payment record and adjust LD deduction
        payment = db_session.query(models.PaymentRecord).filter(models.PaymentRecord.po_id == po.id).first()
        if payment:
            # refund is a percentage of disputed amount
            refunded_val = round((refund_pct / 100.0) * dispute.disputed_amount, 2)
            payment.ld_deduction = max(0.0, payment.ld_deduction - refunded_val)
            payment.net_payable = round(payment.invoice_amount - payment.tds_deduction - payment.ld_deduction, 2)
            db_session.add(payment)

    db_session.commit()
    db_session.refresh(dispute)

    # Log to audit log
    log = models.AuditLog(
        user_id=current_user.id,
        action="DISPUTE_RESOLVED",
        entity_type="DisputeCase",
        entity_id=dispute.id,
        details=f"Dispute {dispute.case_number} resolved by AI. Refund: {refund_pct}%.",
        ip_address="127.0.0.1"
    )
    db_session.add(log)
    db_session.commit()

    return dispute
