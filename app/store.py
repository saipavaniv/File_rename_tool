"""Admin-editable settings and the engine configuration built from them."""
from __future__ import annotations

import json
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engine.naming import DEFAULT_TEMPLATE
from .models import Party, Setting

DEFAULTS = {
    "own_names": [],
    "own_domains": [],
    "template": DEFAULT_TEMPLATE,
    "date_order": "DMY",
    "auto_threshold": 0.75,
}

_cache: dict | None = None
_lock = threading.Lock()


def invalidate():
    global _cache
    with _lock:
        _cache = None


def get_settings(db: Session) -> dict:
    out = dict(DEFAULTS)
    for s in db.execute(select(Setting)).scalars():
        if s.key in DEFAULTS:
            try:
                out[s.key] = json.loads(s.value)
            except ValueError:
                pass
    return out


def save_settings(db: Session, values: dict):
    for k, v in values.items():
        if k not in DEFAULTS:
            continue
        row = db.get(Setting, k)
        if row:
            row.value = json.dumps(v)
        else:
            db.add(Setting(key=k, value=json.dumps(v)))
    db.commit()
    invalidate()


def engine_config(db: Session) -> dict:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
    s = get_settings(db)
    rows = [{"name": p.name, "short_name": p.short_name, "aliases": p.aliases, "domains": p.domains}
            for p in db.execute(select(Party).where(Party.active.is_(True))).scalars()]
    cfg = {"own_names": s["own_names"], "own_domains": s["own_domains"], "template": s["template"],
           "date_order": s["date_order"], "auto_threshold": s["auto_threshold"], "party_rows": rows}
    with _lock:
        _cache = cfg
    return cfg
