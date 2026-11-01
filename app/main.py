from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api import admin, auth, files, pair
from .config import settings
from .db import SessionLocal, init_db
from .engine import worker
from .models import UserSession, now
from .security import BodyLimit, SecurityHeaders

log = logging.getLogger("renamer")
STATIC = Path(__file__).parent / "static"


def _bootstrap_admin(db):
    """First start in the cloud: create the admin from ADMIN_USERNAME / ADMIN_PASSWORD (only if no users exist)."""
    import os

    from sqlalchemy import func, select

    from . import audit
    from .models import User
    from .security import hash_password, password_problems
    pw = os.environ.get("ADMIN_PASSWORD", "")
    if not pw or db.execute(select(func.count()).select_from(User)).scalar_one() > 0:
        return
    name = os.environ.get("ADMIN_USERNAME", "admin").strip().lower() or "admin"
    problem = password_problems(pw, name)
    if problem:
        log.error("ADMIN_PASSWORD not accepted: %s", problem)
        return
    u = User(username=name, display_name=name, role="admin", password_hash=hash_password(pw), must_change_password=False)
    db.add(u)
    db.flush()
    audit.log(db, "admin.created_env", u, target=name, ip="startup")
    log.warning("Created administrator '%s' from ADMIN_PASSWORD. You can remove that variable now.", name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        db.execute(delete(UserSession).where(UserSession.expires_at < now()))
        db.commit()
        _bootstrap_admin(db)
    worker.start(settings.workers)
    yield
    worker.stop()


app = FastAPI(title="Smart File Renamer", lifespan=lifespan,
              docs_url="/api/docs" if settings.enable_docs else None, redoc_url=None,
              openapi_url="/api/openapi.json" if settings.enable_docs else None)

app.add_middleware(BodyLimit)
app.add_middleware(SecurityHeaders)
class _HostCheck(TrustedHostMiddleware):
    """Refuse unknown Host headers, except for the health check the hosting platform calls internally."""
    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/api/health":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


app.add_middleware(_HostCheck, allowed_hosts=settings.allowed_hosts)

app.include_router(auth.router)
app.include_router(files.router)
app.include_router(admin.router)
app.include_router(pair.router)


@app.exception_handler(RequestValidationError)
async def _validation(request: Request, exc: RequestValidationError):
    msgs = []
    for e in exc.errors()[:3]:
        loc = ".".join(str(x) for x in e.get("loc", [])[1:])
        msgs.append(f"{loc}: {e.get('msg')}" if loc else e.get("msg"))
    return JSONResponse({"detail": "; ".join(msgs) or "Invalid input"}, status_code=422)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Something went wrong. The error was logged."}, status_code=500)


@app.get("/api/health")
def health():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC), name="static")

PAGES = {"/": "index.html", "/login": "login.html", "/history": "history.html", "/admin": "admin.html",
         "/account": "account.html", "/connect": "connect.html"}


def _page(name: str):
    async def handler():
        return FileResponse(STATIC / name, headers={"Cache-Control": "no-cache"})
    return handler


for route, file in PAGES.items():
    app.add_api_route(route, _page(file), methods=["GET"], include_in_schema=False)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")
