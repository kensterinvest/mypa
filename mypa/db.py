"""SQLAlchemy engine factory.

Encryption strategy:
- Production (Linux, VPS): SQLCipher via `sqlcipher3-binary` driver.
  Key set via PRAGMA on every connection.
- Dev/Windows: plain SQLite when `MYPA_TEST_NO_ENCRYPTION=true` (no
  Windows wheel for sqlcipher3-binary on recent Python; design decision
  documented in master plan §Other practical considerations).
- Tests: in-memory SQLite, encryption off.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from .settings import settings


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base for all models."""


def _build_engine() -> Engine:
    s = settings()

    if s.test_no_encryption:
        # Dev path — plain SQLite. Same schema, same code paths.
        is_memory = str(s.db_path) in (":memory:", "memory")
        url = "sqlite:///:memory:" if is_memory else f"sqlite:///{s.db_path}"
        kwargs: dict = {"future": True, "echo": False}
        if is_memory:
            # All connections must share the same DB — otherwise tables
            # created in one connection vanish in the next.
            kwargs["poolclass"] = StaticPool
            kwargs["connect_args"] = {"check_same_thread": False}
        engine = create_engine(url, **kwargs)
        return engine

    # Production path — SQLCipher.
    # sqlcipher3-binary provides a `sqlcipher3` module that mimics sqlite3 API.
    # SQLAlchemy supports it via the `sqlite+pysqlcipher` dialect, but the
    # simpler reliable path on modern SQLAlchemy is the `creator` callback:
    # we supply our own DB connection factory using sqlcipher3.
    import sqlcipher3  # noqa: F401  -- import asserts availability

    def _connect():
        conn = sqlcipher3.connect(str(s.db_path), check_same_thread=False)
        # Set the key first thing — SQLCipher rejects any other operation
        # before PRAGMA key.
        if not s.sqlcipher_key:
            raise SystemExit(
                "SQLCIPHER_KEY env var required when test_no_encryption=False"
            )
        # NB: identifier-style quoting via PRAGMA key = "x'<hex>'" allows
        # binary keys, but the simple string form works for passphrase keys.
        conn.execute(f"PRAGMA key = '{s.sqlcipher_key}'")
        # Tune SQLCipher to defaults documented in the master plan.
        conn.execute("PRAGMA cipher_compatibility = 4")
        conn.execute("PRAGMA kdf_iter = 256000")
        return conn

    # Use plain `sqlite://` dialect with a custom creator — that way
    # SQLAlchemy doesn't try to set PRAGMA key from URL credentials (which
    # would conflict with our creator-managed key). sqlcipher3 is API-
    # compatible with sqlite3, so the standard sqlite dialect works.
    engine = create_engine(
        "sqlite://",
        creator=_connect,
        future=True,
        echo=False,
        # connect-time pragma already set by _connect; events below are safe to run
    )
    return engine


_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def engine() -> Engine:
    """Return the lazily-initialized SQLAlchemy engine."""
    global _engine, _session_factory
    if _engine is None:
        _engine = _build_engine()
        _session_factory = sessionmaker(
            bind=_engine, expire_on_commit=False, autoflush=False
        )

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys = ON")
            cur.execute("PRAGMA journal_mode = WAL")
            cur.close()

    return _engine


def session_factory() -> sessionmaker:
    """Return the session factory (initializes engine on first call)."""
    engine()
    assert _session_factory is not None
    return _session_factory


def get_session():
    """Yield a SQLAlchemy session — used as a FastAPI Depends."""
    Session = session_factory()
    db = Session()
    try:
        yield db
    finally:
        db.close()
