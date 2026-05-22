"""ntfy user-management wrapper.

Each MyPA user gets a dedicated ntfy account with read access to their
topic only. mypa-api uses the system `ntfy` CLI via a narrow sudoers
entry; the ntfy server.yml has `auth-default-access: deny-all` so
unauthenticated requests are 403'd.

Why CLI not HTTP admin API: ntfy's user-mgmt HTTP surface is sparse
and version-volatile; the CLI is stable and battle-tested. The
sudoers entry is restricted to `ntfy user add|remove`, `ntfy access`,
and `ntfy token` subcommands only.
"""
from __future__ import annotations

import logging
import os
import secrets
import subprocess

log = logging.getLogger(__name__)


class NtfyAdminError(RuntimeError):
    pass


def _run(args: list[str], *, env_extra: dict[str, str] | None = None,
         check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a `sudo -n ntfy ...` command. Returns CompletedProcess.

    `sudo -n` = non-interactive: fails if password would be needed.
    Sudoers grants mypa user passwordless access to the relevant
    subcommands only.
    """
    cmd = ["sudo", "-n", "ntfy", *args]
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    try:
        return subprocess.run(
            cmd, env=env, check=check,
            capture_output=capture, text=True,
            timeout=10,
        )
    except subprocess.CalledProcessError as e:
        log.error("ntfy admin: %s failed (rc=%s) stderr=%s",
                  " ".join(args), e.returncode, e.stderr)
        if check:
            raise NtfyAdminError(f"ntfy {' '.join(args)} failed: {e.stderr}") from e
        return e
    except FileNotFoundError as e:
        raise NtfyAdminError("ntfy CLI not on PATH") from e


def _gen_password() -> str:
    """ntfy passwords just need to be unguessable; 24 url-safe chars."""
    return secrets.token_urlsafe(18)


def create_user_for_topic(topic: str) -> str:
    """Create an ntfy user named after the topic + grant read on the
    topic. Returns the generated password (caller persists it to
    users.notify_token).

    The username == the topic name; this is a deliberate convention
    so `rotate` / `delete` operations only need the topic.
    """
    password = _gen_password()
    _run(["user", "add", topic], env_extra={"NTFY_PASSWORD": password})
    _run(["access", topic, topic, "read-only"])
    return password


def delete_user_for_topic(topic: str) -> None:
    """Remove the ntfy user. Subsequent attempts to subscribe with
    those credentials are 401'd; this is true revocation."""
    _run(["user", "remove", topic], check=False)


def rotate_password_for_topic(topic: str) -> str:
    """Set a new password on an existing ntfy user. Old password stops
    working immediately. Returns the new password.

    Used when a user wants to invalidate a leaked password without
    rotating their topic (e.g. shared with the wrong person but the
    topic itself isn't sensitive).
    """
    password = _gen_password()
    _run(["user", "change-pass", topic], env_extra={"NTFY_PASSWORD": password})
    return password
