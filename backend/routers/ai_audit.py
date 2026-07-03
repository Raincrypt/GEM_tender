"""
AI Audit Trail Router — Tracks AI recommendations vs human decisions.
Provides accuracy metrics, feedback collection, and decision transparency.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func as sql_func, extract
from datetime import datetime
from typing import Optional, List
import models, schemas, auth, blockchain
from database import get_db

router = APIRouter(prefix="/ai-audit", tags=["AI Audit Trail"])


@router.post("/log-decision", response_model=schemas.AIDecisionLogOut)
def log_ai_decision(
    payload: schemas.AIDecisionLogCreate,
    db: Session = Depends(get_db),
    current_user=Depends(auth.require_role("Admin", "Evaluator")),
):
    """Log a new AI recommendation for a bid/criteria pair."""
    # Validate bid exists
    bid = db.query(models.Bid).filter(models.Bid.id == payload.bid_id).first()
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")

    # Validate tender exists
    tender = db.query(models.Tender).filter(models.Tender.id == payload.tender_id).first()
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")

    # Validate criteria if provided
    if payload.criteria_id is not None:
        criteria = db.query(models.EvaluationCriteria).filter(
            models.EvaluationCriteria.id == payload.criteria_id
        ).first()
        if not criteria:
            raise HTTPException(status_code=404, detail="Evaluation criteria not found")

    log_entry = models.AIDecisionLog(
        bid_id=payload.bid_id,
        criteria_id=payload.criteria_id,
        tender_id=payload.tender_id,
        user_id=current_user.id,
        ai_score=payload.ai_score,
        ai_confidence=payload.ai_confidence,
        ai_rationale=payload.ai_rationale,
        ai_model_version=payload.ai_model_version,
        context_snapshot=payload.context_snapshot,
    )
    db.add(log_entry)
    db.flush()

    blockchain.create_audit_log(
        db=db,
        user_id=current_user.id,
        action="AI_DECISION_LOGGED",
        entity_type="AIDecisionLog",
        entity_id=log_entry.id,
        details=f"AI score={payload.ai_score}, confidence={payload.ai_confidence} for bid #{payload.bid_id}",
    )
    db.commit()
    db.refresh(log_entry)
    return log_entry


@router.post("/feedback/{decision_id}", response_model=schemas.AIDecisionLogOut)
def submit_feedback(
    decision_id: int,
    payload: schemas.AIFeedbackSubmit,
    db: Session = Depends(get_db),
    current_user=Depends(auth.require_role("Admin", "Evaluator")),
):
    """Submit human feedback on an AI decision. Computes deviation automatically."""
    log_entry = db.query(models.AIDecisionLog).filter(
        models.AIDecisionLog.id == decision_id
    ).first()
    if not log_entry:
        raise HTTPException(status_code=404, detail="AI decision log not found")

    if payload.human_action not in ("accepted", "rejected", "modified"):
        raise HTTPException(
            status_code=400,
            detail="human_action must be one of: accepted, rejected, modified",
        )

    if payload.feedback_rating is not None and not (1 <= payload.feedback_rating <= 5):
        raise HTTPException(status_code=400, detail="feedback_rating must be between 1 and 5")

    log_entry.human_score = payload.human_score
    log_entry.human_action = payload.human_action
    log_entry.feedback_rating = payload.feedback_rating
    log_entry.feedback_comment = payload.feedback_comment
    log_entry.deviation = abs(log_entry.ai_score - payload.human_score)
    log_entry.resolved_at = datetime.utcnow()

    blockchain.create_audit_log(
        db=db,
        user_id=current_user.id,
        action="AI_FEEDBACK_SUBMITTED",
        entity_type="AIDecisionLog",
        entity_id=decision_id,
        details=f"Human action={payload.human_action}, deviation={log_entry.deviation:.2f} for decision #{decision_id}",
    )
    db.commit()
    db.refresh(log_entry)
    return log_entry


@router.get("/accuracy-report", response_model=schemas.AIAccuracyReport)
def accuracy_report(
    db: Session = Depends(get_db),
    current_user=Depends(auth.get_current_user),
):
    """Returns dynamic accuracy metrics computed from ALL logged AI decisions."""
    all_decisions = db.query(models.AIDecisionLog).all()
    total = len(all_decisions)

    resolved = [d for d in all_decisions if d.human_action is not None]
    resolved_count = len(resolved)

    accepted = [d for d in resolved if d.human_action == "accepted"]
    rejected = [d for d in resolved if d.human_action == "rejected"]
    modified = [d for d in resolved if d.human_action == "modified"]

    acceptance_rate = len(accepted) / resolved_count * 100 if resolved_count else 0.0
    rejection_rate = len(rejected) / resolved_count * 100 if resolved_count else 0.0
    modification_rate = len(modified) / resolved_count * 100 if resolved_count else 0.0

    deviations = [d.deviation for d in resolved if d.deviation is not None]
    avg_deviation = sum(deviations) / len(deviations) if deviations else None

    confidences = [d.ai_confidence for d in all_decisions if d.ai_confidence is not None]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    ratings = [d.feedback_rating for d in resolved if d.feedback_rating is not None]
    avg_feedback_rating = sum(ratings) / len(ratings) if ratings else None

    # --- Per-criteria accuracy breakdown ---
    criteria_map: dict = {}
    for d in resolved:
        key = d.criteria_id or 0
        if key not in criteria_map:
            criteria_map[key] = {"accepted": 0, "total": 0, "deviations": [], "criteria_id": d.criteria_id}
        criteria_map[key]["total"] += 1
        if d.human_action == "accepted":
            criteria_map[key]["accepted"] += 1
        if d.deviation is not None:
            criteria_map[key]["deviations"].append(d.deviation)

    # Fetch criteria names
    criteria_ids = [k for k in criteria_map if k != 0]
    criteria_names = {}
    if criteria_ids:
        rows = db.query(models.EvaluationCriteria).filter(
            models.EvaluationCriteria.id.in_(criteria_ids)
        ).all()
        criteria_names = {c.id: c.name for c in rows}

    per_criteria_accuracy = []
    for key, data in criteria_map.items():
        avg_dev = sum(data["deviations"]) / len(data["deviations"]) if data["deviations"] else 0
        per_criteria_accuracy.append({
            "criteria_id": data["criteria_id"],
            "criteria_name": criteria_names.get(key, "General / No Criteria"),
            "total_decisions": data["total"],
            "accepted": data["accepted"],
            "accuracy_pct": round(data["accepted"] / data["total"] * 100, 2) if data["total"] else 0,
            "avg_deviation": round(avg_dev, 2),
        })

    # --- Accuracy trend over time (monthly) ---
    monthly_map: dict = {}
    for d in resolved:
        ts = d.resolved_at or d.created_at
        if ts:
            month_key = ts.strftime("%Y-%m")
            if month_key not in monthly_map:
                monthly_map[month_key] = {"accepted": 0, "total": 0}
            monthly_map[month_key]["total"] += 1
            if d.human_action == "accepted":
                monthly_map[month_key]["accepted"] += 1

    accuracy_trend = []
    for month in sorted(monthly_map.keys()):
        data = monthly_map[month]
        accuracy_trend.append({
            "month": month,
            "total_decisions": data["total"],
            "accepted": data["accepted"],
            "accuracy_pct": round(data["accepted"] / data["total"] * 100, 2) if data["total"] else 0,
        })

    # --- Confidence calibration (binned predicted confidence vs actual accuracy) ---
    bins = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)]
    confidence_calibration = []
    for low, high in bins:
        bin_decisions = [
            d for d in resolved
            if d.ai_confidence is not None and low <= d.ai_confidence * 100 < high
        ]
        bin_accepted = [d for d in bin_decisions if d.human_action == "accepted"]
        confidence_calibration.append({
            "confidence_bin": f"{low}-{high}%",
            "total_decisions": len(bin_decisions),
            "actual_accuracy_pct": round(
                len(bin_accepted) / len(bin_decisions) * 100, 2
            ) if bin_decisions else 0,
            "predicted_confidence_avg": round(
                sum(d.ai_confidence * 100 for d in bin_decisions) / len(bin_decisions), 2
            ) if bin_decisions else 0,
        })

    return schemas.AIAccuracyReport(
        total_decisions=total,
        resolved_decisions=resolved_count,
        acceptance_rate=round(acceptance_rate, 2),
        rejection_rate=round(rejection_rate, 2),
        modification_rate=round(modification_rate, 2),
        accepted=len(accepted),
        rejected=len(rejected),
        modified=len(modified),
        avg_deviation=round(avg_deviation, 2) if avg_deviation is not None else None,
        avg_confidence=round(avg_confidence, 4),
        avg_feedback_rating=round(avg_feedback_rating, 2) if avg_feedback_rating is not None else None,
        per_criteria_accuracy=per_criteria_accuracy,
        accuracy_trend=accuracy_trend,
        confidence_calibration=confidence_calibration,
    )


@router.get("/decisions", response_model=List[schemas.AIDecisionLogOut])
def list_decisions(
    tender_id: Optional[int] = Query(None),
    bid_id: Optional[int] = Query(None),
    criteria_id: Optional[int] = Query(None),
    human_action: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(auth.get_current_user),
):
    """List all AI decisions with optional filters and pagination."""
    query = db.query(models.AIDecisionLog)

    if tender_id is not None:
        query = query.filter(models.AIDecisionLog.tender_id == tender_id)
    if bid_id is not None:
        query = query.filter(models.AIDecisionLog.bid_id == bid_id)
    if criteria_id is not None:
        query = query.filter(models.AIDecisionLog.criteria_id == criteria_id)
    if human_action is not None:
        query = query.filter(models.AIDecisionLog.human_action == human_action)

    query = query.order_by(models.AIDecisionLog.id.desc())
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()
    return results


@router.get("/decisions/{tender_id}")
def get_decisions_for_tender(
    tender_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(auth.get_current_user),
):
    """All AI decisions for a specific tender with vendor names and criteria names joined."""
    tender = db.query(models.Tender).filter(models.Tender.id == tender_id).first()
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")

    decisions = db.query(models.AIDecisionLog).filter(
        models.AIDecisionLog.tender_id == tender_id
    ).order_by(models.AIDecisionLog.id.desc()).all()

    # Collect all related bid/criteria IDs for batch lookup
    bid_ids = list({d.bid_id for d in decisions})
    criteria_ids = list({d.criteria_id for d in decisions if d.criteria_id is not None})

    # Batch-fetch vendors via bids
    vendor_map: dict = {}
    if bid_ids:
        bids = db.query(models.Bid).filter(models.Bid.id.in_(bid_ids)).all()
        vendor_ids = list({b.vendor_id for b in bids})
        vendors = db.query(models.Vendor).filter(models.Vendor.id.in_(vendor_ids)).all()
        v_name_map = {v.id: v.company_name for v in vendors}
        for b in bids:
            vendor_map[b.id] = v_name_map.get(b.vendor_id, "Unknown")

    # Batch-fetch criteria names
    criteria_name_map: dict = {}
    if criteria_ids:
        criteria_rows = db.query(models.EvaluationCriteria).filter(
            models.EvaluationCriteria.id.in_(criteria_ids)
        ).all()
        criteria_name_map = {c.id: c.name for c in criteria_rows}

    results = []
    for d in decisions:
        results.append({
            "id": d.id,
            "bid_id": d.bid_id,
            "criteria_id": d.criteria_id,
            "tender_id": d.tender_id,
            "vendor_name": vendor_map.get(d.bid_id, "Unknown"),
            "criteria_name": criteria_name_map.get(d.criteria_id, "General / No Criteria") if d.criteria_id else None,
            "ai_score": d.ai_score,
            "ai_confidence": d.ai_confidence,
            "ai_rationale": d.ai_rationale,
            "ai_model_version": d.ai_model_version,
            "human_score": d.human_score,
            "human_action": d.human_action,
            "deviation": d.deviation,
            "feedback_rating": d.feedback_rating,
            "feedback_comment": d.feedback_comment,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
        })

    return {
        "tender_id": tender_id,
        "tender_title": tender.title,
        "total_decisions": len(results),
        "decisions": results,
    }
