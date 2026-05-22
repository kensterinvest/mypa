"""Append-only JSON-lines audit log for the MCP layer.

Every MCP tool call gets one line. Daily rotation handled by logrotate
externally. Designed for grep-friendly forensics after any incident.
"""
from __future__ import annotations

import json
import os
import time
from contextvars import ContextVar
from pathlib import Path

from .settings import settings


# Tracked per-request: set by middleware, read by audit() + MCP tools.
_remote_ip: ContextVar[str] = ContextVar("remote_ip", default="?")
_token_scope: ContextVar[str] = ContextVar("token_scope", default="?")
_user_id: ContextVar[int | None] = ContextVar("user_id", default=None)


def set_request_context(ip: str, scope: str, user_id: int | None = None) -> None:
    _remote_ip.set(ip or "?")
    _token_scope.set(scope or "?")
    _user_id.set(user_id)


def current_user_id() -> int | None:
    """Read the per-request user_id set by middleware. MCP tools use this
    to scope every service call to the calling user, defending against
    cross-tenant access on the MCP surface (parallel to REST's
    request.state.user_id pattern).
    """
    return _user_id.get()


def audit(tool: str, args: dict, result_summary: str = "ok", exit_code: int = 0) -> None:
    """Append one JSON-lines entry. Safe to call from any thread/task."""
    s = settings()
    path = Path(s.audit_log_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ip": _remote_ip.get(),
        "scope": _token_scope.get(),
        "user_id": _user_id.get(),
        "tool": tool,
        "args": _redact(args),
        "result": (result_summary or "")[:200],
        "exit": exit_code,
        "pid": os.getpid(),
    }
    line = json.dumps(entry, ensure_ascii=False, default=str)
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # Audit failures must NEVER break the API — fall back to stderr
        import sys
        print(f"AUDIT-LOG-FAIL {line}", file=sys.stderr)


_REDACT_KEYS = {"body", "image", "image_b64", "audio", "credentials"}
# Any key containing one of these substrings is also redacted — catches things
# we didn't think of by name (api_key, refresh_token, etc.).
_REDACT_SUBSTRINGS = ("password", "secret", "token", "_key", "credential")


def _is_sensitive(key: str) -> bool:
    if key in _REDACT_KEYS:
        return True
    lower = key.lower()
    return any(s in lower for s in _REDACT_SUBSTRINGS)


def _redact(args: dict) -> dict:
    """Truncate / drop high-volume or sensitive fields from audit args."""
    out = {}
    for k, v in (args or {}).items():
        if _is_sensitive(k):
            out[k] = f"<redacted {type(v).__name__}>"
            continue
        if isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + "…"
        else:
            out[k] = v
    return out
