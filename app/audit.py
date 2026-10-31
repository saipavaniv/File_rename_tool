"""Tamper-evident audit log (HMAC hash chain)."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import secret_key
from .models import AuditLog, now

_lock = threading.Lock()


def _digest(prev: str, row: dict) -> str:
    msg = prev + "|" + json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(secret_key(), msg.encode(), hashlib.sha256).hexdigest()


def _payload(e: AuditLog) -> dict:
    return {"at": e.at.isoformat(timespec="microseconds"), "user_id": e.user_id, "username": e.username,
            "action": e.action, "target": e.target, "ip": e.ip, "detail": e.detail}


def log(db: Session, action: str, user=None, target: str = "", ip: str = "", detail: dict | None = None,
        commit: bool = True):
    with _lock:
        last = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
        prev = last.hash if last else ""
        e = AuditLog(at=now(), user_id=getattr(user, "id", None), username=getattr(user, "username", "") or "",
                     action=action, target=(target or "")[:255], ip=ip or "",
                     detail=json.dumps(detail or {}, default=str)[:4000], prev_hash=prev)
        e.hash = _digest(prev, _payload(e))
        db.add(e)
        db.flush()   # next entry in this transaction must chain onto this one
        if commit:
            db.commit()


def verify(db: Session) -> dict:
    prev = ""
    count = 0
    for e in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        count += 1
        if e.prev_hash != prev or not hmac.compare_digest(e.hash, _digest(prev, _payload(e))):
            return {"ok": False, "checked": count, "broken_at_id": e.id}
        prev = e.hash
    return {"ok": True, "checked": count}
