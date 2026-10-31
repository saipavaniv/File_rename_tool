"""analyse(file bytes) -> suggested name + evidence. Pure function, no I/O."""
from __future__ import annotations

import datetime as dt
import hashlib
import os

from . import fields as F
from .detect import DANGEROUS_EXT, UnsafeFile, detect_kind
from .extract import extract
from .naming import DEFAULT_TEMPLATE, choose_ext, compose

WEIGHTS = {"type": 0.3, "date": 0.25, "party": 0.25, "ref": 0.1, "subject": 0.1}


def prepare_parties(rows: list[dict]) -> list[dict]:
    """Normalise master-data rows for matching."""
    out = []
    for r in rows:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        aliases = [a.strip() for a in (r.get("aliases") or "").split(";") if a.strip()]
        stripped = F._strip_suffix(name)
        match = list(dict.fromkeys([name, stripped] + aliases))
        out.append({
            "display": (r.get("short_name") or "").strip() or F.short_party(name),
            "match_names": [m for m in match if len(m) >= 3],
            "domains": [d.strip().lower().lstrip("@") for d in (r.get("domains") or "").split(";") if d.strip()],
        })
    return out


def analyse(data: bytes, filename: str, context: dict | None = None, config: dict | None = None) -> dict:
    ctx = context or {}
    cfg = dict(config or {})
    cfg.setdefault("own_names", ["kramski"])
    cfg.setdefault("own_domains", ["kramski.com"])
    cfg.setdefault("date_order", "DMY")
    cfg.setdefault("template", DEFAULT_TEMPLATE)
    cfg.setdefault("auto_threshold", 0.75)
    if isinstance(cfg.get("today"), str):
        cfg["today"] = dt.date.fromisoformat(cfg["today"])
    cfg["parties"] = prepare_parties(cfg.get("party_rows", []))

    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    result = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "original_name": filename,
              "warnings": []}
    try:
        kind = detect_kind(data, filename)
    except UnsafeFile as e:
        result.update({"kind": "blocked", "status": "blocked", "suggested_name": None, "fields": {},
                       "confidence": 0.0, "warnings": [f"Blocked: {e}"]})
        return result
    orig_ext = os.path.splitext(filename or "")[1].lower()
    if kind == "exe" or orig_ext in DANGEROUS_EXT:
        result.update({"kind": kind, "status": "blocked", "suggested_name": None, "fields": {}, "confidence": 0.0,
                       "warnings": ["Blocked: programs, scripts and macro files are not renamed (possible malware)"]})
        return result

    ex = extract(data, kind)
    f_type = F.find_type(ex, ctx, cfg, stem)
    f_date = F.find_date(ex, ctx, cfg)
    f_ref = F.find_ref(ex, ctx, cfg, f_type.value)
    f_party = F.find_party(ex, ctx, cfg, f_type.value)
    used = [v for v in (f_party.value, f_ref.value) if v] + list(cfg.get("own_names", []))
    f_subj = F.find_subject(ex, ctx, cfg, stem, used)

    fields = {"date": f_date, "type": f_type, "party": f_party, "ref": f_ref, "subject": f_subj}
    ext = choose_ext(kind, filename)
    name = compose({k: v.value for k, v in fields.items()}, cfg["template"], ext)

    conf = sum(WEIGHTS[k] * (fields[k].confidence if fields[k].value else (0.5 if k in ("ref", "subject") else 0))
               for k in WEIGHTS)
    status = "auto" if (conf >= cfg["auto_threshold"] and f_date.confidence >= 0.6
                        and f_type.value not in ("DOC",)) else "review"
    result.update({
        "kind": kind, "ext": ext, "status": status, "confidence": round(conf, 2),
        "suggested_name": name, "fields": {k: v.as_dict() for k, v in fields.items()},
        "ocr_used": ex.ocr_used, "warnings": ex.warnings,
        "type_label": F.type_labels().get(f_type.value, f_type.value),
    })
    return result
