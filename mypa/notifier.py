"""Thin wrapper around the ntfy HTTP publish API.

The ntfy server runs at NTFY_BASE_URL (e.g. https://ntfy.z-tidus.com).
Each MyPA user has a random `notify_topic`; the publish URL is
NTFY_BASE_URL/<topic>. Anyone who knows the topic can subscribe —
privacy depends on the topic being unguessable. Topics are rotatable
if leaked.
"""
from __future__ import annotations

import logging

import httpx

from .settings import settings


log = logging.getLogger(__name__)


def publish(
    topic: str,
    *,
    message: str,
    title: str | None = None,
    priority: int | None = None,
    click_url: str | None = None,
    tags: list[str] | None = None,
) -> bool:
    """Publish one notification to a topic. Returns True on 200/202.

    Logs but never raises — a notification failure must not break the
    request flow that triggered it.
    """
    s = settings()
    base = (s.ntfy_base_url or "").rstrip("/")
    if not base or not topic:
        log.warning("ntfy not configured (base=%r topic=%r)", base, topic)
        return False

    url = f"{base}/{topic}"
    headers: dict[str, str] = {"Content-Type": "text/plain; charset=utf-8"}
    if title:
        try:
            title.encode("ascii")
            headers["Title"] = title
        except UnicodeEncodeError:
            from urllib.parse import quote
            headers["Title"] = quote(title)
    if priority is not None:
        # ntfy priorities: 1=min, 3=default, 5=max
        headers["Priority"] = str(max(1, min(5, priority)))
    if click_url:
        headers["Click"] = click_url
    if tags:
        headers["Tags"] = ",".join(tags)

    try:
        r = httpx.post(url, content=message.encode("utf-8"), headers=headers, timeout=5.0)
    except httpx.HTTPError as e:
        log.warning("ntfy publish error topic=%s err=%s", topic, e)
        return False
    if r.status_code not in (200, 202):
        log.warning("ntfy publish HTTP %s topic=%s body=%s", r.status_code, topic, r.text[:200])
        return False
    return True
