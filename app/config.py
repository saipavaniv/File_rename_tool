"""Configuration from environment variables (or a .env file next to run.py)."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))


def _load_env_file():
    f = BASE_DIR / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file()


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Settings:
    database_url: str = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'renamer.db'}")
    cookie_secure: bool = _bool("COOKIE_SECURE", True)
    session_hours: int = int(os.environ.get("SESSION_HOURS", "8"))
    idle_minutes: int = int(os.environ.get("IDLE_MINUTES", "60"))
    allowed_hosts: list[str] = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
    max_upload_mb: int = int(os.environ.get("MAX_UPLOAD_MB", "50"))
    workers: int = int(os.environ.get("ANALYSIS_WORKERS", "2"))
    analysis_timeout: int = int(os.environ.get("ANALYSIS_TIMEOUT", "90"))
    enable_docs: bool = _bool("ENABLE_API_DOCS", False)
    login_max_fails: int = int(os.environ.get("LOGIN_MAX_FAILS", "5"))
    lock_minutes: int = int(os.environ.get("LOCK_MINUTES", "15"))
    trust_proxy: bool = _bool("TRUST_PROXY", False)

    @property
    def cookie_name(self) -> str:
        # __Host- prefix: browser refuses the cookie unless Secure, Path=/ and no Domain -> no subdomain tricks
        return "__Host-krn_session" if self.cookie_secure else "krn_session"


settings = Settings()


def secret_key() -> bytes:
    """Key used to seal the audit log. Created once, readable only by the service account."""
    env = os.environ.get("AUDIT_KEY")
    if env:
        return env.encode()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = DATA_DIR / "audit.key"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
    return f.read_text().strip().encode()
