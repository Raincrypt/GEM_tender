"""
GEM Tender — Authentication & Authorization Module v2.0
Security hardened:
  - No anonymous / auto-admin fallback in production
  - Token blacklist backed by Redis (with in-memory fallback for dev)
  - MFA (TOTP) enforcement
  - Role-based access control via require_role()
"""
from datetime import datetime, timedelta
from typing import Optional, List
from jose import JWTError, jwt

# Monkey patch for passlib with newer bcrypt
import bcrypt
if not hasattr(bcrypt, "__about__"):
    class AboutMock:
        __version__ = "3.2.0"
    bcrypt.__about__ = AboutMock

from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import models
from database import get_db
import os
import logging

logger = logging.getLogger("gem.auth")

# ──────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "GEM_TENDER_SECRET_KEY_2024_SECURE_RANDOM_STRING")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours

# Password hashing configuration (using sha256_crypt)

pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


# ──────────────────────────────────────────────────────────────────────────────
#  TOKEN BLACKLIST — Redis-backed with in-memory fallback
# ──────────────────────────────────────────────────────────────────────────────
_MEMORY_BLACKLIST: set = set()
_redis_client = None


def _get_redis():
    """Lazily initialize Redis client. Returns None if Redis is unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        client = redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        _redis_client = client
        logger.info("[auth] Redis token blacklist connected.")
        return _redis_client
    except Exception as e:
        logger.warning(f"[auth] Redis unavailable — using in-memory blacklist: {e}")
        return None


def invalidate_token(token: str):
    """Revoke a JWT by adding it to the blacklist. TTL matches token expiry."""
    r = _get_redis()
    if r:
        try:
            # Decode to get expiry time for proper TTL
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            exp = payload.get("exp", 0)
            ttl = max(1, int(exp - datetime.utcnow().timestamp()))
            r.setex(f"blacklist:{token}", ttl, "1")
            return
        except Exception:
            pass
    # Fallback to in-memory
    _MEMORY_BLACKLIST.add(token)


def is_token_blacklisted(token: str) -> bool:
    """Check if a token has been revoked."""
    r = _get_redis()
    if r:
        try:
            return r.exists(f"blacklist:{token}") > 0
        except Exception:
            pass
    return token in _MEMORY_BLACKLIST


# ──────────────────────────────────────────────────────────────────────────────
#  PASSWORD UTILITIES
# ──────────────────────────────────────────────────────────────────────────────
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# ──────────────────────────────────────────────────────────────────────────────
#  JWT UTILITIES
# ──────────────────────────────────────────────────────────────────────────────
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ──────────────────────────────────────────────────────────────────────────────
#  AUTHENTICATION
# ──────────────────────────────────────────────────────────────────────────────
def authenticate_user(db, username: str, password: str, mfa_code: Optional[str] = None):
    """
    Authenticate user with username + password.
    If the user has MFA enabled, also validates TOTP code.
    Returns the User model on success, None on failure.
    """
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        logger.warning(f"[auth] Failed login attempt for username='{username}'")
        return None

    # MFA Enforcement — TOTP-based (RFC 6238 compliant)
    if getattr(user, "mfa_enabled", False):
        if not mfa_code:
            raise HTTPException(status_code=401, detail="MFA Code Required")
        mfa_valid = False
        try:
            import pyotp
            mfa_secret = getattr(user, "mfa_secret", None) or os.environ.get("MFA_TOTP_SECRET", "")
            if mfa_secret:
                totp = pyotp.TOTP(mfa_secret)
                mfa_valid = totp.verify(mfa_code, valid_window=1)  # ±30s window
        except ImportError:
            raise HTTPException(status_code=503, detail="MFA service unavailable: pyotp not installed")
        if not mfa_valid:
            raise HTTPException(status_code=401, detail="Invalid or expired MFA Code")

    return user


# ──────────────────────────────────────────────────────────────────────────────
#  CURRENT USER DEPENDENCY
# ──────────────────────────────────────────────────────────────────────────────
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db = Depends(get_db),
):
    """
    Resolves the current authenticated user from a Bearer JWT.

    Security policy:
    - A valid, non-blacklisted JWT is strictly required.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Please provide a valid Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # ── No token provided ──────────────────────────────────────────────────
    if not credentials or not credentials.credentials:
        raise credentials_exception

    token = credentials.credentials

    # ── Blacklist check ────────────────────────────────────────────────────
    if is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── Decode & validate JWT ──────────────────────────────────────────────
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(status_code=400, detail="User account is inactive.")

    return user


# ──────────────────────────────────────────────────────────────────────────────
#  ROLE-BASED ACCESS CONTROL
# ──────────────────────────────────────────────────────────────────────────────
def require_role(*roles):
    """
    FastAPI dependency factory. Raises HTTP 403 if the authenticated user
    does not have one of the specified roles.

    Usage:
        @router.get("/admin-only")
        def endpoint(current_user=Depends(auth.require_role("Admin"))):
            ...
    """
    async def role_checker(current_user=Depends(get_current_user)):
        if current_user is None or current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role(s): {', '.join(roles)}."
            )
        return current_user
    return role_checker
