#!/usr/bin/env python3
"""Verify a SQLCipher snapshot is restorable by opening it with the key
and counting items. Replaces the shell pattern of piping the key into
sqlcipher (which exposes it briefly via /proc/<pid>/cmdline).

Usage:
    sudo -u mypa /bin/bash -c "set -a; source /etc/mypa/env; set +a; \\
        /opt/mypa/.venv/bin/python /opt/mypa/scripts/verify_snapshot.py \\
        /srv/backups/mypa-snapshots/<date>/mypa.db"
"""
import os
import sys

import sqlcipher3


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_snapshot.py <path-to-snapshot.db>", file=sys.stderr)
        return 2
    path = sys.argv[1]
    key = os.environ["SQLCIPHER_KEY"]

    con = sqlcipher3.connect(path)
    safe_key = key.replace("'", "''")
    con.execute(f"PRAGMA key = '{safe_key}'")
    row = con.execute("SELECT COUNT(*) FROM items").fetchone()
    con.close()

    print(f"OK — {path} contains {row[0]} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
