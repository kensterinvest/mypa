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

import pytest

# Force a fresh settings + engine for each test module
from mypa import db, settings as settings_mod


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Reset module-level singletons between tests."""
    settings_mod._settings = None
    db._engine = None
    db._session_factory = None
    yield
