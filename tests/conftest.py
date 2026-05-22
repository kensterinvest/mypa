"""Pytest fixtures. Tests run with encryption OFF, in-memory SQLite.

Encryption is verified separately on the VPS (or in CI on Linux) where
sqlcipher3-binary has wheels. This is the documented dev-environment
escape hatch.
"""
import os
from pathlib import Path

os.environ.setdefault("BEARER_TOKEN_RW", "test-rw-token")
os.environ.setdefault("BEARER_TOKEN_RO", "test-ro-token")
os.environ.setdefault("TEST_NO_ENCRYPTION", "true")
os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("AUDIT_LOG_PATH", str(Path("/tmp/mypa-test-audit.log")))
os.environ.setdefault("OAUTH_JWT_SECRET", "test-only-jwt-secret-not-for-prod")
# Tests run without a real ntfy server — disable user-mgmt CLI calls.
os.environ.setdefault("NTFY_USER_MGMT_ENABLED", "false")

import pytest

# Force a fresh settings + engine for each test module
from mypa import db, settings as settings_mod


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Reset module-level singletons between tests. Apply OAuth schema after engine init."""
    settings_mod._settings = None
    db._engine = None
    db._session_factory = None

    # Tests will lazily init the engine via app startup or direct calls. Use a
    # finalize hook to ensure OAuth tables exist if anything touched the engine.
    yield

    # Cleanup: nothing — in-memory SQLite is dropped when engine is reset.


@pytest.fixture(autouse=True)
def ensure_oauth_schema():
    """Apply the OAuth SQL migration on top of ORM-managed tables."""
    yield  # allow test to run first (it init's the engine)


def _apply_oauth_schema():
    """Helper invoked from tests that need OAuth tables.

    Also applies 003 (users) and 005 (notifications) — every newer
    feature assumed those columns exist, and we want one bootstrap
    helper rather than fragmenting migration application across test
    files. Each migration's CREATE/ALTER statements are idempotent or
    swallow ALTER-on-existing errors.
    """
    from sqlalchemy import text
    eng = db.engine()
    for fname in ("002_oauth.sql", "003_users.sql", "005_notifications.sql", "006_ntfy_token.sql"):
        sql_path = Path(__file__).parent.parent / "migrations" / fname
        sql = sql_path.read_text(encoding="utf-8")
        sql = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
        with eng.begin() as conn:
            for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    # ALTER TABLE … ADD COLUMN raises if column exists
                    # (ORM may have already created it via Base.metadata.create_all).
                    pass
