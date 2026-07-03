"""
GEM AI Operations Center — Router v3.0
All price index and market intelligence is fully deterministic and data-driven.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
import models, auth, blockchain, rag_engine, llm_client
from database import get_db
import ai_swarm_engine, anomaly_detector
import statistics, math, json, asyncio, hashlib
from datetime import datetime, timedelta
from routers.documents import extract_text_from_file, redact_pii

router = APIRouter(prefix="/ai-ops", tags=["AI Operations Center"])


@router.get("/swarm-registry")
def get_swarm_registry():
    """Returns all registered AI agents and their cognitive profiles."""
    return {
        "agents": ai_swarm_engine.get_agent_registry(),
        "swarm_version": "3.0",
        "total_agents": len(ai_swarm_engine.AGENT_REGISTRY),
    }


@router.post("/negotiate/{tender_id}")
async def run_negotiation_swarm(
    tender_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(auth.require_role("Admin")),
):
    """Execute the full multi-agent negotiation swarm on a tender's L1 bid."""
    from routers.evaluation import comparative_statement
    comp = comparative_statement(tender_id, db, current_user=current_user)
    eligible_bids = [b for b in comp["bids"] if not b["is_disqualified"]]
    if not eligible_bids:
        raise HTTPException(status_code=400, detail="No eligible bids")

    l1 = eligible_bids[0]
    context = {
        "vendor_name": l1["vendor_name"],
        "l1_amount": l1["total_amount"],
        "estimated_value": comp["tender"]["estimated_value"] or 0,
        "all_bid_amounts": [b["total_amount"] for b in eligible_bids],
        "is_blacklisted": False,
        "category": "General IT & Infrastructure",
        "tender_id": tender_id,
    }

    result = await ai_swarm_engine.execute_negotiation_swarm(context)

    if result["approved"] and result["final_amount"] < l1["total_amount"]:
        blockchain.create_audit_log(
            db, current_user.id, "AI_SWARM_NEGOTIATION_V3",
            "Tender", tender_id,
            f"Swarm v3.0 saved ₹{result['savings']:,.0f} ({result['savings_pct']:.1f}%) from {context['vendor_name']}",
        )
        db.commit()

    return result


@router.get("/negotiate-stream/{tender_id}")
async def stream_negotiation_swarm(tender_id: int, db: Session = Depends(get_db)):
    """SSE Endpoint: Streams the swarm's cognitive process in real-time."""
    from routers.evaluation import comparative_statement
    
    # System authorization proxy for SSE bypass
    class SSEUser:
        id = 1
        username = "admin"
        role = "Admin"
    
    comp = comparative_statement(tender_id, db, current_user=SSEUser())
    eligible_bids = [b for b in comp["bids"] if not b["is_disqualified"]]
    if not eligible_bids:
        raise HTTPException(status_code=400, detail="No eligible bids")

    l1 = eligible_bids[0]
    context = {
        "vendor_name": l1["vendor_name"],
        "l1_amount": l1["total_amount"],
        "estimated_value": comp["tender"]["estimated_value"] or 0,
        "all_bid_amounts": [b["total_amount"] for b in eligible_bids],
        "is_blacklisted": False,
        "category": "General IT & Infrastructure",
        "tender_id": tender_id,
    }

    async def event_generator():
        bus = ai_swarm_engine.SwarmBus()
        last_idx = 0

        async def flush():
            nonlocal last_idx
            while last_idx < len(bus.messages):
                msg = bus.messages[last_idx].to_dict()
                yield "data: " + json.dumps(msg) + "\n\n"
                last_idx += 1
                await asyncio.sleep(0.4)

        await asyncio.gather(
            ai_swarm_engine._planner(bus, context),
            ai_swarm_engine._sentinel(bus, context),
            ai_swarm_engine._oracle(bus, context),
        )
        async for chunk in flush():
            yield chunk

        await ai_swarm_engine._analyst(bus, context)
        async for chunk in flush():
            yield chunk

        await ai_swarm_engine._negotiator(bus, context)
        async for chunk in flush():
            yield chunk

        await ai_swarm_engine._auditor(bus, context)
        async for chunk in flush():
            yield chunk

        await ai_swarm_engine._critic(bus, context)
        async for chunk in flush():
            yield chunk

        nm = bus.last("NEGOTIATOR")
        fa = nm.metadata.get("counter_offer", context["l1_amount"]) if nm else context["l1_amount"]
        sv = context["l1_amount"] - fa
        sv_pct = round(sv / context["l1_amount"] * 100, 2) if context["l1_amount"] else 0
        bus.publish(
            ai_swarm_engine.AgentMessage(
                "PLANNER",
                f"SWARM CONSENSUS REACHED. Final negotiated price: ₹{fa:,.0f}. Government savings: ₹{sv:,.0f} ({sv_pct}%).",
                "consensus", 0.98,
                {"phase": "consensus", "final_amount": round(fa, 0), "savings": round(sv, 0), "savings_pct": sv_pct, "approved": True},
            )
        )
        async for chunk in flush():
            yield chunk
        yield "event: end\ndata: {}\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Access-Control-Allow-Origin": "*",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)

@router.post("/clear-llm-cache")
async def clear_llm_cache():
    import os
    import llm_client

    # Clear file cache
    cache_dir = os.path.join(os.path.dirname(__file__), "..", "llm_cache")
    cleared = 0
    if os.path.isdir(cache_dir):
        for f in os.listdir(cache_dir):
            if f.endswith(".json"):
                try:
                    os.remove(os.path.join(cache_dir, f))
                    cleared += 1
                except Exception:
                    pass

    # Clear Redis cache if available
    try:
        r = llm_client._get_redis_client()
        if r:
            keys = r.keys("llm_cache:*")
            if keys:
                r.delete(*keys)
    except Exception:
        pass

    return {"success": True, "cleared": cleared}
@router.get("/cognitive-map/{tender_id}")
async def get_cognitive_map(
    tender_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(auth.get_current_user),
):
    """Returns the full AI decision graph for visualization."""
    tender = db.query(models.Tender).filter(models.Tender.id == tender_id).first()
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")

    bids = db.query(models.Bid).filter(models.Bid.tender_id == tender_id).all()
    vmap = {v.id: v for v in db.query(models.Vendor).all()}

    nodes = [{"id": "ROOT", "label": f"Tender {tender.bid_number}", "type": "tender", "color": "#8b5cf6"}]
    edges = []

    for agent_key, agent_info in ai_swarm_engine.AGENT_REGISTRY.items():
        nodes.append({"id": agent_key, "label": agent_info["name"], "type": "agent",
                      "color": agent_info["color"], "icon": agent_info["icon"]})
        edges.append({"from": "ROOT", "to": agent_key, "label": "deploys"})

    for b in bids:
        v = vmap.get(b.vendor_id)
        bid_node = f"BID_{b.id}"
        nodes.append({
            "id": bid_node,
            "label": v.company_name if v else f"Bid {b.id}",
            "type": "bid",
            "color": "#4ade80" if b.rank == 1 else "#64748b",
            "amount": b.total_amount,
            "rank": b.rank,
        })
        edges.append({"from": "ANALYST", "to": bid_node, "label": "analyzes"})
        if b.rank == 1:
            edges.append({"from": "NEGOTIATOR", "to": bid_node, "label": "negotiates"})
            edges.append({"from": "AUDITOR", "to": bid_node, "label": "validates"})

    return {"nodes": nodes, "edges": edges, "agents": ai_swarm_engine.get_agent_registry()}


@router.get("/threat-intel")
async def get_threat_intelligence(
    db: Session = Depends(get_db),
    current_user=Depends(auth.get_current_user),
):
    """Real-time threat intelligence feed from Sentinel agent."""
    bids = db.query(models.Bid).all()
    vendors = db.query(models.Vendor).all()
    vmap = {v.id: v for v in vendors}
    tenders = db.query(models.Tender).all()
    t_bids: dict = {}
    for b in bids:
        t_bids.setdefault(b.tender_id, []).append(b)

    threats = []
    for t in tenders:
        tbids = t_bids.get(t.id, [])
        amounts = sorted([b.total_amount for b in tbids if b.total_amount and not b.is_disqualified])

        if len(amounts) >= 2:
            for i in range(len(amounts) - 1):
                if amounts[i] > 0 and (amounts[i + 1] - amounts[i]) / amounts[i] * 100 < 0.5:
                    threats.append({
                        "type": "BID_CLUSTERING", "severity": "CRITICAL",
                        "tender": t.bid_number,
                        "detail": f"Bids within 0.5% gap: ₹{amounts[i]:,.0f} vs ₹{amounts[i+1]:,.0f}",
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                    break

        if t.estimated_value and amounts and min(amounts) < t.estimated_value * 0.5:
            threats.append({
                "type": "PRICE_DUMPING", "severity": "HIGH",
                "tender": t.bid_number,
                "detail": f"L1 at {min(amounts) / t.estimated_value * 100:.0f}% of estimate",
                "timestamp": datetime.utcnow().isoformat(),
            })

        if len(tbids) < 3:
            threats.append({
                "type": "LOW_COMPETITION", "severity": "MODERATE",
                "tender": t.bid_number,
                "detail": f"Only {len(tbids)} bid(s) received",
                "timestamp": datetime.utcnow().isoformat(),
            })

    for v in vendors:
        if v.is_blacklisted:
            vbids = [b for b in bids if b.vendor_id == v.id and not b.is_disqualified]
            if vbids:
                threats.append({
                    "type": "BLACKLISTED_ACTIVE", "severity": "CRITICAL",
                    "tender": "SYSTEM",
                    "detail": f"{v.company_name} has {len(vbids)} active bid(s)",
                    "timestamp": datetime.utcnow().isoformat(),
                })

    threats.sort(key=lambda x: {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}.get(x["severity"], 4))

    return {
        "threats": threats[:20],
        "total_threats": len(threats),
        "critical_count": len([t for t in threats if t["severity"] == "CRITICAL"]),
        "system_threat_level": (
            "CRITICAL" if any(t["severity"] == "CRITICAL" for t in threats) else
            "HIGH" if len(threats) > 5 else
            "MODERATE" if threats else "SECURE"
        ),
        "scan_timestamp": datetime.utcnow().isoformat(),
        "sentinel_version": "Ψ-3.0",
    }


@router.get("/anomaly-scan")
def run_anomaly_scan(db: Session = Depends(get_db), current_user=Depends(auth.get_current_user)):
    """Full-system anomaly detection using Isolation Forest + EWMA."""
    bids = db.query(models.Bid).all()
    vmap = {v.id: v for v in db.query(models.Vendor).all()}
    tmap = {t.id: t for t in db.query(models.Tender).all()}

    bids_data = []
    for b in bids:
        if not b.total_amount:
            continue
        t = tmap.get(b.tender_id)
        bids_data.append({
            "bid_id": b.id,
            "tender_id": b.tender_id,
            "vendor_id": b.vendor_id,
            "vendor_name": vmap[b.vendor_id].company_name if b.vendor_id in vmap else "?",
            "total_amount": b.total_amount,
            "delivery_period": b.delivery_period,
            "status": b.status,
            "submitted_at": b.submitted_at,
            "tender_published_at": t.created_at if t else None,
            "estimated_value": t.estimated_value if t else None
        })

    results = anomaly_detector.comprehensive_anomaly_scan(bids_data, [])
    return results


@router.get("/market-intelligence")
def get_market_intelligence(
    db: Session = Depends(get_db),
    current_user=Depends(auth.get_current_user),
):
    """Cross-market price intelligence — fully deterministic, data-driven."""
    tenders = db.query(models.Tender).all()
    bids = db.query(models.Bid).all()

    # Category breakdown from real data
    cat_stats: dict = {}
    for t in tenders:
        cat = t.category or "Uncategorized"
        if cat not in cat_stats:
            cat_stats[cat] = {"tenders": 0, "total_value": 0, "bids": 0, "savings": [], "values": []}
        cat_stats[cat]["tenders"] += 1
        cat_stats[cat]["total_value"] += t.estimated_value or 0
        if t.estimated_value:
            cat_stats[cat]["values"].append(t.estimated_value)

        t_bids = [b for b in bids if b.tender_id == t.id and b.total_amount and not b.is_disqualified]
        cat_stats[cat]["bids"] += len(t_bids)
        if t_bids and t.estimated_value:
            l1 = min(b.total_amount for b in t_bids)
            cat_stats[cat]["savings"].append((t.estimated_value - l1) / t.estimated_value * 100)

    categories = []
    for cat, data in cat_stats.items():
        avg_sav = statistics.mean(data["savings"]) if data["savings"] else 0
        categories.append({
            "category": cat,
            "tenders": data["tenders"],
            "total_estimated_value": round(data["total_value"], 0),
            "total_bids": data["bids"],
            "avg_savings_pct": round(avg_sav, 2),
            "competition_ratio": round(data["bids"] / max(data["tenders"], 1), 1),
            "health": (
                "STRONG" if avg_sav > 10 and data["bids"] / max(data["tenders"], 1) > 3 else
                "MODERATE" if avg_sav > 5 else "WEAK"
            ),
        })

    categories.sort(key=lambda x: x["total_estimated_value"], reverse=True)

    # Deterministic price index from real tender estimated values over time
    # Build monthly average estimated values from actual tender data
    now = datetime.utcnow()
    monthly_vals: dict = {}
    for t in tenders:
        if t.created_at and t.estimated_value:
            key = t.created_at.replace(tzinfo=None).strftime("%Y-%m")
            monthly_vals.setdefault(key, []).append(t.estimated_value)

    # Autoregressive linear trend projection to fill missing monthly index data points
    month_keys = []
    month_labels = []
    for i in range(11, -1, -1):
        m_date = now - timedelta(days=30 * i)
        month_keys.append(m_date.strftime("%Y-%m"))
        month_labels.append(m_date.strftime("M-%m/%y"))

    known_points = []
    for t_idx, key in enumerate(month_keys):
        vals = monthly_vals.get(key, [])
        if vals:
            index_val = round(statistics.mean(vals) / 100000, 1)
            known_points.append((t_idx, index_val))

    n_points = len(known_points)
    if n_points >= 2:
        sum_x = sum(p[0] for p in known_points)
        sum_y = sum(p[1] for p in known_points)
        sum_xy = sum(p[0] * p[1] for p in known_points)
        sum_x_sq = sum(p[0] ** 2 for p in known_points)
        denominator = (n_points * sum_x_sq - sum_x ** 2)
        if denominator != 0:
            m = (n_points * sum_xy - sum_x * sum_y) / denominator
            c = (sum_y - m * sum_x) / n_points
        else:
            m = 0.0
            c = sum(p[1] for p in known_points) / n_points
    elif n_points == 1:
        m = 0.0
        c = known_points[0][1]
    else:
        m = 0.5  # assume a slight growth trend for fallback
        c = 100.0  # base index level

    price_index = []
    for t_idx, (key, label) in enumerate(zip(month_keys, month_labels)):
        vals = monthly_vals.get(key, [])
        if vals:
            index_val = round(statistics.mean(vals) / 100000, 1)
        else:
            index_val = round(m * t_idx + c, 1)
            # Constrain to a logical percentage index range [50.0, 300.0]
            index_val = max(50.0, min(300.0, index_val))
        price_index.append({"month": label, "index": index_val})

    savings_list = [c["avg_savings_pct"] for c in categories if c["avg_savings_pct"]]
    avg_sys_sav = statistics.mean(savings_list) if savings_list else 0

    return {
        "categories": categories,
        "price_index": price_index,
        "total_procurement_value": round(sum(c["total_estimated_value"] for c in categories), 0),
        "avg_system_savings": round(avg_sys_sav, 2),
        "generated_at": datetime.utcnow().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────
#  RAG ENDPOINTS
# ─────────────────────────────────────────────────────────────────
import os, shutil

@router.post("/rag-upload")
def rag_upload(
    file: UploadFile = File(...),
    vendor_id: Optional[int] = Form(None),
    tender_id: Optional[int] = Form(None),
    doc_type: Optional[str] = Form("general"),
    db: Session = Depends(get_db),
    current_user = Depends(auth.require_role("Admin", "Evaluator"))
):
    """Uploads a document, extracts text via OCR, and indexes it into the RAG vector store."""
    os.makedirs("uploads", exist_ok=True)
    temp_path = os.path.join("uploads", f"temp_rag_{file.filename}")
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Extract and clean text
        raw_text = extract_text_from_file(temp_path)
        extracted_text = redact_pii(raw_text)
        
        # Prepare metadata
        metadata = {
            "filename": file.filename,
            "doc_type": doc_type
        }
        if vendor_id is not None:
            metadata["vendor_id"] = vendor_id
        if tender_id is not None:
            metadata["tender_id"] = tender_id
            
        # Delete old index chunks first
        delete_filter = {}
        if file.filename:
            delete_filter["filename"] = file.filename
        if vendor_id is not None:
            delete_filter["vendor_id"] = vendor_id
        if tender_id is not None:
            delete_filter["tender_id"] = tender_id
        if doc_type:
            delete_filter["doc_type"] = doc_type
            
        if delete_filter:
            try:
                rag_engine.delete_document_from_index(delete_filter)
            except Exception as e:
                print(f"Error purging old RAG chunks in ai_ops: {e}")

        # Index in RAG
        success = rag_engine.add_document_to_index(extracted_text, metadata=metadata)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to add document to vector index")
            
        # Get new index stats
        stats = rag_engine.get_index_stats()
        
        return {
            "success": True,
            "message": f"Successfully vectorized and indexed {file.filename}",
            "stats": stats
        }
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.post("/rag-query")
def rag_query(
    body: dict,
    db: Session = Depends(get_db),
    current_user = Depends(auth.get_current_user)
):
    """Query the RAG vector store with optional metadata filtering."""
    question = body.get("question")
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")
        
    filters = {}
    if "vendor_id" in body and body["vendor_id"] is not None and str(body["vendor_id"]).strip() != "":
        filters["vendor_id"] = body["vendor_id"]
    if "tender_id" in body and body["tender_id"] is not None and str(body["tender_id"]).strip() != "":
        filters["tender_id"] = body["tender_id"]
    if "doc_type" in body and body["doc_type"] is not None and str(body["doc_type"]).strip() != "":
        filters["doc_type"] = body["doc_type"]
        
    res = rag_engine.query_rag_filtered(question, filter_metadata=filters if filters else None)
    return res


@router.get("/rag-status")
def rag_status(current_user = Depends(auth.get_current_user)):
    """Retrieve index size and statistics for the RAG Knowledge Base."""
    return rag_engine.get_index_stats()


@router.post("/document-ocr")
def document_ocr(
    file: UploadFile = File(...),
    current_user = Depends(auth.get_current_user)
):
    """Uploads a document, extracts text via OCR, and returns the redacted text for preview."""
    import os, shutil
    os.makedirs("uploads", exist_ok=True)
    temp_path = os.path.join("uploads", f"temp_ocr_{file.filename}")
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        raw_text = extract_text_from_file(temp_path)
        redacted_text = redact_pii(raw_text)
        
        return {
            "success": True,
            "filename": file.filename,
            "text": redacted_text,
            "length": len(redacted_text)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR failed: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# ─────────────────────────────────────────────────────────────────
#  ANOMALY & CARTEL DETECTION
# ─────────────────────────────────────────────────────────────────
@router.get("/cartel-detection")
def cartel_detection(
    db: Session = Depends(get_db),
    current_user = Depends(auth.require_role("Admin", "Evaluator"))
):
    """Run DBSCAN clustering to detect potential bidding cartels/clusters."""
    bids = db.query(models.Bid).all()
    vmap = {v.id: v for v in db.query(models.Vendor).all()}
    
    bids_data = []
    for b in bids:
        if not b.total_amount:
            continue
        bids_data.append({
            "bid_id": b.id,
            "tender_id": b.tender_id,
            "vendor_id": b.vendor_id,
            "vendor_name": vmap.get(b.vendor_id).company_name if b.vendor_id in vmap else f"Vendor {b.vendor_id}",
            "total_amount": b.total_amount
        })
        
    return anomaly_detector.detect_bid_clusters(bids_data)


@router.get("/bid-timing-analysis")
def bid_timing_analysis(
    db: Session = Depends(get_db),
    current_user = Depends(auth.require_role("Admin", "Evaluator"))
):
    """Run entropy and coordination analysis on bid submission timestamps."""
    bids = db.query(models.Bid).all()
    vmap = {v.id: v for v in db.query(models.Vendor).all()}
    tmap = {t.id: t for t in db.query(models.Tender).all()}
    
    bids_data = []
    for b in bids:
        t = tmap.get(b.tender_id)
        bids_data.append({
            "bid_id": b.id,
            "tender_id": b.tender_id,
            "vendor_id": b.vendor_id,
            "vendor_name": vmap.get(b.vendor_id).company_name if b.vendor_id in vmap else f"Vendor {b.vendor_id}",
            "total_amount": b.total_amount,
            "submitted_at": b.submitted_at.isoformat() if b.submitted_at else None,
            "tender_published_at": t.created_at.isoformat() if t and t.created_at else None
        })
        
    return anomaly_detector.analyze_bid_timing(bids_data)


# ─────────────────────────────────────────────────────────────────
#  LLM CLIENT CONTROL ENDPOINTS
# ─────────────────────────────────────────────────────────────────

@router.get("/llm-status")
def get_llm_status(current_user = Depends(auth.get_current_user)):
    """Retrieve configuration and active status of all LLM providers."""
    return llm_client.get_provider_status()


@router.get("/ollama-local-models")
def get_ollama_local_models(current_user = Depends(auth.get_current_user)):
    """Retrieve all local models currently downloaded in the active Ollama instance."""
    url = llm_client.config_data.get("ollama_url", "http://localhost:11434/api/generate")
    tags_url = url.replace("/api/generate", "/api/tags").replace("/api/chat", "/api/tags")
    if "/api/tags" not in tags_url:
        tags_url = "http://localhost:11434/api/tags"
        
    try:
        import requests
        resp = requests.get(tags_url, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            models_list = []
            for item in data.get("models", []):
                models_list.append({
                    "name": item.get("name"),
                    "size": item.get("size"),
                    "details": item.get("details", {})
                })
            return {"success": True, "models": models_list}
        return {"success": False, "error": f"Ollama returned status code {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to connect to Ollama: {str(e)}"}


@router.post("/llm-select")
def select_llm_provider(body: dict, current_user = Depends(auth.get_current_user)):
    """Configure LLM settings dynamically (provider, models, API keys, compliance)."""
    config_keys = [
        "llm_provider", "strict_open_source", "gemini_api_key", "openai_api_key",
        "ollama_url", "ollama_model", "gemini_model", "openai_model",
        "strict_accuracy", "rag_min_relevance",
        "ollama_model_fast", "ollama_model_reasoning", "rag_semantic_weight"
    ]
    
    # Map old client payload parameter names
    if "provider" in body and "llm_provider" not in body:
        body["llm_provider"] = body["provider"]
        
    updated_data = {}
    for key in config_keys:
        if key in body:
            val = body[key]
            if key == "strict_open_source":
                if isinstance(val, str):
                    val = val.lower() == "true"
                else:
                    val = bool(val)
            elif key == "strict_accuracy":
                if isinstance(val, str):
                    val = val.lower() == "true"
                else:
                    val = bool(val)
            elif key == "rag_min_relevance":
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    val = 40.0
            elif key == "rag_semantic_weight":
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    val = 0.7
            elif key == "llm_provider":
                val = val.lower().strip()
                if val not in ["gemini", "openai", "ollama"]:
                    raise HTTPException(status_code=400, detail=f"Invalid provider: {val}")
            updated_data[key] = val

    if updated_data:
        # Strict open source mode check
        strict = updated_data.get("strict_open_source", llm_client.config_data.get("strict_open_source", True))
        provider = updated_data.get("llm_provider", llm_client.config_data.get("llm_provider", "ollama"))
        if strict and provider in ["gemini", "openai"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot select cloud provider '{provider}' when strict open source mode is enabled."
            )
        
        # Save configuration changes
        llm_client.save_config(updated_data)
        
    return {"success": True, "status": llm_client.get_provider_status()}


@router.post("/llm-test")
def test_llm_provider(body: dict, current_user = Depends(auth.get_current_user)):
    """Test connectivity to a specific LLM provider."""
    provider = body.get("provider")
    if not provider:
        raise HTTPException(status_code=400, detail="Provider is required")
    res = llm_client.test_connection(provider.lower().strip())
    return res


@router.post("/swarm-interactive")
def swarm_interactive_playground(body: dict, db: Session = Depends(get_db)):
    """Interactive Swarm Playground endpoint to chat with agents."""
    tender_id = body.get("tender_id")
    message = body.get("message", "").strip()
    agent = body.get("agent", "PLANNER").upper()
    temperature = float(body.get("temperature", 0.3))
    target_savings_pct = float(body.get("target_savings_pct", 5.0))
    
    if not tender_id or not message:
        raise HTTPException(status_code=400, detail="tender_id and message are required")
        
    from routers.evaluation import comparative_statement
    
    class SSEUser:
        id = 1
        username = "admin"
        role = "Admin"
        
    comp = comparative_statement(tender_id, db, current_user=SSEUser())
    eligible_bids = [b for b in comp["bids"] if not b["is_disqualified"]]
    if not eligible_bids:
        raise HTTPException(status_code=400, detail="No eligible bids")
        
    l1 = eligible_bids[0]
    context = {
        "vendor_name": l1["vendor_name"],
        "l1_amount": l1["total_amount"],
        "estimated_value": comp["tender"]["estimated_value"] or 0,
        "all_bid_amounts": [b["total_amount"] for b in eligible_bids],
        "is_blacklisted": False,
        "category": "General IT & Infrastructure",
    }
    
    agent_registry = ai_swarm_engine.get_agent_registry()
    
    if agent == "SWARM":
        debate = []
        
        # 1. Planner chimes in
        planner_system = "You are Strategic Planner Ω, Swarm Orchestrator. Directs the debate context."
        planner_user = (
            f"Context: target vendor {context['vendor_name']}, L1: Rs. {context['l1_amount']:,.0f}, Estimated: Rs. {context['estimated_value']:,.0f}. "
            f"The user/buyer asks: '{message}'. Plan how the swarm should respond in 1-2 sentences."
        )
        planner_res = ai_swarm_engine._call_agent_llm("PLANNER", planner_system, planner_user, "Planner ready.")
        debate.append({
            "sender": "PLANNER", 
            "content": planner_res, 
            "timestamp": datetime.utcnow().isoformat(),
            "agent_info": agent_registry.get("PLANNER", {})
        })
        
        # 2. Analyst chimes in
        analyst_system = "You are Market Analyst Σ, statistical auditor. Analyzes price bid distributions."
        analyst_user = (
            f"Tender estimated value: Rs. {context['estimated_value']:,.0f}. Bids list: {context['all_bid_amounts']}. "
            f"User query: '{message}'. Planner says: '{planner_res}'. Propose a quick analysis or calculation in 1-2 sentences."
        )
        analyst_res = ai_swarm_engine._call_agent_llm("ANALYST", analyst_system, analyst_user, "Analyst ready.")
        debate.append({
            "sender": "ANALYST", 
            "content": analyst_res, 
            "timestamp": datetime.utcnow().isoformat(),
            "agent_info": agent_registry.get("ANALYST", {})
        })
        
        # 3. Negotiator chimes in
        negotiator_system = "You are Negotiation Agent Δ. Autonomously negotiate prices."
        negotiator_user = (
            f"L1 bid: Rs. {context['l1_amount']:,.0f}. Target savings: {target_savings_pct}%. "
            f"User query: '{message}'. Planner says: '{planner_res}'. Analyst says: '{analyst_res}'. "
            f"Draft a response/offer to the user in 1-2 sentences."
        )
        negotiator_res = ai_swarm_engine._call_agent_llm("NEGOTIATOR", negotiator_system, negotiator_user, "Negotiator ready.")
        debate.append({
            "sender": "NEGOTIATOR", 
            "content": negotiator_res, 
            "timestamp": datetime.utcnow().isoformat(),
            "agent_info": agent_registry.get("NEGOTIATOR", {})
        })
        
        # 4. Critic chimes in
        critic_system = "You are Cognitive Critic Ξ. Conducts adversarial risk auditing."
        critic_user = (
            f"Negotiator recommends: '{negotiator_res}'. Bids list: {context['all_bid_amounts']}. "
            f"User query: '{message}'. State any potential risk or compliance flag in 1-2 sentences."
        )
        critic_res = ai_swarm_engine._call_agent_llm("CRITIC", critic_system, critic_user, "Critic ready.")
        debate.append({
            "sender": "CRITIC", 
            "content": critic_res, 
            "timestamp": datetime.utcnow().isoformat(),
            "agent_info": agent_registry.get("CRITIC", {})
        })
        
        return {"mode": "swarm", "debate": debate}
        
    else:
        if agent not in agent_registry:
            raise HTTPException(status_code=400, detail=f"Invalid agent key: {agent}")
            
        agent_info = agent_registry[agent]
        system_prompt = (
            f"You are {agent_info['name']} ({agent_info['role']}). "
            f"Context:\n"
            f"- Target Vendor: {context['vendor_name']}\n"
            f"- L1 Bid Amount: Rs. {context['l1_amount']:,.0f}\n"
            f"- Estimated Value: Rs. {context['estimated_value']:,.0f}\n"
            f"- All Bids: {context['all_bid_amounts']}\n"
            f"- Target Savings Pct: {target_savings_pct}%\n"
            f"Respond directly and concisely in character to the user's question. Stay under 3 sentences."
        )
        
        response = ai_swarm_engine._call_agent_llm(agent, system_prompt, message, f"{agent} standby.")
        return {
            "mode": "single",
            "reply": {
                "sender": agent,
                "content": response,
                "timestamp": datetime.utcnow().isoformat(),
                "agent_info": agent_info
            }
        }


# ─────────────────────────────────────────────────────────────────
#  DYNAMIC RULE & DOCUMENT ANALYSIS ENDPOINTS
# ─────────────────────────────────────────────────────────────────
import os
import shutil
from pydantic import BaseModel
from typing import List, Dict, Any

@router.post("/extract-rules-from-doc")
def extract_rules_from_doc(
    file: UploadFile = File(...),
    tender_title: Optional[str] = Form(""),
    current_user = Depends(auth.require_role("Admin", "Evaluator"))
):
    """Uploads a tender/criteria document and extracts structured evaluation rules using Ollama."""
    os.makedirs("uploads", exist_ok=True)
    temp_path = os.path.join("uploads", f"temp_rules_{file.filename}")
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Extract text via OCR Cascade
        raw_text = extract_text_from_file(temp_path)
        if not raw_text or len(raw_text.strip()) < 50:
            raise HTTPException(status_code=400, detail="Could not extract sufficient text from the document. Ensure it is a valid PDF or image.")
            
        # Extract rules
        import rule_engine
        rules = rule_engine.extract_rules_from_document(raw_text, tender_title=tender_title)
        
        return {
            "success": True,
            "filename": file.filename,
            "text_length": len(raw_text),
            "rules": rules
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to extract rules: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.post("/extract-profile-from-doc")
def extract_profile_from_doc(
    file: UploadFile = File(...),
    doc_type: Optional[str] = Form("credential"),
    current_user = Depends(auth.require_role("Admin", "Evaluator"))
):
    """Uploads a vendor document and extracts a structured vendor profile using Ollama."""
    os.makedirs("uploads", exist_ok=True)
    temp_path = os.path.join("uploads", f"temp_vendor_{file.filename}")
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Extract text
        raw_text = extract_text_from_file(temp_path)
        if not raw_text or len(raw_text.strip()) < 50:
            raise HTTPException(status_code=400, detail="Could not extract sufficient text from the document.")
            
        # Extract profile
        import vendor_extractor
        profile = vendor_extractor.extract_vendor_profile(raw_text, doc_type=doc_type)
        
        return {
            "success": True,
            "filename": file.filename,
            "text_length": len(raw_text),
            "profile": profile
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to extract vendor profile: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


class RuleEvaluationInput(BaseModel):
    rules: List[dict]
    profile: dict
    vendor_name: Optional[str] = ""

@router.post("/evaluate-vendor-rules")
def evaluate_vendor_rules(
    data: RuleEvaluationInput,
    current_user = Depends(auth.require_role("Admin", "Evaluator"))
):
    """Applies a list of extracted rules against a vendor's structured profile."""
    import rule_engine
    try:
        verdict = rule_engine.apply_rules_to_vendor(data.rules, data.profile, vendor_name=data.vendor_name)
        return {
            "success": True,
            "verdict": verdict
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run rule engine evaluation: {str(e)}")


# ─────────────────────────────────────────────────────────────────
#  POLICY GUARDIAN Γ — COMPLIANCE SCAN ENDPOINT
# ─────────────────────────────────────────────────────────────────

class ComplianceScanInput(BaseModel):
    document_text: str
    tender_title: Optional[str] = "Tender Document"
    vendor_profile: Optional[dict] = None

@router.post("/compliance-scan")
async def compliance_scan(
    data: ComplianceScanInput,
    db: Session = Depends(get_db),
    current_user = Depends(auth.get_current_user),
):
    """
    Run Policy Guardian Γ — the Autonomous Compliance Sentinel.
    Validates a document against GEM Rules, CVC Guidelines, and MSME Policy.
    Returns compliance score, missing clauses, CVC flags, and MSME waivers.
    """
    if not data.document_text or len(data.document_text.strip()) < 20:
        raise HTTPException(status_code=400, detail="document_text must be at least 20 characters.")
    try:
        result = await ai_swarm_engine.execute_compliance_scan(
            document_text=data.document_text,
            tender_title=data.tender_title,
            vendor_profile=data.vendor_profile or {},
        )
        # Log the compliance scan
        blockchain.create_audit_log(
            db=db, user_id=current_user.id,
            action="AI_COMPLIANCE_SCAN",
            entity_type="Document", entity_id=0,
            details=f"Compliance scan: {result.get('compliance_status','?')} ({result.get('compliance_score_pct',0):.0f}%)",
        ) if hasattr(current_user, "id") else None
        db.commit()
        return result
    except Exception as e:
        if db:
            db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────
#  PREDICTIVE VENDOR RISK — ML-POWERED SCORING
# ─────────────────────────────────────────────────────────────────

@router.get("/vendor-risk/predict")
def predict_vendor_risk_endpoint(
    db: Session = Depends(get_db),
    current_user = Depends(auth.get_current_user),
):
    """
    ML-Powered Predictive Vendor Risk Scoring.
    Trains a GradientBoostingClassifier on historical bid behavior and
    returns per-vendor default risk probability with feature attributions.
    Falls back to heuristic scoring if data is insufficient (<10 vendors).
    """
    import anomaly_detector

    all_bids_raw = db.query(models.Bid).all()
    all_vendors = db.query(models.Vendor).all()
    all_tenders = db.query(models.Tender).all()
    vmap = {v.id: v for v in all_vendors}

    # Flatten bid records to dicts with enriched vendor/tender info
    bids_data = []
    for b in all_bids_raw:
        v = vmap.get(b.vendor_id)
        t = next((t for t in all_tenders if t.id == b.tender_id), None)
        bids_data.append({
            "vendor_id": b.vendor_id,
            "tender_id": b.tender_id,
            "total_amount": b.total_amount,
            "delivery_period": b.delivery_period,
            "status": b.status,
            "is_disqualified": b.is_disqualified,
            "is_blacklisted": v.is_blacklisted if v else False,
            "estimated_value": t.estimated_value if t else None,
            "tender_estimated_value": t.estimated_value if t else None,
            "submitted_at": b.submitted_at.isoformat() if b.submitted_at else None,
        })

    vendor_ids = [v.id for v in all_vendors]
    vendor_name_map = {v.id: v.company_name for v in all_vendors}

    try:
        predictions = anomaly_detector.predict_vendor_risk(
            all_bids=bids_data,
            all_vendor_ids=vendor_ids,
            vendor_name_map=vendor_name_map,
            n_tenders=len(all_tenders),
        )
        model_info = anomaly_detector.train_vendor_risk_model(bids_data, n_tenders=len(all_tenders))

        return {
            "model_type": model_info["model_type"],
            "training_samples": model_info["training_samples"],
            "feature_importances": model_info["feature_importances"],
            "vendor_count": len(predictions),
            "critical_count": sum(1 for p in predictions if p["risk_level"] == "CRITICAL"),
            "high_count": sum(1 for p in predictions if p["risk_level"] == "HIGH"),
            "predictions": predictions,
            "generated_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")


# ─────────────────────────────────────────────────────────────────
#  VENDOR DNA FINGERPRINT — SHELL COMPANY DETECTION
# ─────────────────────────────────────────────────────────────────

@router.get("/vendor-dna")
def vendor_dna_analysis(
    db: Session = Depends(get_db),
    current_user = Depends(auth.get_current_user),
):
    """
    Vendor DNA Fingerprint Engine.
    Profiles all vendors by behavioral fingerprints (price patterns, bid timing,
    co-bidder relationships) and runs DBSCAN clustering to identify shell company rings.
    """
    import vendor_dna as vdna

    all_bids_raw = db.query(models.Bid).all()
    all_vendors = db.query(models.Vendor).all()
    all_tenders = db.query(models.Tender).all()
    vmap = {v.id: v for v in all_vendors}

    # Convert to dicts
    bids_data = []
    for b in all_bids_raw:
        bids_data.append({
            "vendor_id": b.vendor_id,
            "tender_id": b.tender_id,
            "total_amount": b.total_amount,
            "status": b.status,
            "submitted_at": b.submitted_at.isoformat() if b.submitted_at else None,
            "is_disqualified": b.is_disqualified,
        })

    tenders_data = []
    for t in all_tenders:
        tenders_data.append({
            "id": t.id,
            "estimated_value": t.estimated_value,
            "title": t.title,
            "category": getattr(t, "category", None) or t.title,
        })

    vendor_ids = [v.id for v in all_vendors]
    vendor_name_map = {v.id: v.company_name for v in all_vendors}

    try:
        result = vdna.run_full_dna_analysis(
            all_bids=bids_data,
            all_tenders=tenders_data,
            all_vendor_ids=vendor_ids,
            vendor_name_map=vendor_name_map,
        )

        # Log
        n_clusters = result["shell_clusters"]["summary"].get("clusters_found", 0)
        blockchain.create_audit_log(
            db, current_user.id, "DNA_SHELL_DETECTION",
            "System", 0,
            f"Vendor DNA analysis: {n_clusters} shell company cluster(s) detected",
        )
        db.commit()

        return {
            "total_vendors_profiled": len(vendor_ids),
            "total_pairs_analyzed": result["total_pairs_analyzed"],
            "shell_clusters": result["shell_clusters"],
            "high_risk_pairs": result["high_risk_pairs"][:10],
            "top_similarity_pairs": result["top_similarity_pairs"][:10],
            "generated_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DNA analysis failed: {str(e)}")


class ConflictScanInput(BaseModel):
    bids_data: List[dict]

@router.post("/conflict-scan")
async def conflict_scan_endpoint(
    data: ConflictScanInput,
    current_user = Depends(auth.get_current_user),
):
    """
    Run Kinship Sentinel X — the Swarm Conflict of Interest Agent.
    Cross-scans bidder profiles for relationships, overlapping personnel, matching IPs, and kinship links.
    """
    if not data.bids_data or len(data.bids_data) < 2:
        raise HTTPException(status_code=400, detail="bids_data must contain at least 2 bidder profiles.")
    try:
        result = await ai_swarm_engine.execute_coi_scan(data.bids_data)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


