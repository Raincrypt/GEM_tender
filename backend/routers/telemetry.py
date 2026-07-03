from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import math
import models, auth
from database import get_db

router = APIRouter(prefix="/c3/telemetry", tags=["Logistics Telemetry"])

@router.get("/{po_id}")
def get_logistics_telemetry(po_id: int, db: Session = Depends(get_db)):
    """
    Simulates live IoT GPS telemetry and environmental sensors for delivery trucks.
    Provides route coordinates, weather metrics, and real-time AI rerouting recommendations.
    """
    po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
        
    tender = db.query(models.Tender).filter(models.Tender.id == po.tender_id).first()
    vendor = db.query(models.Vendor).filter(models.Vendor.id == po.vendor_id).first()
    
    # ── MOCK GPS ROUTE DATA ─────────────────────────────────────
    # Source: Vendor Dispatch to active Tender Delivery location
    destination_name = tender.department if (tender and tender.department) else "Barauni Refinery"
    origin_name = f"{vendor.company_name} Dispatch" if vendor else "Vendor Dispatch Hub"
    haldia_lat, haldia_lon = 22.0644, 88.0641
    barauni_lat, barauni_lon = 25.4344, 86.0272
    
    # Use real timestamp to animate the truck position dynamically
    now = datetime.utcnow().timestamp()
    speed_factor = 0.005 # progression speed
    progression = (now % 200) / 200.0 # 0.0 to 1.0 cycle every 200 seconds
    
    current_lat = haldia_lat + (barauni_lat - haldia_lat) * progression
    current_lon = haldia_lon + (barauni_lon - haldia_lon) * progression
    
    # Add minor noise for realistic jitter
    jitter_lat = math.sin(now) * 0.001
    jitter_lon = math.cos(now) * 0.001
    current_lat += jitter_lat
    current_lon += jitter_lon
    
    # Route path points for rendering in map
    route_points = []
    steps = 15
    for i in range(steps + 1):
        p = i / float(steps)
        lat = haldia_lat + (barauni_lat - haldia_lat) * p
        lon = haldia_lon + (barauni_lon - haldia_lon) * p
        # add curvature
        deviation = math.sin(p * math.pi) * 0.4
        lat += deviation * 0.2
        lon -= deviation * 0.3
        route_points.append({"lat": lat, "lon": lon})
        
    # Real-time position
    idx = int(progression * steps)
    if idx < len(route_points):
        current_lat = route_points[idx]["lat"] + jitter_lat
        current_lon = route_points[idx]["lon"] + jitter_lon
        
    # Weather and sensor anomaly logic
    temperature = 28.0 + math.sin(now / 10) * 3.0
    humidity = 65.0 + math.cos(now / 10) * 10.0
    vibration = 0.8 + math.sin(now) * 0.4 # in Gs
    
    # Trigger active delay alerts at ~60-80% progress
    is_anomaly = 0.55 < progression < 0.80
    alert_message = ""
    ai_reroute_suggested = False
    ai_suggestion_text = ""
    route_status = "In Transit"
    
    if is_anomaly:
        route_status = "Delayed"
        alert_message = "🚨 WEATHER HAZARD: Heavy monsoon floods causing vehicle bottleneck on NH-31."
        ai_reroute_suggested = True
        ai_suggestion_text = "AI Mitigation Advice: Reroute via SH-8 bypass to avoid 4.2-hour logistics delay and Liquidated Damages (LD) clause deduction."
        # shift position slightly off-route to simulate bypass/halt
        current_lat += 0.05
        current_lon -= 0.04
    else:
        route_status = "On Schedule"
        alert_message = "✅ Clear route. Standard operating parameters."
        
    # Final ETA calculation
    remaining_ratio = 1.0 - progression
    eta_hours = round(remaining_ratio * 12.0, 1)
    
    return {
        "po_id": po_id,
        "po_number": po.po_number,
        "tender_title": tender.title,
        "vendor_name": vendor.company_name,
        "route_status": route_status,
        "origin": {"name": origin_name, "lat": haldia_lat, "lon": haldia_lon},
        "destination": {"name": destination_name, "lat": barauni_lat, "lon": barauni_lon},
        "current_position": {"lat": current_lat, "lon": current_lon},
        "progression_pct": round(progression * 100, 1),
        "speed_kmh": 0 if is_anomaly else int(55 + math.sin(now / 5) * 5),
        "eta_hours": eta_hours,
        "route_points": route_points,
        "sensors": {
            "temperature_celsius": round(temperature, 1),
            "humidity_pct": round(humidity, 1),
            "vibration_g": round(vibration, 2),
        },
        "alert": alert_message,
        "ai_rerouting": {
            "active": ai_reroute_suggested,
            "recommendation": ai_suggestion_text
        }
    }
