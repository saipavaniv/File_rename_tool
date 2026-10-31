from __future__ import annotations

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATA_DIR, settings


class Base(DeclarativeBase):
    pass


_is_sqlite = settings.database_url.startswith("sqlite")
if _is_sqlite:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA secure_delete=ON")   # deleted rows are overwritten, not left on disk
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db():
    from . import models  # noqa: F401
    Base.metadata.create_all(engine)
    if _is_sqlite:
        db_file = settings.database_url.replace("sqlite:///", "")
        try:
            os.chmod(db_file, 0o600)   # only the service account can read the database file
        except OSError:
            pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
