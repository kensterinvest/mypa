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


# Tracked per-request: set by middleware, read by audit().
_remote_ip: ContextVar[str] = ContextVar("remote_ip", default="?")
_token_scope: ContextVar[str] = ContextVar("token_scope", default="?")


def set_request_context(ip: str, scope: str) -> None:
    _remote_ip.set(ip or "?")
    _token_scope.set(scope or "?")


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


def _redact(args: dict) -> dict:
    """Truncate / drop high-volume or sensitive fields from audit args."""
    out = {}
    for k, v in (args or {}).items():
        if k in _REDACT_KEYS:
            out[k] = f"<redacted {type(v).__name__}>"
            continue
        if isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + "…"
        else:
            out[k] = v
    return out
