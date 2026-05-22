#!/usr/bin/env python3
"""Backfill ntfy accounts for users who existed before migration 006.

Idempotent: skips users that already have notify_token set. For each
user without a token, creates an ntfy account (username = their topic)
and stores the generated password in users.notify_token.
"""
from sqlalchemy import text

from mypa import ntfy_admin
from mypa.db import session_factory


def main() -> int:
    Session = session_factory()
    with Session() as db:
        rows = db.execute(text(
            "SELECT id, email, notify_topic, notify_token FROM users "
            "WHERE notify_topic IS NOT NULL"
        )).fetchall()
        for uid, email, topic, token in rows:
            if token:
                print(f"  skip {email!s} — already has ntfy account")
                continue
            try:
                pw = ntfy_admin.create_user_for_topic(topic)
            except ntfy_admin.NtfyAdminError as e:
                # Likely "user already exists" from a partial backfill —
                # rotate password to take ownership of the existing account.
                print(f"  {email}: create_user failed ({e}); trying rotate")
                pw = ntfy_admin.rotate_password_for_topic(topic)
            db.execute(
                text("UPDATE users SET notify_token = :p WHERE id = :i"),
                {"p": pw, "i": uid},
            )
            db.commit()
            print(f"  provisioned {email}: username={topic}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
