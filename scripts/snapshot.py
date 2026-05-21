#!/usr/bin/env python3
"""Encrypted snapshot of mypa.db via sqlcipher3 VACUUM INTO.

Run as mypa user. Reads DB_PATH + SQLCIPHER_KEY from environment;
writes to the destination path given on argv[1]. Output file inherits
the same cipher key.

Usage:
    sudo -u mypa /bin/bash -c "set -a; source /etc/mypa/env; set +a; \\
        /opt/mypa/.venv/bin/python /opt/mypa/scripts/snapshot.py /tmp/snap.db"
"""
import os
import sys

import sqlcipher3


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: snapshot.py <destination-path>", file=sys.stderr)
        return 2
    dest = sys.argv[1]
    db = os.environ["DB_PATH"]
    key = os.environ["SQLCIPHER_KEY"]

    con = sqlcipher3.connect(db)
    # Set the key — escape single-quotes in the key in case (improbable)
    safe_key = key.replace("'", "''")
    con.execute(f"PRAGMA key = '{safe_key}'")
    # VACUUM INTO acquires a read lock and produces a consistent encrypted copy.
    safe_dest = dest.replace("'", "''")
    con.execute(f"VACUUM INTO '{safe_dest}'")
    con.close()

    if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
        print(f"ERROR: destination missing or empty: {dest}", file=sys.stderr)
        return 1
    print(f"snapshot ok: {dest} ({os.path.getsize(dest)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
