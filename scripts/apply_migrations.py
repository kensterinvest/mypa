#!/usr/bin/env python3
"""Apply pending migrations under migrations/*.sql in lexical order.

Idempotent: each filename is recorded in schema_versions after success,
so re-runs skip already-applied files. New schema changes = drop a new
00N_*.sql file in migrations/ and run this.

Run as the mypa user; reads DB_PATH + SQLCIPHER_KEY from environment.
"""
from __future__ import annotations

import sys
from pathlib import Path

from mypa.db import engine


MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


def main() -> int:
    eng = engine()
    sql_files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    if not sql_files:
        print("no migrations found", file=sys.stderr)
        return 1

    # Ensure schema_versions exists so we can query it (chicken-and-egg —
    # 001_init.sql also creates it, but if it's the first time, we need
    # the table to record success).
    with eng.begin() as conn:
        from sqlalchemy import text
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_versions ("
            "filename TEXT PRIMARY KEY, "
            "applied_at DATETIME NOT NULL DEFAULT (datetime('now')))"
        ))

    # What's already applied?
    with eng.connect() as conn:
        from sqlalchemy import text
        applied = {
            row[0] for row in conn.execute(text("SELECT filename FROM schema_versions"))
        }

    pending = [f for f in sql_files if f.name not in applied]
    if not pending:
        print("no pending migrations")
        return 0

    for f in pending:
        print(f"applying {f.name}…", end=" ", flush=True)
        raw = f.read_text(encoding="utf-8")
        # Strip `--` comment lines first — they may contain `;` and confuse
        # the naive splitter below.
        sql = "\n".join(
            line for line in raw.splitlines()
            if not line.lstrip().startswith("--")
        )
        with eng.begin() as conn:
            from sqlalchemy import text
            for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                conn.execute(text(stmt))
            conn.execute(
                text("INSERT INTO schema_versions (filename) VALUES (:n)"),
                {"n": f.name},
            )
        print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
