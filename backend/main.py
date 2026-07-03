import os
from dotenv import load_dotenv
# Load environment configurations from root directory
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(root_dir, ".env"), override=True)

from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
import models, schemas, auth, database
from typing import List, Dict
import os
import time
import json
import logging

logger = logging.getLogger("gem.main")

# Import routers
from routers import tenders, vendors, bids, evaluation, reports, documents, iocl, c3, security, ai_ops, analytics, ai_audit, telemetry, disputes, settings, notifications

from contextlib import asynccontextmanager
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Log MongoDB Connection Info
    try:
        database.mongo_client.admin.command("ping")
        addr = database.mongo_client.address
        logger.info("=" * 60)
        logger.info(" [SUCCESS] CONNECTED TO ENTERPRISE MONGODB CLUSTER")
        logger.info(f"   Host: {addr[0] if addr else 'localhost'}:{addr[1] if addr else 27017}")
        logger.info(f"   Database: {database.mongo_db.name}")
        logger.info(f"   Collections: {', '.join(database.mongo_db.list_collection_names())}")
        logger.info("=" * 60)
        
        # Initialize database indexes automatically on startup
        database.initialize_mongodb_indexes()
    except Exception as e:
        logger.warning("=" * 60)
        logger.warning(" [WARNING] MONGODB UNAVAILABLE — Running in degraded mode")
        logger.warning(f"   Details: {e}")
        logger.warning("=" * 60)

    asyncio.create_task(audit_log_broadcaster())
    asyncio.create_task(tender_expiration_cron())
    yield


app = FastAPI(
    title="GEM Tender Evaluation API",
    description="Backend API for the GEM Tender Evaluation System",
    version="2.0.0",
    lifespan=lifespan,
    # Disable interactive docs in production (set via env)
    docs_url="/docs" if os.environ.get("ENABLE_DOCS", "true").lower() == "true" else None,
    redoc_url="/redoc" if os.environ.get("ENABLE_DOCS", "true").lower() == "true" else None,
)


# ──────────────────────────────────────────────────────────────────────────────
#  SECURITY: Rate Limiting Middleware
#  Production: backed by Redis via slowapi or this custom sliding-window impl.
#  Dev: in-memory with periodic cleanup.
# ──────────────────────────────────────────────────────────────────────────────
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter.
    - Uses Redis when available (shared across workers/processes).
    - Falls back to in-memory for single-process dev setups.
    """
    def __init__(self, app, max_requests: int = 200, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._ip_records: dict = {}
        self._last_cleanup = time.time()
        self._redis = None
        self._redis_checked = False
        self._redis_available = False

    def _get_redis(self):
        if self._redis_checked:
            return self._redis if self._redis_available else None
        self._redis_checked = True
        try:
            import redis
            r = redis.from_url(
                os.environ.get("REDIS_URL", "redis://localhost:6379"),
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            r.ping()
            self._redis = r
            self._redis_available = True
            return r
        except Exception:
            self._redis_available = False
            self._redis = None
            return None

    async def dispatch(self, request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # ── Try Redis first ───────────────────────────────────────────────
        r = self._get_redis()
        if r:
            try:
                pipe_key = f"rl:{client_ip}"
                with r.pipeline() as pipe:
                    pipe.zadd(pipe_key, {str(now): now})
                    pipe.zremrangebyscore(pipe_key, 0, now - self.window_seconds)
                    pipe.zcard(pipe_key)
                    pipe.expire(pipe_key, self.window_seconds)
                    _, _, count, _ = pipe.execute()
                if count > self.max_requests:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Rate limit exceeded. Please slow down."},
                    )
                return await call_next(request)
            except Exception:
                pass  # Fall through to in-memory

        # ── In-memory fallback ────────────────────────────────────────────
        if client_ip not in self._ip_records:
            self._ip_records[client_ip] = []

        self._ip_records[client_ip] = [
            t for t in self._ip_records[client_ip]
            if now - t < self.window_seconds
        ]

        # Periodic memory cleanup every 5 minutes
        if now - self._last_cleanup > 300:
            stale = [ip for ip, times in self._ip_records.items() if not times]
            for ip in stale:
                del self._ip_records[ip]
            self._last_cleanup = now

        if client_ip not in self._ip_records:
            self._ip_records[client_ip] = []

        if len(self._ip_records[client_ip]) >= self.max_requests:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please slow down."},
            )

        self._ip_records[client_ip].append(now)
        return await call_next(request)


# ──────────────────────────────────────────────────────────────────────────────
#  MIDDLEWARE STACK (order matters — outermost first)
# ──────────────────────────────────────────────────────────────────────────────
# GZip MUST be innermost (added first)
app.add_middleware(GZipMiddleware, minimum_size=2000)

# CORS — read allowed origins from .env, fallback to wildcard in dev
_cors_origins_raw = os.environ.get("ALLOWED_ORIGINS", "*")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",")] if _cors_origins_raw != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RateLimitMiddleware)

# ──────────────────────────────────────────────────────────────────────────────
#  STATIC FILES — Frontend
# ──────────────────────────────────────────────────────────────────────────────
from fastapi.staticfiles import StaticFiles

frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/app", StaticFiles(directory=frontend_path, html=True), name="frontend")
        # Alias mount: some CSS references resolve to /app/vendor/vendor/... (double vendor)
        # Serve those requests from the actual frontend/vendor directory so fonts/assets are found.
        vendor_dir = os.path.join(frontend_path, "vendor")
        if os.path.exists(vendor_dir):
            app.mount("/app/vendor/vendor", StaticFiles(directory=vendor_dir), name="vendor_alias")

# ──────────────────────────────────────────────────────────────────────────────
#  ROUTERS
# ──────────────────────────────────────────────────────────────────────────────
app.include_router(tenders.router)
app.include_router(vendors.router)
app.include_router(bids.router)
app.include_router(evaluation.router)
app.include_router(reports.router)
app.include_router(documents.router)
app.include_router(iocl.router)
app.include_router(c3.router)
app.include_router(security.router)
app.include_router(ai_ops.router)
app.include_router(analytics.router)
app.include_router(ai_audit.router)
app.include_router(telemetry.router)
app.include_router(disputes.router)
app.include_router(settings.router)
app.include_router(notifications.router)


# ──────────────────────────────────────────────────────────────────────────────
#  WEBSOCKET CONNECTION MANAGER
# ──────────────────────────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}
        self.auction_connections: Dict[int, List[WebSocket]] = {}
        self.audit_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket, tender_id: int):
        await websocket.accept()
        self.active_connections.setdefault(tender_id, []).append(websocket)

    async def connect_auction(self, websocket: WebSocket, tender_id: int):
        await websocket.accept()
        self.auction_connections.setdefault(tender_id, []).append(websocket)

    def disconnect(self, websocket: WebSocket, tender_id: int):
        if tender_id in self.active_connections:
            try:
                self.active_connections[tender_id].remove(websocket)
            except ValueError:
                pass

    async def connect_audit(self, websocket: WebSocket):
        await websocket.accept()
        self.audit_connections.append(websocket)

    def disconnect_audit(self, websocket: WebSocket):
        try:
            self.audit_connections.remove(websocket)
        except ValueError:
            pass

    def disconnect_auction(self, websocket: WebSocket, tender_id: int):
        if tender_id in self.auction_connections:
            try:
                self.auction_connections[tender_id].remove(websocket)
            except ValueError:
                pass

    async def broadcast(self, message: str, tender_id: int):
        if tender_id in self.active_connections:
            dead = []
            for ws in list(self.active_connections[tender_id]):
                try:
                    await ws.send_text(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.disconnect(ws, tender_id)

    async def broadcast_auction(self, message: str, tender_id: int):
        if tender_id in self.auction_connections:
            dead = []
            for ws in list(self.auction_connections[tender_id]):
                try:
                    await ws.send_text(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.disconnect_auction(ws, tender_id)

    async def broadcast_audit(self, message: str):
        dead = []
        for ws in list(self.audit_connections):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_audit(ws)


manager = ConnectionManager()


# ──────────────────────────────────────────────────────────────────────────────
#  WEBSOCKET ENDPOINTS
# ──────────────────────────────────────────────────────────────────────────────
@app.websocket("/ws/audit")
async def audit_websocket_endpoint(websocket: WebSocket):
    await manager.connect_audit(websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep alive
    except WebSocketDisconnect:
        manager.disconnect_audit(websocket)


@app.websocket("/ws/evaluation/{tender_id}")
async def websocket_endpoint(websocket: WebSocket, tender_id: int):
    await manager.connect(websocket, tender_id)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast(f"UPDATE_TRIGGERED: {data}", tender_id)
    except WebSocketDisconnect:
        manager.disconnect(websocket, tender_id)


@app.websocket("/ws/auction/{tender_id}")
async def auction_websocket_endpoint(websocket: WebSocket, tender_id: int):
    await manager.connect_auction(websocket, tender_id)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast_auction(data, tender_id)
    except WebSocketDisconnect:
        manager.disconnect_auction(websocket, tender_id)


# ──────────────────────────────────────────────────────────────────────────────
#  BACKGROUND CRON TASKS
# ──────────────────────────────────────────────────────────────────────────────
async def tender_expiration_cron():
    """
    Autonomous System Cron Job.
    Scans every 60 seconds and auto-transitions expired 'Published' tenders
    to 'Under Evaluation'.
    """
    while True:
        await asyncio.sleep(60)
        db = None
        try:
            db = database.SessionLocal()
            from datetime import datetime
            now = datetime.utcnow()

            expired_tenders = db.query(models.Tender).filter(
                models.Tender.status == "Published",
                models.Tender.closing_date != None,
                models.Tender.closing_date < now
            ).all()

            if expired_tenders:
                for t in expired_tenders:
                    t.status = "Under Evaluation"
                    log = models.AuditLog(
                        action="AUTO_STATE_TRANSITION",
                        entity_type="Tender",
                        entity_id=t.id,
                        details="System automatically moved tender to Evaluation phase as deadline passed.",
                        ip_address="127.0.0.1",
                        timestamp=now,
                    )
                    db.add(log)
                db.commit()
                logger.info(f"[cron] Auto-transitioned {len(expired_tenders)} expired tender(s)")
        except Exception as e:
            logger.error(f"[cron] Tender expiration cron error: {e}")
        finally:
            if db:
                db.close()


async def audit_log_broadcaster():
    """Streams new audit log entries to all connected /ws/audit clients every 2s."""
    last_log_id = 0
    db = None
    try:
        db = database.SessionLocal()
        last_log = db.query(models.AuditLog).order_by(models.AuditLog.id.desc()).first()
        if last_log:
            last_log_id = last_log.id
    except Exception:
        pass
    finally:
        if db:
            db.close()

    while True:
        await asyncio.sleep(2)
        if not manager.audit_connections:
            continue
        db = None
        try:
            db = database.SessionLocal()
            latest_logs = (
                db.query(models.AuditLog)
                .filter(models.AuditLog.id > last_log_id)
                .order_by(models.AuditLog.id.asc())
                .all()
            )
            if latest_logs:
                logs_data = [
                    {
                        "id": l.id,
                        "action": l.action,
                        "details": l.details,
                        "user_id": l.user_id,
                        "timestamp": l.timestamp.isoformat() if l.timestamp else "",
                        "current_hash": l.current_hash,
                    }
                    for l in latest_logs
                ]
                await manager.broadcast_audit(json.dumps(logs_data))
                last_log_id = latest_logs[-1].id
        except Exception as e:
            logger.debug(f"[broadcaster] {e}")
        finally:
            if db:
                db.close()


# ──────────────────────────────────────────────────────────────────────────────
#  AUTH ENDPOINTS
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"message": "GEM Tender Evaluation API v2.0", "status": "operational"}


@app.get("/health")
def health_check():
    """Health check endpoint for load balancers / Docker healthcheck."""
    mongo_ok = False
    try:
        database.mongo_client.admin.command("ping")
        mongo_ok = True
    except Exception:
        pass
    status = "healthy" if mongo_ok else "degraded"
    return {"status": status, "mongodb": mongo_ok, "timestamp": time.time()}


@app.post("/token", response_model=schemas.Token, tags=["Authentication"])
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: database.SessionLocal = Depends(database.get_db),
):
    user = auth.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user account")

    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=access_token_expires,
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
        },
    }


@app.post("/logout", tags=["Authentication"])
def logout(
    credentials=Depends(auth.security),
    current_user=Depends(auth.get_current_user),
):
    """Revoke the current JWT token (adds to blacklist)."""
    if credentials and credentials.credentials:
        auth.invalidate_token(credentials.credentials)
    return {"message": "Logged out successfully. Token revoked."}


@app.post("/token/refresh", response_model=schemas.Token, tags=["Authentication"])
def refresh_token(
    credentials=Depends(auth.security),
    current_user=Depends(auth.get_current_user),
):
    """Refresh a valid JWT token before it expires."""
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": current_user.username, "role": current_user.role},
        expires_delta=access_token_expires,
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "role": current_user.role,
        },
    }


@app.get("/auth/demo-creds", tags=["Authentication"])
def get_demo_credentials():
    """Return demo credentials only when SHOW_DEMO_CREDS=true in env."""
    if os.environ.get("SHOW_DEMO_CREDS", "true").lower() == "true":     
        return {
            "show": True,
            "credentials": [
                {"label": "Demo Admin", "username": "admin", "password": "admin123"},
                {"label": "Demo Evaluator", "username": "evaluator", "password": "eval123"},
            ]
        }
    return {"show": False, "credentials": []}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

