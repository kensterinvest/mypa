"""User accounts — multi-tenant within one deployment.

Each install (family/small-org) has an admin (the operator) who provisions
other users via CLI. Each user has email + password; OAuth /authorize asks
for those; JWT issued with `sub=<user_id>`. All service-layer queries
scope by `user_id`.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str | None
    is_admin: bool
    created_at: datetime | None
    last_login_at: datetime | None
    disabled_at: datetime | None


# ----- password hashing -----------------------------------------------------
#
# scrypt — built-in to hashlib, no extra deps. Parameters tuned for ~50ms
# per check on modern hardware; not as strong as Argon2 but vastly better
# than plain hashes.

_SCRYPT_N = 2 ** 14    # 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64


def hash_password(password: str) -> str:
    """Return 'scrypt:N$R$P$salt_b64$hash_b64'. Constant-time-comparable."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
    )
    return (
        f"scrypt:{_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}$"
        f"{secrets.token_urlsafe(0)}{salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against the stored hash. Constant-time."""
    try:
        algo, rest = stored.split(":", 1)
        if algo != "scrypt":
            return False
        params_n, params_r, params_p, salt_hex, hash_hex = rest.split("$")
        n, r, p = int(params_n), int(params_r), int(params_p)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        computed = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt, n=n, r=r, p=p, dklen=len(expected),
        )
        return hmac.compare_digest(expected, computed)
    except (ValueError, IndexError):
        return False


# ----- CRUD -----------------------------------------------------------------

def _row_to_user(row) -> User:
    return User(
        id=row[0],
        email=row[1],
        name=row[2],
        is_admin=bool(row[3]),
        created_at=datetime.fromisoformat(row[4]) if row[4] else None,
        last_login_at=datetime.fromisoformat(row[5]) if row[5] else None,
        disabled_at=datetime.fromisoformat(row[6]) if row[6] else None,
    )


def _select_user(db: Session, *, email: str | None = None, user_id: int | None = None) -> User | None:
    if email is None and user_id is None:
        raise ValueError("provide email or user_id")
    if user_id is not None:
        row = db.execute(
            text("SELECT id, email, name, is_admin, created_at, last_login_at, disabled_at "
                 "FROM users WHERE id = :i"),
            {"i": user_id},
        ).fetchone()
    else:
        row = db.execute(
            text("SELECT id, email, name, is_admin, created_at, last_login_at, disabled_at "
                 "FROM users WHERE lower(email) = lower(:e)"),
            {"e": email},
        ).fetchone()
    return _row_to_user(row) if row else None


def create_user(
    db: Session, email: str, password: str, name: str | None = None, is_admin: bool = False,
    tz: str = "Europe/London",
) -> User:
    """Create a new user. Returns the created User (without the password).
    Auto-assigns a random `notify_topic` (16 hex chars) for ntfy push;
    rotatable later via rotate_notify_topic().
    """
    if not email or "@" not in email:
        raise ValueError("email must contain '@'")
    if len(password) < 8:
        raise ValueError("password must be at least 8 chars")
    existing = _select_user(db, email=email)
    if existing is not None:
        raise ValueError(f"user with email {email!r} already exists")
    topic = "u-" + secrets.token_hex(8)  # 16 hex chars after "u-" — practical privacy
    db.execute(
        text("INSERT INTO users (email, password_hash, name, is_admin, tz, notify_topic) "
             "VALUES (:e, :h, :n, :a, :tz, :t)"),
        {"e": email.lower(), "h": hash_password(password), "n": name,
         "a": 1 if is_admin else 0, "tz": tz, "t": topic},
    )
    db.commit()
    user = _select_user(db, email=email)
    assert user is not None
    return user


def rotate_notify_topic(db: Session, user_id: int) -> str:
    """Generate a new random topic, store it, return the new value.
    Existing mobile subscribers to the old topic stop receiving messages."""
    topic = "u-" + secrets.token_hex(8)
    db.execute(
        text("UPDATE users SET notify_topic = :t WHERE id = :i"),
        {"t": topic, "i": user_id},
    )
    db.commit()
    return topic


def get_notify_settings(db: Session, user_id: int) -> dict:
    """Read the user's tz + topic + parsed prefs JSON. Returns sensible
    defaults for any missing keys."""
    import json
    row = db.execute(
        text("SELECT tz, notify_topic, notify_prefs FROM users WHERE id = :i"),
        {"i": user_id},
    ).fetchone()
    if row is None:
        return {}
    tz, topic, prefs_raw = row
    try:
        prefs = json.loads(prefs_raw) if prefs_raw else {}
    except json.JSONDecodeError:
        prefs = {}
    # Merge with defaults
    defaults = {
        "realtime": True,
        "digest_enabled": True,
        "digest_hour": 7,
        "overdue_weekly_enabled": False,
        "overdue_day": 0,
        "overdue_hour": 9,
    }
    defaults.update(prefs)
    return {"tz": tz or "Etc/UTC", "topic": topic, "prefs": defaults}


def set_notify_prefs(db: Session, user_id: int, patch: dict) -> dict:
    """Merge `patch` into the user's notify_prefs JSON. Returns the new
    full settings (via get_notify_settings)."""
    import json
    current = get_notify_settings(db, user_id)
    if not current:
        raise ValueError("user not found")
    new_prefs = {**current["prefs"], **patch}
    # tz is stored as a separate column for index-ability — handle if passed
    if "tz" in patch:
        db.execute(
            text("UPDATE users SET tz = :tz WHERE id = :i"),
            {"tz": patch["tz"], "i": user_id},
        )
        new_prefs.pop("tz", None)  # don't store in JSON
    db.execute(
        text("UPDATE users SET notify_prefs = :p WHERE id = :i"),
        {"p": json.dumps(new_prefs), "i": user_id},
    )
    db.commit()
    return get_notify_settings(db, user_id)


def authenticate(db: Session, email: str, password: str) -> User | None:
    """Return the User if credentials match and account is not disabled."""
    row = db.execute(
        text("SELECT id, password_hash, disabled_at FROM users WHERE lower(email) = lower(:e)"),
        {"e": email},
    ).fetchone()
    if row is None:
        return None
    user_id, stored, disabled = row
    if disabled is not None:
        return None
    if not verify_password(password, stored):
        return None
    db.execute(
        text("UPDATE users SET last_login_at = datetime('now') WHERE id = :i"),
        {"i": user_id},
    )
    db.commit()
    return _select_user(db, user_id=user_id)


def get_user(db: Session, user_id: int) -> User | None:
    return _select_user(db, user_id=user_id)


def get_admin_user(db: Session) -> User | None:
    """Return the lowest-id admin user — used for static-bearer auth + backfill."""
    row = db.execute(
        text("SELECT id FROM users WHERE is_admin = 1 AND disabled_at IS NULL "
             "ORDER BY id ASC LIMIT 1")
    ).fetchone()
    return _select_user(db, user_id=row[0]) if row else None


def list_users(db: Session) -> list[User]:
    rows = db.execute(
        text("SELECT id, email, name, is_admin, created_at, last_login_at, disabled_at "
             "FROM users ORDER BY id ASC")
    ).fetchall()
    return [_row_to_user(r) for r in rows]


def disable_user(db: Session, user_id: int) -> bool:
    r = db.execute(
        text("UPDATE users SET disabled_at = datetime('now') WHERE id = :i AND disabled_at IS NULL"),
        {"i": user_id},
    )
    db.commit()
    return r.rowcount > 0
