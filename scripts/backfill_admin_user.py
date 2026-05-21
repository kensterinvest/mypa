#!/usr/bin/env python3
"""One-shot: assign all existing items + reminders to the admin user.

Run AFTER migration 003 lands on a previously-single-tenant deployment.
If no admin user exists yet, prompts to create one. If items already have
user_id set, leaves them alone.
"""
import getpass
import sys

from sqlalchemy import text

from mypa.db import session_factory
from mypa.users import create_user, get_admin_user


def main() -> int:
    Session = session_factory()
    with Session() as db:
        admin = get_admin_user(db)
        if admin is None:
            print("No admin user exists yet. Creating one now.")
            email = input("Admin email: ").strip()
            password = getpass.getpass("Admin password (8+ chars): ")
            name = input("Display name (optional): ").strip() or None
            try:
                admin = create_user(db, email, password, name=name, is_admin=True)
            except ValueError as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return 1
            print(f"Created admin user id={admin.id} email={admin.email}")

        # Backfill items / reminders that don't have a user_id yet.
        for table in ("items", "reminders"):
            r = db.execute(
                text(f"UPDATE {table} SET user_id = :u WHERE user_id IS NULL"),
                {"u": admin.id},
            )
            db.commit()
            print(f"  {table}: {r.rowcount} row(s) assigned to admin user {admin.id}")

        # Sanity check
        for table in ("items", "reminders"):
            row = db.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL")
            ).fetchone()
            if row[0] > 0:
                print(f"WARNING: {table} still has {row[0]} rows with NULL user_id", file=sys.stderr)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
