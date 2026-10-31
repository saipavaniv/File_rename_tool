from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import get_db
from ..models import ApiToken, User, UserSession, now
from ..security import (Principal, burn_time, clear_session_cookie, client_ip, create_session, current,
                        current_session, hash_password, limiter, new_api_token, password_problems,
                        set_session_cookie, verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name or u.username,
            "role": u.role, "must_change_password": u.must_change_password}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    uname = body.username.strip().lower()
    # Throttling is per IP and per username+IP, so a stranger cannot lock a real person out,
    # and the response is identical whether or not the username exists.
    if (not limiter.hit(f"login-ip:{ip}", 30, 900)
            or not limiter.check(f"login-fail:{uname}:{ip}", settings.login_max_fails, settings.lock_minutes * 60)
            or not limiter.check(f"login-fail-user:{uname}", 50, 900)):
        burn_time(body.password)
        audit.log(db, "login.throttled", target=uname, ip=ip)
        raise HTTPException(429, f"Too many sign-in attempts. Please wait {settings.lock_minutes} minutes.")
    user = db.execute(select(User).where(User.username == uname)).scalar_one_or_none()
    ok = verify_password(user.password_hash, body.password) if user else (burn_time(body.password) or False)
    if not user or not ok or not user.is_active:
        limiter.hit(f"login-fail:{uname}:{ip}", 10**6, settings.lock_minutes * 60)
        limiter.hit(f"login-fail-user:{uname}", 10**6, 900)
        if user:
            user.failed_logins += 1
        reason = "unknown user" if not user else ("disabled" if not user.is_active else "bad password")
        audit.log(db, "login.failed", user, target=uname, ip=ip, detail={"reason": reason})
        raise HTTPException(401, "Wrong username or password.")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now()
    # keep at most 5 sessions per user
    old = db.execute(select(UserSession).where(UserSession.user_id == user.id)
                     .order_by(UserSession.created_at.desc()).offset(4)).scalars().all()
    for s in old:
        db.delete(s)
    raw, s = create_session(db, user, request)
    audit.log(db, "login.success", user, target=uname, ip=ip, commit=False)
    db.commit()
    set_session_cookie(response, raw)
    return {"user": user_out(user), "csrf": s.csrf_token}


@router.post("/logout")
def logout(request: Request, response: Response, p: Principal = Depends(current_session), db: Session = Depends(get_db)):
    db.delete(p.session)
    audit.log(db, "logout", p.user, ip=client_ip(request), commit=False)
    db.commit()
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(p: Principal = Depends(current)):
    out = {"user": user_out(p.user), "via": p.via, "max_upload_mb": settings.max_upload_mb}
    if p.session:
        out["csrf"] = p.session.csrf_token
    return out


class PasswordIn(BaseModel):
    current: str = Field(min_length=1, max_length=128)
    new: str = Field(min_length=1, max_length=128)


@router.post("/password")
def change_password(body: PasswordIn, request: Request, p: Principal = Depends(current_session),
                    db: Session = Depends(get_db)):
    if not limiter.hit(f"pw:{p.user.id}", 10, 900):
        raise HTTPException(429, "Too many attempts. Please wait.")
    if not verify_password(p.user.password_hash, body.current):
        raise HTTPException(400, "Current password is wrong.")
    problem = password_problems(body.new, p.user.username)
    if problem:
        raise HTTPException(400, problem)
    if verify_password(p.user.password_hash, body.new):
        raise HTTPException(400, "New password must be different.")
    p.user.password_hash = hash_password(body.new)
    p.user.must_change_password = False
    db.execute(delete(UserSession).where(UserSession.user_id == p.user.id, UserSession.id != p.session.id))
    for t in db.execute(select(ApiToken).where(ApiToken.user_id == p.user.id, ApiToken.revoked.is_(False))).scalars():
        t.revoked = True   # a stolen key must not survive a password change
    audit.log(db, "password.changed", p.user, ip=client_ip(request), commit=False)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- extension tokens

class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    days: int = Field(default=180, ge=1, le=365)


@router.get("/tokens")
def list_tokens(p: Principal = Depends(current_session), db: Session = Depends(get_db)):
    rows = db.execute(select(ApiToken).where(ApiToken.user_id == p.user.id, ApiToken.revoked.is_(False))
                      .order_by(ApiToken.created_at.desc())).scalars()
    return [{"id": t.id, "name": t.name, "prefix": t.prefix, "created_at": t.created_at,
             "expires_at": t.expires_at, "last_used_at": t.last_used_at} for t in rows]


@router.post("/tokens")
def create_token(body: TokenIn, request: Request, p: Principal = Depends(current_session), db: Session = Depends(get_db)):
    if p.user.must_change_password:
        raise HTTPException(403, "Please change your password first")
    active = db.execute(select(ApiToken).where(ApiToken.user_id == p.user.id, ApiToken.revoked.is_(False))).scalars().all()
    if len(active) >= 5:
        raise HTTPException(400, "You already have 5 active tokens. Revoke one first.")
    raw, prefix, h = new_api_token()
    t = ApiToken(user_id=p.user.id, name=body.name.strip(), prefix=prefix, token_hash=h,
                 expires_at=now() + dt.timedelta(days=body.days))
    db.add(t)
    audit.log(db, "token.created", p.user, target=body.name, ip=client_ip(request), commit=False)
    db.commit()
    return {"id": t.id, "token": raw, "expires_at": t.expires_at}


@router.delete("/tokens/{token_id}")
def revoke_token(token_id: int, request: Request, p: Principal = Depends(current_session), db: Session = Depends(get_db)):
    t = db.get(ApiToken, token_id)
    if not t or t.user_id != p.user.id:
        raise HTTPException(404, "Not found")
    t.revoked = True
    audit.log(db, "token.revoked", p.user, target=t.name, ip=client_ip(request), commit=False)
    db.commit()
    return {"ok": True}
