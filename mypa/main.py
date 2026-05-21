"""MyPA FastAPI entrypoint.

Wires bearer middleware + (later) routers + lifespan + MCP server.
Run via systemd:
  uvicorn mypa.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

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
    # Touch the engine — surfaces SQLCipher key issues at startup, not first
    # request.
    engine()
    yield


app = FastAPI(title="MyPA", version=__version__, lifespan=lifespan)
app.middleware("http")(bearer_auth_middleware)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "mypa", "version": __version__}


# Routers
from .routes import items as items_routes  # noqa: E402
from .routes import reminders as reminders_routes  # noqa: E402
from .routes import search as search_routes  # noqa: E402

app.include_router(items_routes.router)
app.include_router(reminders_routes.router)
app.include_router(search_routes.router)

# MCP mount happens via mypa.mcp_server when run as the MCP service.
