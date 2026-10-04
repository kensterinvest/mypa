"""The MCP endpoint speaks Streamable HTTP at /mcp, with /sse kept as a
legacy alias (public https://<host>/mcp/sse → Caddy strips → /sse)."""
import pytest
from fastapi.testclient import TestClient

from mypa import mcp_server as mcp_mod
from tests.conftest import make_admin

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
HEADERS = {
    "Authorization": "Bearer test-rw-token",
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Host": "localhost",
}


@pytest.fixture(scope="module")
def client():
    # The Streamable HTTP session manager can only be started once per
    # process, so all tests share one lifespan.
    with TestClient(mcp_mod.app, base_url="http://localhost") as c:
        yield c


@pytest.mark.parametrize("path", ["/mcp", "/sse"])
def test_streamable_http_initialize(client, path):
    make_admin()  # the in-memory DB is reset per test
    r = client.post(path, json=INIT, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.headers.get("mcp-session-id")
    assert '"serverInfo"' in r.text and '"mypa"' in r.text


def test_mcp_requires_auth(client):
    h = {k: v for k, v in HEADERS.items() if k != "Authorization"}
    r = client.post("/mcp", json=INIT, headers=h)
    assert r.status_code == 401
