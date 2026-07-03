"""
GEM Bids Router — v3.0
WebSocket auction engine powered by real bid data from the database.
All randomness removed; auction replay is deterministic and data-driven.
"""
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from datetime import datetime
import asyncio
import hashlib
from typing import List, Dict
import models, schemas, auth
from database import get_db

router = APIRouter(prefix="/bids", tags=["Bids"])


# ── Live Auction WebSocket Manager ──────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, tender_id: int):
        await websocket.accept()
        if tender_id not in self.active_connections:
            self.active_connections[tender_id] = []
        self.active_connections[tender_id].append(websocket)

    def disconnect(self, websocket: WebSocket, tender_id: int):
        if tender_id in self.active_connections:
            try:
                self.active_connections[tender_id].remove(websocket)
            except ValueError:
                pass

    async def broadcast(self, message: dict, tender_id: int):
        if tender_id in self.active_connections:
            for connection in self.active_connections[tender_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass


manager = ConnectionManager()


def _deterministic_delay(seed: str) -> float:
    """Returns a deterministic delay between 2.0 – 4.0 seconds from a seed string."""
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return 2.0 + (h % 20) / 10.0  # 2.0 – 4.0 s


@router.websocket("/ws/auction/{tender_id}")
async def websocket_auction(websocket: WebSocket, tender_id: int, db: Session = Depends(get_db)):
    """
    Data-driven live auction WebSocket.
    Primary mode: replays real submitted bids for this tender in descending price order.
    Fallback mode: deterministic hash-based simulation when no bids exist yet.
    """
    await manager.connect(websocket, tender_id)

    tender = db.query(models.Tender).filter(models.Tender.id == tender_id).first()
    if not tender:
        await websocket.close(code=1008, reason="Tender not found")
        return

    vendors = db.query(models.Vendor).all()
    if not vendors:
        await websocket.close()
        return

    vendor_map = {v.id: v for v in vendors}
    current_lowest = tender.estimated_value or 5000000

    try:
        await websocket.send_json({
            "type": "auction_start",
            "tender_id": tender.id,
            "title": tender.title,
            "starting_price": current_lowest
        })

        # --- Primary: replay real submitted bids (highest → lowest = auction countdown) ---
        real_bids = (
            db.query(models.Bid)
            .filter(models.Bid.tender_id == tender_id, models.Bid.total_amount.isnot(None))
            .order_by(models.Bid.total_amount.desc())
            .all()
        )

        if real_bids:
            for bid in real_bids:
                delay = _deterministic_delay(f"bid-{bid.id}-{tender_id}")
                await asyncio.sleep(delay)

                v = vendor_map.get(bid.vendor_id)
                vendor_name = v.company_name if v else f"Vendor #{bid.vendor_id}"
                bid_amount = int(bid.total_amount)

                await manager.broadcast({
                    "type": "new_bid",
                    "vendor_name": vendor_name,
                    "amount": bid_amount,
                    "timestamp": (bid.submitted_at or datetime.utcnow()).isoformat() + "Z"
                }, tender_id)

                current_lowest = min(current_lowest, bid_amount)

            # Announce L1 winner
            l1_bid = min(real_bids, key=lambda b: b.total_amount)
            winner_vendor = vendor_map.get(l1_bid.vendor_id)
            await manager.broadcast({
                "type": "auction_end",
                "winner": winner_vendor.company_name if winner_vendor else "Unknown",
                "final_amount": int(l1_bid.total_amount)
            }, tender_id)

        else:
            # --- Fallback: deterministic simulation when no bids exist yet ---
            # Uses hash-based drops (no random.uniform) based on vendor IDs + tender
            active_vendors = vendors[:5] if len(vendors) >= 5 else vendors

            for step, v in enumerate(active_vendors):
                v_hash = int(hashlib.sha256(f"{v.id}-{step}-{tender_id}".encode()).hexdigest(), 16)
                # Deterministic drop: 0.5% – 3.5% per bid
                drop_pct = 0.005 + (v_hash % 30) / 1000.0
                new_amount = int(current_lowest * (1 - drop_pct))

                delay = _deterministic_delay(f"fallback-{v.id}-{step}")
                await asyncio.sleep(delay)

                await manager.broadcast({
                    "type": "new_bid",
                    "vendor_name": v.company_name,
                    "amount": new_amount,
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }, tender_id)

                current_lowest = new_amount

                # Stop if we've hit the floor (40% of estimate)
                floor = int(tender.estimated_value * 0.4) if tender.estimated_value else 1000000
                if current_lowest < floor:
                    break

            winner = active_vendors[-1] if active_vendors else None
            await manager.broadcast({
                "type": "auction_end",
                "winner": winner.company_name if winner else "N/A",
                "final_amount": current_lowest
            }, tender_id)

    except WebSocketDisconnect:
        manager.disconnect(websocket, tender_id)
    except Exception:
        manager.disconnect(websocket, tender_id)


# ── Standard Bid CRUD ────────────────────────────────────────────────────────

@router.post("/", response_model=schemas.BidOut)
def submit_bid(bid: schemas.BidCreate, db: Session = Depends(get_db),
               current_user=Depends(auth.get_current_user)):
    tender = db.query(models.Tender).filter(models.Tender.id == bid.tender_id).first()
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
    if tender.status != "Published":
        raise HTTPException(status_code=400, detail="Tender is not open for bids")
    vendor = db.query(models.Vendor).filter(models.Vendor.id == bid.vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    if vendor.is_blacklisted:
        raise HTTPException(status_code=400, detail="Blacklisted vendor cannot submit bids")
    existing = db.query(models.Bid).filter(
        models.Bid.tender_id == bid.tender_id,
        models.Bid.vendor_id == bid.vendor_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Vendor already submitted a bid for this tender")
    total = bid.bid_amount + bid.taxes
    db_bid = models.Bid(**bid.dict(), total_amount=total)
    db.add(db_bid)
    db.commit()
    db.refresh(db_bid)
    return db_bid


@router.get("/tender/{tender_id}", response_model=List[schemas.BidOut])
def get_bids_for_tender(tender_id: int, db: Session = Depends(get_db),
                        current_user=Depends(auth.get_current_user)):
    return db.query(models.Bid).filter(models.Bid.tender_id == tender_id).all()


@router.get("/{bid_id}", response_model=schemas.BidOut)
def get_bid(bid_id: int, db: Session = Depends(get_db),
            current_user=Depends(auth.get_current_user)):
    bid = db.query(models.Bid).filter(models.Bid.id == bid_id).first()
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")
    return bid


@router.delete("/{bid_id}")
def delete_bid(bid_id: int, db: Session = Depends(get_db),
               current_user=Depends(auth.require_role("Admin"))):
    bid = db.query(models.Bid).filter(models.Bid.id == bid_id).first()
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")
    db.delete(bid)
    db.commit()
    return {"message": "Bid deleted"}
