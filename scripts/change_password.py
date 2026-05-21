#!/usr/bin/env python3
"""Change a user's password.

Two modes:
  - Operator changes a user's password (no current-password check):
      python scripts/change_password.py alice@example.com
  - User changes their own (must provide current password):
      python scripts/change_password.py alice@example.com --self

Prompts for the new password (and current, if --self).
"""
import argparse
import getpass
import sys

from sqlalchemy import text

from mypa.db import session_factory
from mypa.users import authenticate, hash_password, verify_password


def main() -> int:
    parser = argparse.ArgumentParser(description="Change a MyPA user's password")
    parser.add_argument("email")
    parser.add_argument("--self", action="store_true",
                        help="User changing own password (current password required)")
    args = parser.parse_args()

    Session = session_factory()
    with Session() as db:
        if args.self:
            current = getpass.getpass("Current password: ")
            user = authenticate(db, args.email, current)
            if user is None:
                print("ERROR: wrong email or password", file=sys.stderr)
                return 1
        else:
            row = db.execute(
                text("SELECT id FROM users WHERE lower(email) = lower(:e)"),
                {"e": args.email},
            ).fetchone()
            if row is None:
                print(f"ERROR: no user with email {args.email}", file=sys.stderr)
                return 1
            user_id = row[0]

        new = getpass.getpass("New password (8+ chars): ")
        confirm = getpass.getpass("Confirm new password: ")
        if new != confirm:
            print("ERROR: passwords don't match", file=sys.stderr)
            return 1
        if len(new) < 8:
            print("ERROR: must be at least 8 chars", file=sys.stderr)
            return 1

        target_id = user.id if args.self else user_id
        db.execute(
            text("UPDATE users SET password_hash = :h WHERE id = :i"),
            {"h": hash_password(new), "i": target_id},
        )
        db.commit()

    print(f"Password updated for {args.email}.")
    print("Existing JWTs continue to work until they expire (1h max).")
    print("To force immediate invalidation, rotate OAUTH_JWT_SECRET.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
