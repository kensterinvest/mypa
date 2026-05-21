#!/usr/bin/env python3
"""Provision a new MyPA user. Run as the operator after setup.sh.

Usage:
    python scripts/add_user.py alice@example.com [--admin]

If --password isn't given, a 16-character random password is generated.
The password is printed ONCE — the operator must save it (or pass it to
the new user via a secure channel).
"""
import argparse
import secrets
import sys

from mypa.db import session_factory
from mypa.users import create_user


def gen_password(length: int = 16) -> str:
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision a new MyPA user")
    parser.add_argument("email")
    parser.add_argument("--name", default=None, help="Display name (optional)")
    parser.add_argument("--admin", action="store_true", help="Make this user an admin")
    parser.add_argument("--password", default=None,
                        help="Set explicit password (default: generate 16 chars)")
    args = parser.parse_args()

    password = args.password or gen_password()

    Session = session_factory()
    with Session() as db:
        try:
            user = create_user(db, args.email, password, name=args.name, is_admin=args.admin)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1

    print("=" * 64)
    print("MyPA user created. Save the password NOW — it won't be shown again.")
    print("=" * 64)
    print(f"  Email:    {user.email}")
    print(f"  Name:     {user.name or '(none)'}")
    print(f"  Admin:    {'yes' if user.is_admin else 'no'}")
    print(f"  ID:       {user.id}")
    print(f"  Password: {password}")
    print("=" * 64)
    print("Share this with the user via a secure channel (password manager")
    print("share, encrypted DM, etc.). They'll use it to log in via the")
    print("OAuth /authorize page or the dashboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
