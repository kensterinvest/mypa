#!/usr/bin/env python3
"""Register a new OAuth client for MyPA. Prints client_id + secret ONCE.

Usage:
    python scripts/oauth_register_client.py <name> <redirect_uri> [more_uris...]

Example (register Claude.ai):
    python scripts/oauth_register_client.py "claude.ai" \\
        "https://claude.ai/api/organizations/<org>/mcp/callback"
"""
import sys

from mypa.db import session_factory
from mypa.oauth import register_client


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    name = sys.argv[1]
    redirect_uris = sys.argv[2:]

    Session = session_factory()
    with Session() as db:
        client = register_client(db, name=name, redirect_uris=redirect_uris)

    print("=" * 64)
    print("OAuth client registered. Save the secret NOW — it won't be shown again.")
    print("=" * 64)
    print(f"  Name:          {client['name']}")
    print(f"  Client ID:     {client['client_id']}")
    print(f"  Client Secret: {client['client_secret']}")
    print(f"  Redirect URIs: {', '.join(client['redirect_uris'])}")
    print(f"  Scopes:        {client['scopes']}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
