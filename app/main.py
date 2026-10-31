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

from .api import admin, auth, files
from .config import settings
from .db import SessionLocal, init_db
from .engine import worker
from .models import UserSession, now
from .security import BodyLimit, SecurityHeaders

log = logging.getLogger("renamer")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        db.execute(delete(UserSession).where(UserSession.expires_at < now()))
        db.commit()
    worker.start(settings.workers)
    yield
    worker.stop()


app = FastAPI(title="Smart File Renamer", lifespan=lifespan,
              docs_url="/api/docs" if settings.enable_docs else None, redoc_url=None,
              openapi_url="/api/openapi.json" if settings.enable_docs else None)

app.add_middleware(BodyLimit)
app.add_middleware(SecurityHeaders)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

app.include_router(auth.router)
app.include_router(files.router)
app.include_router(admin.router)


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
         "/account": "account.html"}


def _page(name: str):
    async def handler():
        return FileResponse(STATIC / name, headers={"Cache-Control": "no-cache"})
    return handler


for route, file in PAGES.items():
    app.add_api_route(route, _page(file), methods=["GET"], include_in_schema=False)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")
