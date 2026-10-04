"""SQL migration helpers shared by scripts/apply_migrations.py and tests."""
from __future__ import annotations

import sqlite3


def split_sql(script: str) -> list[str]:
    """Split a SQL script into complete statements.

    Uses SQLite's own parser (sqlite3.complete_statement), so semicolons
    inside string literals, comments and CREATE TRIGGER ... BEGIN ... END
    bodies don't split a statement. `--` comment-only lines are dropped.
    """
    statements: list[str] = []
    buf: list[str] = []
    for line in script.splitlines():
        if not buf and (not line.strip() or line.lstrip().startswith("--")):
            continue
        buf.append(line)
        candidate = "\n".join(buf)
        if sqlite3.complete_statement(candidate):
            stmt = candidate.strip().rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail and not all(l.lstrip().startswith("--") or not l.strip() for l in buf):
        statements.append(tail)
    return statements
