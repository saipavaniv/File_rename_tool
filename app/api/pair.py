"""One-click connection of the browser button (no key copying).

  1. Extension makes a random secret code and calls  POST /api/pair/start {code}
  2. Extension opens  /connect#code=...  in a tab. The signed-in user clicks Allow ->  POST /api/pair/approve
  3. Extension polls  POST /api/pair/claim {code}  and receives its personal key once.

Safety:
  * the code is 256-bit random, lives only in the URL fragment (never sent in a URL) and expires in 5 minutes;
  * start, approve and claim must all come from the SAME computer (IP address), so a code that a
    stranger tricks you into approving can't be claimed from their machine;
  * the key is handed out once, then forgotten by the server (only its hash is stored).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import ApiToken, now
from ..security import Principal, client_ip, current_ready, limiter, new_api_token

router = APIRouter(prefix="/api/pair", tags=["pair"])

TTL = 300
_lock = threading.Lock()
_pending: dict[str, dict] = {}     # sha256(code) -> {ip, started, token?, user?}


class CodeIn(BaseModel):
    code: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_\-]+$")


def _h(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _sweep():
    t = time.monotonic()
    for k in [k for k, v in _pending.items() if t - v["started"] > TTL]:
        _pending.pop(k, None)


@router.post("/start")
def start(body: CodeIn, request: Request):
    ip = client_ip(request)
    if not limiter.hit(f"pair-start:{ip}", 20, 600):
        raise HTTPException(429, "Too many attempts. Wait a few minutes.")
    with _lock:
        _sweep()
        if len(_pending) > 500:
            raise HTTPException(503, "Busy. Try again shortly.")
        _pending[_h(body.code)] = {"ip": ip, "started": time.monotonic()}
    return {"ok": True}


@router.post("/approve")
def approve(body: CodeIn, request: Request, p: Principal = Depends(current_ready), db: Session = Depends(get_db)):
    if p.via != "session":
        raise HTTPException(403, "Sign in on the website to connect the button.")
    ip = client_ip(request)
    with _lock:
        _sweep()
        entry = _pending.get(_h(body.code))
        if not entry or entry.get("token"):
            raise HTTPException(404, "This connect link has expired. Click Connect in the Hop button again.")
        if entry["ip"] != ip:
            raise HTTPException(403, "This connect link was started on a different computer. Only approve links you started yourself.")
    active = db.execute(select(ApiToken).where(ApiToken.user_id == p.user.id, ApiToken.revoked.is_(False))
                        .order_by(ApiToken.created_at)).scalars().all()
    for old in active[:-3] if len(active) >= 4 else []:   # keep the newest few, so reconnecting never fails
        old.revoked = True
    raw, prefix, h = new_api_token()
    db.add(ApiToken(user_id=p.user.id, name="Browser button", prefix=prefix, token_hash=h,
                    expires_at=now() + dt.timedelta(days=180)))
    audit.log(db, "token.created", p.user, target="Browser button (connected)", ip=ip, commit=False)
    db.commit()
    with _lock:
        if _h(body.code) in _pending:
            _pending[_h(body.code)].update(token=raw, user=p.user.display_name or p.user.username)
    return {"ok": True}


@router.post("/claim")
def claim(body: CodeIn, request: Request):
    ip = client_ip(request)
    if not limiter.hit(f"pair-claim:{ip}", 400, 600):
        raise HTTPException(429, "Too many attempts.")
    with _lock:
        _sweep()
        k = _h(body.code)
        entry = _pending.get(k)
        if not entry or entry["ip"] != ip:
            raise HTTPException(404, "Unknown or expired code")
        if not entry.get("token"):
            return {"status": "pending"}
        _pending.pop(k, None)          # handed out exactly once
    return {"status": "ok", "token": entry["token"], "user": entry["user"]}
