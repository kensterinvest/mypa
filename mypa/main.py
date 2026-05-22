"""MyPA FastAPI entrypoint.

Wires bearer middleware + (later) routers + lifespan + MCP server.
Run via systemd:
  uvicorn mypa.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from . import __version__
from .auth import bearer_auth_middleware
from .db import engine
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast on missing required env
    s = settings()
    if not s.bearer_token_rw:
        raise SystemExit("BEARER_TOKEN_RW env var required")
    if not s.test_no_encryption and not s.sqlcipher_key:
        raise SystemExit(
            "SQLCIPHER_KEY env var required (or set TEST_NO_ENCRYPTION=true for dev)"
        )
    engine()
    _ensure_dashboard_client()
    yield


def _ensure_dashboard_client() -> None:
    """Insert a synthetic 'dashboard' row in oauth_clients so refresh tokens
    issued by /auth/login satisfy the FK constraint. Safe to run on every
    startup — INSERT OR IGNORE."""
    try:
        from sqlalchemy import text
        from .db import session_factory
        Session = session_factory()
        with Session() as db:
            db.execute(text(
                "INSERT OR IGNORE INTO oauth_clients "
                "(client_id, client_secret_hash, name, redirect_uris, scopes) "
                "VALUES ('dashboard', 'n/a', 'MyPA Dashboard (internal)', '', 'mypa:read mypa:write')"
            ))
            db.commit()
    except Exception:
        # oauth_clients table may not exist yet on bootstrap; that's OK.
        pass


# Rate limiting — Caddy doesn't ship rate_limit module on this build, so we
# enforce here. Bearer auth is still the primary defence; this caps damage
# from a stolen token. Key on (forwarded IP) when proxied, falling back to
# direct client.
def _rate_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return fwd or get_remote_address(request)


limiter = Limiter(key_func=_rate_key, default_limits=["60/minute"])

app = FastAPI(title="MyPA", version=__version__, lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.middleware("http")(bearer_auth_middleware)


@app.get("/health")
async def health() -> dict:
    """Liveness — the process is up. No DB check."""
    return {"status": "ok", "service": "mypa", "version": __version__}


@app.get("/health/ready")
async def ready() -> dict:
    """Readiness — DB is reachable. Returns 503 if a DB connection / SELECT fails."""
    from fastapi import HTTPException
    from sqlalchemy import text
    from .db import session_factory

    try:
        Session = session_factory()
        with Session() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"db unreachable: {exc.__class__.__name__}")
    return {"status": "ready", "service": "mypa", "version": __version__}


# Routers
from .routes import attachments as attachments_routes  # noqa: E402
from .routes import auth_routes  # noqa: E402
from .routes import items as items_routes  # noqa: E402
from .routes import oauth as oauth_routes  # noqa: E402
from .routes import reminders as reminders_routes  # noqa: E402
from .routes import search as search_routes  # noqa: E402

app.include_router(items_routes.router)
app.include_router(reminders_routes.router)
app.include_router(search_routes.router)
app.include_router(attachments_routes.router)
# OAuth router has paths at /.well-known/* and /oauth/* — mounted at root.
app.include_router(oauth_routes.router)
# Dashboard auth (email + password → JWT) at /auth/*
app.include_router(auth_routes.router)

# MCP mount happens via mypa.mcp_server when run as the MCP service.
