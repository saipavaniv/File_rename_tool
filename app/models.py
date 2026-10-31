from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")          # user | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class UserSession(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)   # SHA-256; raw token only in the cookie
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(255), default="")


class ApiToken(Base):
    """Personal tokens for the browser extension. Stored hashed; shown once."""
    __tablename__ = "api_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class FileRecord(Base):
    """One analysed file. File *contents* are never stored, only names, fingerprint and fields."""
    __tablename__ = "files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[str] = mapped_column(String(16), default="web")       # web | extension
    original_name: Mapped[str] = mapped_column(String(255))
    suggested_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    final_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(16), default="")
    doc_type: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    party: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    doc_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="suggested")  # suggested | saved | blocked | error
    auto: Mapped[bool] = mapped_column(Boolean, default=False)
    fields_json: Mapped[str] = mapped_column(Text, default="{}")
    page_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, index=True)
    finalized_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class Correction(Base):
    """What the user changed. Used to improve rules and measure accuracy."""
    __tablename__ = "corrections"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    field: Mapped[str] = mapped_column(String(16))
    suggested: Mapped[str | None] = mapped_column(String(255), nullable=True)
    corrected: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Party(Base):
    """Customer / supplier master data (export from ERP)."""
    __tablename__ = "parties"
    __table_args__ = (UniqueConstraint("code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str] = mapped_column(String(60), default="")
    aliases: Mapped[str] = mapped_column(String(500), default="")     # ; separated
    domains: Mapped[str] = mapped_column(String(300), default="")     # ; separated
    kind: Mapped[str] = mapped_column(String(16), default="customer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class AuditLog(Base):
    """Append-only, hash-chained. Each row's HMAC covers the previous row's, so editing
    or deleting any entry breaks the chain and shows up in Admin > Audit > Verify."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(48), index=True)
    target: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="{}")
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    hash: Mapped[str] = mapped_column(String(64))
