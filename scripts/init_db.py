#!/usr/bin/env python3
"""Initialize the MyPA database — creates tables if missing.

Idempotent: safe to re-run; create_all() skips existing tables.
Reads SQLCIPHER_KEY (or TEST_NO_ENCRYPTION) from env via settings.
"""
from mypa.db import Base, engine
from mypa import models  # noqa: F401  -- import registers Item/Reminder on Base.metadata


def main() -> int:
    eng = engine()
    Base.metadata.create_all(eng)
    # Smoke: list tables
    from sqlalchemy import inspect
    tables = sorted(inspect(eng).get_table_names())
    print(f"OK — tables: {tables}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
