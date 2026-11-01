"""Authentication, sessions, CSRF, API tokens, rate limits and security headers."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import settings
from .db import get_db
from .models import ApiToken, User, UserSession, now

# Argon2id (memory-hard): resistant to GPU cracking if the database is ever stolen.
ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_DUMMY_HASH = ph.hash("dummy-password-for-timing")


def hash_password(pw: str) -> str:
    return ph.hash(pw)


def verify_password(hash_: str, pw: str) -> bool:
    try:
        return ph.verify(hash_, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def burn_time(pw: str):
    """Same cost as a real check, so unknown usernames can't be discovered by timing."""
    verify_password(_DUMMY_HASH, pw)


def password_problems(pw: str, username: str = "") -> str | None:
    if len(pw) < 12:
        return "Password must be at least 12 characters."
    if len(pw) > 128:
        return "Password is too long."
    classes = sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 3:
        return "Use at least three of: lowercase, uppercase, digits, symbols."
    if username and username.lower() in pw.lower():
        return "Password must not contain the username."
    if pw.lower() in {"password1234", "welcome12345", "qwertyuiop12"}:
        return "This password is too common."
    return None


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def new_api_token() -> tuple[str, str, str]:
    raw = "krn_" + secrets.token_urlsafe(32)
    return raw, raw[:10], sha256(raw)


def client_ip(request: Request) -> str:
    if settings.trust_proxy:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[-1].strip()[:64]   # right-most = set by our proxy; left ones are client-controlled
    return (request.client.host if request.client else "")[:64]


# ---------------------------------------------------------------- rate limiting

class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: int) -> bool:
        """True if fewer than `limit` hits in the window (does not record a hit)."""
        t = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return True
            while q and q[0] < t - window:
                q.popleft()
            return len(q) < limit

    def hit(self, key: str, limit: int, window: int) -> bool:
        t = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] < t - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(t)
            if len(self._hits) > 50_000:      # bound memory
                self._hits.clear()
            return True


limiter = RateLimiter()


# ---------------------------------------------------------------- sessions

def create_session(db: Session, user: User, request: Request) -> tuple[str, UserSession]:
    raw = secrets.token_urlsafe(32)
    s = UserSession(user_id=user.id, token_hash=sha256(raw), csrf_token=secrets.token_urlsafe(32),
                    expires_at=now() + dt.timedelta(hours=settings.session_hours),
                    ip=client_ip(request), user_agent=request.headers.get("user-agent", "")[:255])
    db.add(s)
    return raw, s


def set_session_cookie(response, raw: str):
    response.set_cookie(settings.cookie_name, raw, max_age=settings.session_hours * 3600, httponly=True,
                        secure=settings.cookie_secure, samesite="strict", path="/")


def clear_session_cookie(response):
    response.delete_cookie(settings.cookie_name, path="/", secure=settings.cookie_secure,
                           httponly=True, samesite="strict")


class Principal:
    def __init__(self, user: User, session: UserSession | None = None, token: ApiToken | None = None):
        self.user = user
        self.session = session
        self.token = token

    @property
    def via(self) -> str:
        return "token" if self.token else "session"


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _from_session(request: Request, db: Session) -> Principal | None:
    raw = request.cookies.get(settings.cookie_name)
    if not raw or len(raw) > 100:
        return None
    s = db.execute(select(UserSession).where(UserSession.token_hash == sha256(raw))).scalar_one_or_none()
    if not s:
        return None
    t = now()
    if s.expires_at < t or s.last_seen_at < t - dt.timedelta(minutes=settings.idle_minutes):
        db.delete(s)
        db.commit()
        return None
    user = db.get(User, s.user_id)
    if not user or not user.is_active:
        return None
    if request.method not in SAFE_METHODS:
        # CSRF: a cookie alone is never enough to change anything
        sent = request.headers.get("x-csrf-token", "")
        if not sent or not hmac.compare_digest(sent, s.csrf_token):
            raise HTTPException(403, "Security check failed. Reload the page and try again.")
        origin = request.headers.get("origin")
        if origin and origin.split("://", 1)[-1] != request.headers.get("host", ""):
            raise HTTPException(403, "Cross-site request blocked.")
    if (t - s.last_seen_at).total_seconds() > 60:
        s.last_seen_at = t
        db.commit()
    return Principal(user, session=s)


def _from_token(request: Request, db: Session) -> Principal | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    raw = auth[7:].strip()
    if not raw.startswith("krn_") or len(raw) > 100:
        raise HTTPException(401, "Invalid token")
    tok = db.execute(select(ApiToken).where(ApiToken.token_hash == sha256(raw))).scalar_one_or_none()
    if not tok or tok.revoked or (tok.expires_at and tok.expires_at < now()):
        raise HTTPException(401, "Token is invalid, expired or revoked")
    user = db.get(User, tok.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "Account disabled")
    if not tok.last_used_at or (now() - tok.last_used_at).total_seconds() > 60:
        tok.last_used_at = now()
        db.commit()
    return Principal(user, token=tok)


def current(request: Request, db: Session = Depends(get_db)) -> Principal:
    p = _from_token(request, db) or _from_session(request, db)
    if not p:
        raise HTTPException(401, "Please sign in")
    return p


def current_session(p: Principal = Depends(current)) -> Principal:
    """Endpoints that must not be reachable with an extension token (account & admin)."""
    if p.via != "session":
        raise HTTPException(403, "Not allowed with an extension token")
    return p


def current_ready(p: Principal = Depends(current)) -> Principal:
    if p.user.must_change_password:
        raise HTTPException(403, "Please change your password first")
    return p


def admin(p: Principal = Depends(current_session)) -> Principal:
    if p.user.role != "admin":
        raise HTTPException(403, "Administrators only")
    if p.user.must_change_password:
        raise HTTPException(403, "Please change your password first")
    return p


# ---------------------------------------------------------------- middleware

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        h = resp.headers
        h["Content-Security-Policy"] = CSP
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        if not request.url.path.startswith("/api/"):
            # pages/static only: the API must stay reachable for the browser extension (token-authenticated)
            h["Cross-Origin-Resource-Policy"] = "same-origin"
        if settings.cookie_secure:
            h["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith("/api/"):
            h["Cache-Control"] = "no-store"
        if "server" in h:
            del h["server"]
        return resp


class BodyLimit(BaseHTTPMiddleware):
    """Reject oversize uploads before they are read."""
    async def dispatch(self, request, call_next):
        limit = (settings.max_upload_mb + 1) * 1024 * 1024
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > limit:
            return JSONResponse({"detail": f"File too large (max {settings.max_upload_mb} MB)"}, status_code=413)
        if request.method in ("POST", "PUT", "PATCH") and not cl and request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Content-Length required"}, status_code=411)
        return await call_next(request)
