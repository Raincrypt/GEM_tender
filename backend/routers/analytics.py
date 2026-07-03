"""
GEM Analytics Router v1.0
Real-time KPI summaries, AI insights, tender lifecycle timelines.
All data sourced directly from the SQLite database.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
import statistics, hashlib

import models, auth
from database import get_db

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/kpi-summary")
def get_kpi_summary(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    """
    Real-time KPI strip:
    - Average procurement cycle time (indent → tender award)
    - System-wide savings rate
    - Active threat count
    - Vendor compliance rate
    """
    # ── Cycle time: indent created_at → tender awarded updated_at ────
    indents = db.query(models.Indent).filter(models.Indent.tender_id != None).all()
    cycle_days = []
    for indent in indents:
        if indent.created_at and indent.tender_id:
            tender = db.query(models.Tender).filter(models.Tender.id == indent.tender_id).first()
            if tender and tender.status == "Awarded" and tender.updated_at:
                diff = (tender.updated_at.replace(tzinfo=None) - indent.created_at.replace(tzinfo=None)).days
                if diff > 0:
                    cycle_days.append(diff)
    avg_cycle = round(statistics.mean(cycle_days), 1) if cycle_days else 0

    # ── Savings rate ──────────────────────────────────────────
    tenders = db.query(models.Tender).all()
    savings_pcts = []
    for t in tenders:
        if not t.estimated_value:
            continue
        q_bids = [b for b in t.bids if not b.is_disqualified and b.total_amount]
        if q_bids:
            l1 = min(b.total_amount for b in q_bids)
            savings_pcts.append((t.estimated_value - l1) / t.estimated_value * 100)
    avg_savings = round(statistics.mean(savings_pcts), 2) if savings_pcts else 0

    # ── Threat count ──────────────────────────────────────────
    bids = db.query(models.Bid).all()
    t_bid_map: dict = {}
    for b in bids:
        t_bid_map.setdefault(b.tender_id, []).append(b.total_amount or 0)

    threat_count = 0
    for t in tenders:
        amounts = sorted([a for a in t_bid_map.get(t.id, []) if a > 0])
        for i in range(len(amounts) - 1):
            if amounts[i] > 0 and (amounts[i + 1] - amounts[i]) / amounts[i] * 100 < 0.5:
                threat_count += 1
                break
        if t.estimated_value and amounts and min(amounts) < t.estimated_value * 0.5:
            threat_count += 1

    blacklisted_active = db.query(models.Vendor).filter(models.Vendor.is_blacklisted == True).count()
    threat_count += blacklisted_active

    # ── Vendor compliance ─────────────────────────────────────
    total_vendors = db.query(models.Vendor).count()
    compliant = db.query(models.Vendor).filter(models.Vendor.is_blacklisted == False).count()
    compliance_rate = round((compliant / total_vendors) * 100, 1) if total_vendors else 100.0

    # ── Tender funnel ─────────────────────────────────────────
    status_counts: dict = {}
    for t in tenders:
        status_counts[t.status] = status_counts.get(t.status, 0) + 1

    return {
        "avg_cycle_days": avg_cycle,
        "avg_savings_pct": avg_savings,
        "active_threats": threat_count,
        "vendor_compliance_pct": compliance_rate,
        "total_vendors": total_vendors,
        "tender_funnel": {
            "Draft": status_counts.get("Draft", 0),
            "Published": status_counts.get("Published", 0),
            "Under Evaluation": status_counts.get("Under Evaluation", 0),
            "Awarded": status_counts.get("Awarded", 0),
            "Cancelled": status_counts.get("Cancelled", 0),
            "Closed": status_counts.get("Closed", 0),
        },
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/tender-timeline/{tender_id}")
def get_tender_timeline(
    tender_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(auth.get_current_user),
):
    """
    Structured lifecycle timeline for a specific tender.
    Pulls real audit log entries and interpolates key milestones.
    """
    tender = db.query(models.Tender).filter(models.Tender.id == tender_id).first()
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")

    # Audit logs for this tender
    logs = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.entity_id == tender_id, models.AuditLog.entity_type == "Tender")
        .order_by(models.AuditLog.timestamp.asc())
        .all()
    )

    stages = []

    # Stage 1: Created
    if tender.created_at:
        stages.append({
            "stage": "Tender Created",
            "status": "completed",
            "timestamp": tender.created_at.replace(tzinfo=None).isoformat(),
            "detail": f"Tender {tender.bid_number} created by department.",
            "icon": "file-plus",
        })

    # Stage 2: Published
    if tender.published_date or tender.status not in ("Draft",):
        stages.append({
            "stage": "Published",
            "status": "completed" if tender.status != "Draft" else "pending",
            "timestamp": (tender.published_date or tender.created_at).replace(tzinfo=None).isoformat(),
            "detail": f"Tender published. Closing: {tender.closing_date.strftime('%d %b %Y') if tender.closing_date else 'N/A'}.",
            "icon": "send",
        })

    # Stage 3: Bid submission — count bids
    total_bids = db.query(models.Bid).filter(models.Bid.tender_id == tender_id).count()
    if total_bids > 0:
        last_bid = db.query(models.Bid).filter(
            models.Bid.tender_id == tender_id
        ).order_by(models.Bid.submitted_at.desc()).first()
        stages.append({
            "stage": "Bids Received",
            "status": "completed",
            "timestamp": last_bid.submitted_at.replace(tzinfo=None).isoformat() if last_bid and last_bid.submitted_at else "",
            "detail": f"{total_bids} bid(s) received.",
            "icon": "inbox",
        })

    # Stage 4: Financial Opened
    if getattr(tender, "is_financial_opened", False):
        fin_log = next((l for l in logs if "OPEN_FINANCIAL" in (l.action or "")), None)
        stages.append({
            "stage": "Financial Bids Opened",
            "status": "completed",
            "timestamp": fin_log.timestamp.replace(tzinfo=None).isoformat() if fin_log and fin_log.timestamp else "",
            "detail": "Financial bids unlocked for comparative evaluation.",
            "icon": "lock-open",
        })

    # Stage 5: Evaluation
    eval_bids = db.query(models.Bid).filter(
        models.Bid.tender_id == tender_id, models.Bid.status == "Evaluated"
    ).count()
    if eval_bids > 0:
        stages.append({
            "stage": "Technical Evaluation",
            "status": "completed",
            "timestamp": "",
            "detail": f"{eval_bids} bid(s) evaluated with composite scoring.",
            "icon": "bar-chart-2",
        })

    # Stage 6: Negotiation
    neg_log = next((l for l in logs if "NEGOTIATION" in (l.action or "")), None)
    if neg_log:
        stages.append({
            "stage": "AI Swarm Negotiation",
            "status": "completed",
            "timestamp": neg_log.timestamp.replace(tzinfo=None).isoformat() if neg_log.timestamp else "",
            "detail": neg_log.details or "Negotiation completed.",
            "icon": "git-merge",
        })

    # Stage 7: Award
    award_log = next((l for l in logs if "AWARD" in (l.action or "")), None)
    if tender.status == "Awarded" and award_log:
        stages.append({
            "stage": "Contract Awarded",
            "status": "completed",
            "timestamp": award_log.timestamp.replace(tzinfo=None).isoformat() if award_log.timestamp else "",
            "detail": award_log.details or "Tender awarded.",
            "icon": "award",
        })

    # Stage 8: PO
    po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.tender_id == tender_id).first()
    if po:
        stages.append({
            "stage": "Purchase Order Issued",
            "status": "completed",
            "timestamp": po.created_at.replace(tzinfo=None).isoformat() if po and po.created_at else "",
            "detail": f"PO {po.po_number} issued for ₹{po.total_po_value:,.2f}.",
            "icon": "file-text",
        })

    return {
        "tender": {
            "id": tender.id,
            "bid_number": tender.bid_number,
            "title": tender.title,
            "status": tender.status,
        },
        "stages": stages,
        "total_stages": len(stages),
        "current_status": tender.status,
    }


@router.get("/ai-insights")
def get_ai_insights(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    """
    Aggregated AI-generated insights across all active tenders.
    Fully deterministic — derived from real DB queries.
    """
    tenders = db.query(models.Tender).filter(
        models.Tender.status.in_(["Published", "Under Evaluation"])
    ).all()
    all_bids = db.query(models.Bid).all()
    all_vendors = db.query(models.Vendor).all()

    t_bid_map: dict = {}
    for b in all_bids:
        t_bid_map.setdefault(b.tender_id, []).append(b)

    insights = []

    # Insight 1: Expiring tenders
    now = datetime.utcnow()
    expiring = [
        t for t in tenders
        if t.closing_date and 0 < (t.closing_date.replace(tzinfo=None) - now).days <= 3
    ]
    if expiring:
        insights.append({
            "id": "EXPIRING_TENDERS",
            "severity": "HIGH",
            "title": f"{len(expiring)} Tender(s) Closing in 72 Hours",
            "detail": f"Tenders: {', '.join(t.bid_number for t in expiring[:3])}. Ensure bid evaluations are initiated promptly.",
            "icon": "clock",
            "color": "#f59e0b",
            "action": "Review Tenders",
            "action_url": "tenders.html",
        })

    # Insight 2: Cartel patterns
    cartel_tenders = []
    for t in tenders:
        amounts = sorted([b.total_amount for b in t_bid_map.get(t.id, []) if b.total_amount and not b.is_disqualified])
        for i in range(len(amounts) - 1):
            if amounts[i] > 0 and (amounts[i + 1] - amounts[i]) / amounts[i] * 100 < 0.5:
                cartel_tenders.append(t.bid_number)
                break
    if cartel_tenders:
        insights.append({
            "id": "CARTEL_DETECTED",
            "severity": "CRITICAL",
            "title": f"Cartel Pattern in {len(cartel_tenders)} Tender(s)",
            "detail": f"Bid clustering (<0.5% spread) detected in: {', '.join(cartel_tenders[:3])}. Possible pre-auction price fixing.",
            "icon": "alert-triangle",
            "color": "#ef4444",
            "action": "View Cartel Intel",
            "action_url": "cartel.html",
        })

    # Insight 3: Blacklisted vendor active
    blacklisted_with_bids = []
    for v in all_vendors:
        if v.is_blacklisted:
            vbids = [b for b in all_bids if b.vendor_id == v.id and not b.is_disqualified]
            if vbids:
                blacklisted_with_bids.append(v.company_name)
    if blacklisted_with_bids:
        insights.append({
            "id": "BLACKLISTED_ACTIVE",
            "severity": "CRITICAL",
            "title": f"{len(blacklisted_with_bids)} Blacklisted Vendor(s) Have Active Bids",
            "detail": f"Vendors: {', '.join(blacklisted_with_bids[:3])}. Immediate disqualification required.",
            "icon": "shield-off",
            "color": "#ef4444",
            "action": "Review Vendors",
            "action_url": "vendors.html",
        })

    # Insight 4: Low competition tenders
    low_comp = [t for t in tenders if len(t_bid_map.get(t.id, [])) < 3]
    if low_comp:
        insights.append({
            "id": "LOW_COMPETITION",
            "severity": "MODERATE",
            "title": f"{len(low_comp)} Tender(s) with Low Competition",
            "detail": f"Less than 3 bids received. May indicate restricted market access or tight specifications.",
            "icon": "users",
            "color": "#8b5cf6",
            "action": "Analyse Bids",
            "action_url": "bid_analysis.html",
        })

    # Insight 5: Unevaluated tenders
    under_eval_no_scores = []
    for t in tenders:
        if t.status == "Under Evaluation":
            unscored = [b for b in t_bid_map.get(t.id, []) if b.status == "Submitted"]
            if unscored:
                under_eval_no_scores.append(t.bid_number)
    if under_eval_no_scores:
        insights.append({
            "id": "PENDING_EVALUATION",
            "severity": "MODERATE",
            "title": f"{len(under_eval_no_scores)} Tender(s) Pending Evaluation",
            "detail": f"Tenders with unevaluated bids: {', '.join(under_eval_no_scores[:3])}.",
            "icon": "clipboard-list",
            "color": "#3b82f6",
            "action": "Go to Evaluation",
            "action_url": "evaluation.html",
        })

    # Sort: CRITICAL first
    priority = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}
    insights.sort(key=lambda x: priority.get(x["severity"], 4))

    # If no insights, emit a positive status
    if not insights:
        insights.append({
            "id": "ALL_CLEAR",
            "severity": "LOW",
            "title": "System Operating Normally",
            "detail": "No critical anomalies detected. All procurement operations are within acceptable parameters.",
            "icon": "check-circle",
            "color": "#10b981",
            "action": "View Dashboard",
            "action_url": "dashboard.html",
        })

    return {
        "insights": insights,
        "total_insights": len(insights),
        "critical_count": len([i for i in insights if i["severity"] == "CRITICAL"]),
        "generated_at": datetime.utcnow().isoformat(),
    }
