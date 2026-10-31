from __future__ import annotations

import csv
import io
import json
import os
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit, store
from ..config import settings
from ..db import get_db
from ..engine import worker
from ..engine.fields import type_labels
from ..engine.naming import compose, sanitize_final
from ..models import Correction, FileRecord, User, now
from ..security import Principal, admin, client_ip, current_ready, limiter

router = APIRouter(prefix="/api", tags=["files"])

# Concurrency caps: protect server memory from many large uploads at once.
MAX_INFLIGHT = max(4, settings.workers * 4)
MAX_INFLIGHT_PER_USER = 4
_inflight = {"total": 0}
_inflight_user: dict[int, int] = {}

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$")


def _clean_context(raw: str | None) -> dict:
    """Context sent by the browser extension about where the file was found. Treated as untrusted hints."""
    if not raw:
        return {}
    try:
        c = json.loads(raw[:20000])
    except ValueError:
        return {}
    if not isinstance(c, dict):
        return {}
    out = {}
    for k, lim in (("link_text", 200), ("page_title", 300), ("page_host", 255), ("email_subject", 300)):
        v = c.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()[:lim]
    d = c.get("email_date")
    if isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        out["email_date"] = d
    em = c.get("sender_emails")
    if isinstance(em, list):
        out["sender_emails"] = [e.strip().lower() for e in em[:5] if isinstance(e, str) and EMAIL_RE.match(e.strip())]
    return out


def _clean_filename(name: str | None) -> str:
    name = os.path.basename((name or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:255] or "file"


async def _read_limited(upload: UploadFile) -> bytes:
    limit = settings.max_upload_mb * 1024 * 1024
    chunks, total = [], 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, f"File too large (max {settings.max_upload_mb} MB)")
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/meta")
def meta(p: Principal = Depends(current_ready), db: Session = Depends(get_db)):
    s = store.get_settings(db)
    return {"types": type_labels(), "template": s["template"], "max_upload_mb": settings.max_upload_mb}


@router.post("/analyze")
async def analyze(request: Request, file: UploadFile = File(...), context: str | None = Form(None),
                  source: str = Form("web"), p: Principal = Depends(current_ready), db: Session = Depends(get_db)):
    if not limiter.hit(f"analyze:{p.user.id}", 300, 600):
        raise HTTPException(429, "Too many files at once. Please wait a few minutes.")
    uid = p.user.id
    if _inflight["total"] >= MAX_INFLIGHT:
        raise HTTPException(503, "The server is busy. Please try again in a moment.")
    if _inflight_user.get(uid, 0) >= MAX_INFLIGHT_PER_USER:
        raise HTTPException(429, "Please wait for your other files to finish.")
    _inflight["total"] += 1
    _inflight_user[uid] = _inflight_user.get(uid, 0) + 1
    try:
        data = await _read_limited(file)
        if not data:
            raise HTTPException(400, "The file is empty.")
        filename = _clean_filename(file.filename)
        ctx = _clean_context(context)
        cfg = store.engine_config(db)
        result = await worker.analyse_isolated(data, filename, ctx, cfg, timeout=settings.analysis_timeout)
        del data
    finally:
        _inflight["total"] -= 1
        _inflight_user[uid] -= 1
        if _inflight_user[uid] <= 0:
            _inflight_user.pop(uid, None)

    f = result.get("fields") or {}
    val = lambda k: (f.get(k) or {}).get("value")
    rec = FileRecord(
        user_id=p.user.id, source="extension" if p.via == "token" else ("web" if source != "extension" else "extension"),
        original_name=filename, suggested_name=result.get("suggested_name"),
        sha256=result.get("sha256", ""), size_bytes=result.get("size", 0), kind=result.get("kind", "")[:16],
        doc_type=val("type"), party=(val("party") or None) and str(val("party"))[:120], doc_date=val("date"),
        reference=(val("ref") or None) and str(val("ref"))[:80], subject=(val("subject") or None) and str(val("subject"))[:200],
        confidence=result.get("confidence", 0.0), status=result.get("status") if result.get("status") in ("blocked", "error") else "suggested",
        auto=result.get("status") == "auto", fields_json=json.dumps(f)[:20000], page_host=ctx.get("page_host"),
    )
    db.add(rec)
    db.flush()   # assigns rec.id so the audit entry links to the file
    audit.log(db, "file.analysed", p.user, target=filename, ip=client_ip(request),
              detail={"file_id": rec.id, "sha256": rec.sha256, "suggested": rec.suggested_name, "via": p.via,
                      "status": result.get("status")}, commit=False)
    db.commit()
    # never send internal error text or file contents back; only the fields and the name
    return {"id": rec.id, "original_name": filename, "suggested_name": result.get("suggested_name"),
            "status": result.get("status"), "confidence": result.get("confidence", 0.0), "fields": f,
            "kind": result.get("kind"), "ext": result.get("ext", ""), "type_label": result.get("type_label"),
            "warnings": result.get("warnings", [])[:5], "error": result.get("error"), "ocr_used": result.get("ocr_used", False)}


class FieldsIn(BaseModel):
    date: str | None = Field(default=None, max_length=20)
    type: str | None = Field(default=None, max_length=16)
    party: str | None = Field(default=None, max_length=120)
    ref: str | None = Field(default=None, max_length=80)
    subject: str | None = Field(default=None, max_length=200)


class ComposeIn(BaseModel):
    fields: FieldsIn
    ext: str = Field(default="", max_length=12, pattern=r"^(\.[A-Za-z0-9]{1,10})?$")


@router.post("/compose")
def compose_name(body: ComposeIn, p: Principal = Depends(current_ready), db: Session = Depends(get_db)):
    s = store.get_settings(db)
    return {"name": compose(body.fields.model_dump(), s["template"], body.ext.lower())}


class FinalizeIn(BaseModel):
    final_name: str = Field(min_length=1, max_length=255)
    fields: FieldsIn | None = None


@router.post("/files/{file_id}/finalize")
def finalize(file_id: str, body: FinalizeIn, request: Request, p: Principal = Depends(current_ready),
             db: Session = Depends(get_db)):
    rec = db.get(FileRecord, file_id[:36])
    if not rec or rec.user_id != p.user.id:
        raise HTTPException(404, "Not found")
    if rec.status in ("blocked", "error"):
        raise HTTPException(400, "This file was blocked and cannot be renamed.")
    ext = os.path.splitext(rec.suggested_name or rec.original_name)[1]
    final = sanitize_final(body.final_name, ext)
    if body.fields:
        new = body.fields.model_dump()
        old = {"date": rec.doc_date, "type": rec.doc_type, "party": rec.party, "ref": rec.reference, "subject": rec.subject}
        for k, v in new.items():
            if v is not None and (v or "") != (old.get(k) or ""):
                db.add(Correction(file_id=rec.id, user_id=p.user.id, field=k, suggested=old.get(k), corrected=v[:255]))
        rec.doc_date, rec.doc_type, rec.party = new["date"] or rec.doc_date, new["type"] or rec.doc_type, new["party"]
        rec.reference, rec.subject = new["ref"], new["subject"]
    if final != rec.suggested_name and not body.fields:
        db.add(Correction(file_id=rec.id, user_id=p.user.id, field="name", suggested=rec.suggested_name, corrected=final))
    rec.final_name = final
    rec.status = "saved"
    rec.finalized_at = now()
    audit.log(db, "file.renamed", p.user, target=final, ip=client_ip(request),
              detail={"file_id": rec.id, "from": rec.original_name, "edited": final != rec.suggested_name}, commit=False)
    db.commit()
    return {"id": rec.id, "final_name": final}


def _file_out(r: FileRecord, username: str | None = None) -> dict:
    return {"id": r.id, "original_name": r.original_name, "suggested_name": r.suggested_name,
            "final_name": r.final_name, "doc_type": r.doc_type, "party": r.party, "doc_date": r.doc_date,
            "reference": r.reference, "subject": r.subject, "confidence": r.confidence, "status": r.status,
            "auto": r.auto, "source": r.source, "size_bytes": r.size_bytes, "sha256": r.sha256,
            "created_at": r.created_at, "user": username}


def _query(p: Principal, q: str | None, all_: bool):
    stmt = select(FileRecord, User.username).join(User, User.id == FileRecord.user_id)
    if not (all_ and p.user.role == "admin" and p.via == "session"):
        stmt = stmt.where(FileRecord.user_id == p.user.id)
    if q:
        like = f"%{q.strip()[:100]}%"
        stmt = stmt.where(or_(FileRecord.original_name.ilike(like), FileRecord.final_name.ilike(like),
                              FileRecord.suggested_name.ilike(like), FileRecord.party.ilike(like),
                              FileRecord.reference.ilike(like), FileRecord.subject.ilike(like),
                              FileRecord.sha256 == q.strip().lower()))
    return stmt


@router.get("/files")
def list_files(q: str | None = None, limit: int = 50, offset: int = 0, all: bool = False,
               p: Principal = Depends(current_ready), db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    stmt = _query(p, q, all)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(FileRecord.created_at.desc()).limit(limit).offset(max(0, offset))).all()
    return {"total": total, "items": [_file_out(r, u) for r, u in rows]}


@router.get("/stats")
def stats(all: bool = False, p: Principal = Depends(current_ready), db: Session = Depends(get_db)):
    base = select(FileRecord)
    if not (all and p.user.role == "admin" and p.via == "session"):
        base = base.where(FileRecord.user_id == p.user.id)
    sub = base.subquery()
    total = db.execute(select(func.count()).select_from(sub)).scalar_one()
    saved = db.execute(select(func.count()).select_from(sub).where(sub.c.status == "saved")).scalar_one()
    auto = db.execute(select(func.count()).select_from(sub).where(sub.c.auto.is_(True))).scalar_one()
    unchanged = db.execute(select(func.count()).select_from(sub).where(
        sub.c.status == "saved", sub.c.final_name == sub.c.suggested_name)).scalar_one()
    blocked = db.execute(select(func.count()).select_from(sub).where(sub.c.status == "blocked")).scalar_one()
    return {"total": total, "saved": saved, "auto": auto, "accepted_unchanged": unchanged, "blocked": blocked}


def _csv_safe(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s   # stop formula injection in Excel


@router.get("/files/export.csv")
def export_csv(q: str | None = None, p: Principal = Depends(admin), db: Session = Depends(get_db)):
    rows = db.execute(_query(p, q, True).order_by(FileRecord.created_at.desc()).limit(50_000)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["created_at", "user", "source", "original_name", "suggested_name", "final_name", "type", "party",
                "date", "reference", "subject", "confidence", "status", "sha256"])
    for r, u in rows:
        w.writerow([_csv_safe(x) for x in (r.created_at, u, r.source, r.original_name, r.suggested_name, r.final_name,
                                           r.doc_type, r.party, r.doc_date, r.reference, r.subject, r.confidence,
                                           r.status, r.sha256)])
    audit.log(db, "files.exported", p.user, detail={"rows": len(rows)})
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="rename-history.csv"'})
