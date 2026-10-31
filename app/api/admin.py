from __future__ import annotations

import csv
import hashlib
import io
import re

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .. import audit, store
from ..db import get_db
from ..engine.naming import validate_template
from ..models import ApiToken, AuditLog, Correction, Party, User, UserSession
from ..security import Principal, admin, client_ip, hash_password, password_problems

router = APIRouter(prefix="/api/admin", tags=["admin"])

USERNAME_RE = r"^[a-z0-9][a-z0-9._\-]{1,62}$"


# ---------------------------------------------------------------- users

class NewUser(BaseModel):
    username: str = Field(pattern=USERNAME_RE)
    display_name: str = Field(default="", max_length=120)
    role: str = Field(default="user", pattern=r"^(user|admin)$")
    password: str = Field(min_length=12, max_length=128)


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, pattern=r"^(user|admin)$")
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=128)
    unlock: bool | None = None


def _u(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role,
            "is_active": u.is_active, "locked": bool(u.locked_until), "must_change_password": u.must_change_password,
            "created_at": u.created_at, "last_login_at": u.last_login_at}


@router.get("/users")
def users(p: Principal = Depends(admin), db: Session = Depends(get_db)):
    return [_u(u) for u in db.execute(select(User).order_by(User.username)).scalars()]


@router.post("/users")
def create_user(body: NewUser, request: Request, p: Principal = Depends(admin), db: Session = Depends(get_db)):
    uname = body.username.lower()
    if db.execute(select(User).where(User.username == uname)).scalar_one_or_none():
        raise HTTPException(400, "That username already exists.")
    problem = password_problems(body.password, uname)
    if problem:
        raise HTTPException(400, problem)
    u = User(username=uname, display_name=body.display_name.strip(), role=body.role,
             password_hash=hash_password(body.password), must_change_password=True)
    db.add(u)
    audit.log(db, "user.created", p.user, target=uname, ip=client_ip(request), detail={"role": body.role}, commit=False)
    db.commit()
    return _u(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, request: Request, p: Principal = Depends(admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Not found")
    admins = db.execute(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))).scalar_one()
    if u.id == p.user.id and (body.is_active is False or body.role == "user"):
        raise HTTPException(400, "You can't disable or demote your own account.")
    if u.role == "admin" and admins <= 1 and (body.is_active is False or body.role == "user"):
        raise HTTPException(400, "There must always be at least one active administrator.")
    changes = {}
    if body.display_name is not None:
        u.display_name = body.display_name.strip()
        changes["display_name"] = u.display_name
    if body.role is not None and body.role != u.role:
        u.role = body.role
        changes["role"] = body.role
    if body.is_active is not None and body.is_active != u.is_active:
        u.is_active = body.is_active
        changes["is_active"] = body.is_active
        if not body.is_active:   # sign out everywhere, kill extension tokens
            db.execute(delete(UserSession).where(UserSession.user_id == u.id))
            for t in db.execute(select(ApiToken).where(ApiToken.user_id == u.id)).scalars():
                t.revoked = True
    if body.password:
        problem = password_problems(body.password, u.username)
        if problem:
            raise HTTPException(400, problem)
        u.password_hash = hash_password(body.password)
        u.must_change_password = True
        u.failed_logins, u.locked_until = 0, None
        db.execute(delete(UserSession).where(UserSession.user_id == u.id))
        for t in db.execute(select(ApiToken).where(ApiToken.user_id == u.id)).scalars():
            t.revoked = True
        changes["password"] = "reset"
    if body.unlock:
        u.failed_logins, u.locked_until = 0, None
        changes["unlocked"] = True
    audit.log(db, "user.updated", p.user, target=u.username, ip=client_ip(request), detail=changes, commit=False)
    db.commit()
    return _u(u)


# ---------------------------------------------------------------- settings

class SettingsIn(BaseModel):
    own_names: list[str] = Field(max_length=20)
    own_domains: list[str] = Field(max_length=20)
    template: str = Field(max_length=80)
    date_order: str = Field(pattern=r"^(DMY|MDY)$")
    auto_threshold: float = Field(ge=0.5, le=0.99)


@router.get("/settings")
def get_settings(p: Principal = Depends(admin), db: Session = Depends(get_db)):
    return store.get_settings(db)


@router.put("/settings")
def put_settings(body: SettingsIn, request: Request, p: Principal = Depends(admin), db: Session = Depends(get_db)):
    if not validate_template(body.template):
        raise HTTPException(400, "Template may only contain {date} {type} {party} {ref} {subject} separated by _ or -")
    names = [n.strip()[:80] for n in body.own_names if n.strip()]
    domains = [d.strip().lower().lstrip("@")[:120] for d in body.own_domains if d.strip()]
    if any(not re.fullmatch(r"[a-z0-9.\-]+\.[a-z]{2,}", d) for d in domains):
        raise HTTPException(400, "Each own domain must look like kramski.com")
    vals = {"own_names": names, "own_domains": domains, "template": body.template,
            "date_order": body.date_order, "auto_threshold": round(body.auto_threshold, 2)}
    store.save_settings(db, vals)
    audit.log(db, "settings.changed", p.user, ip=client_ip(request), detail=vals)
    return vals


# ---------------------------------------------------------------- parties (customers / suppliers)

class PartyIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=200)
    short_name: str = Field(default="", max_length=60)
    aliases: str = Field(default="", max_length=500)
    domains: str = Field(default="", max_length=300)
    kind: str = Field(default="customer", pattern=r"^(customer|supplier|other)$")


def _p(x: Party) -> dict:
    return {"id": x.id, "code": x.code, "name": x.name, "short_name": x.short_name, "aliases": x.aliases,
            "domains": x.domains, "kind": x.kind}


@router.get("/parties")
def parties(q: str | None = None, p: Principal = Depends(admin), db: Session = Depends(get_db)):
    stmt = select(Party).where(Party.active.is_(True))
    if q:
        like = f"%{q.strip()[:80]}%"
        stmt = stmt.where(or_(Party.name.ilike(like), Party.code.ilike(like), Party.short_name.ilike(like),
                              Party.domains.ilike(like)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    return {"total": total, "items": [_p(x) for x in db.execute(stmt.order_by(Party.name).limit(300)).scalars()]}


def _upsert(db: Session, d: dict) -> bool:
    x = db.execute(select(Party).where(Party.code == d["code"])).scalar_one_or_none()
    new = x is None
    if new:
        x = Party(code=d["code"])
        db.add(x)
    x.name, x.short_name, x.aliases, x.domains, x.kind, x.active = (
        d["name"], d["short_name"], d["aliases"], d["domains"], d["kind"], True)
    return new


@router.post("/parties")
def add_party(body: PartyIn, request: Request, p: Principal = Depends(admin), db: Session = Depends(get_db)):
    _upsert(db, body.model_dump())
    audit.log(db, "party.saved", p.user, target=body.code, ip=client_ip(request), commit=False)
    db.commit()
    store.invalidate()
    return {"ok": True}


@router.delete("/parties/{party_id}")
def delete_party(party_id: int, request: Request, p: Principal = Depends(admin), db: Session = Depends(get_db)):
    x = db.get(Party, party_id)
    if not x:
        raise HTTPException(404, "Not found")
    x.active = False
    audit.log(db, "party.removed", p.user, target=x.code, ip=client_ip(request), commit=False)
    db.commit()
    store.invalidate()
    return {"ok": True}


@router.post("/parties/import")
async def import_parties(request: Request, file: UploadFile = File(...), p: Principal = Depends(admin),
                         db: Session = Depends(get_db)):
    raw = await file.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "CSV too large (max 5 MB)")
    text = raw.decode("utf-8-sig", "replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
    if "name" not in cols:
        raise HTTPException(400, "CSV needs at least a 'name' column (optional: code, short_name, aliases, domains, kind)")
    added = updated = skipped = 0
    for i, row in enumerate(reader):
        if i >= 20000:
            break
        g = lambda k, lim: (row.get(cols[k]) or "").strip()[:lim] if k in cols else ""
        try:
            d = PartyIn(code=g("code", 40) or "AUTO-" + hashlib.sha1(g("name", 200).lower().encode()).hexdigest()[:10], name=g("name", 200),
                        short_name=g("short_name", 60), aliases=g("aliases", 500), domains=g("domains", 300),
                        kind=(g("kind", 16).lower() or "customer") if g("kind", 16).lower() in ("customer", "supplier", "other", "") else "other")
        except Exception:
            skipped += 1
            continue
        if _upsert(db, d.model_dump()):
            added += 1
        else:
            updated += 1
    audit.log(db, "parties.imported", p.user, ip=client_ip(request),
              detail={"added": added, "updated": updated, "skipped": skipped}, commit=False)
    db.commit()
    store.invalidate()
    return {"added": added, "updated": updated, "skipped": skipped}


# ---------------------------------------------------------------- audit & learning

@router.get("/audit")
def audit_list(limit: int = 100, offset: int = 0, action: str | None = None, p: Principal = Depends(admin),
               db: Session = Depends(get_db)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action[:40]}%"))
    rows = db.execute(stmt.order_by(AuditLog.id.desc()).limit(max(1, min(limit, 500))).offset(max(0, offset))).scalars()
    return [{"id": e.id, "at": e.at, "username": e.username, "action": e.action, "target": e.target, "ip": e.ip,
             "detail": e.detail} for e in rows]


@router.get("/audit/verify")
def audit_verify(request: Request, p: Principal = Depends(admin), db: Session = Depends(get_db)):
    res = audit.verify(db)
    audit.log(db, "audit.verified", p.user, ip=client_ip(request), detail=res)
    return res


@router.get("/corrections")
def corrections(p: Principal = Depends(admin), db: Session = Depends(get_db)):
    """Most common corrections: tells the admin which rules to add."""
    rows = db.execute(select(Correction.field, Correction.suggested, Correction.corrected, func.count().label("n"))
                      .group_by(Correction.field, Correction.suggested, Correction.corrected)
                      .order_by(func.count().desc()).limit(50)).all()
    return [{"field": f, "suggested": s, "corrected": c, "count": n} for f, s, c, n in rows]
