"""FTS5 search + data{} filters (roadmap item 4)."""
from pathlib import Path

import pytest

from mypa import mcp_server as mcp_mod
from mypa.audit import set_request_context
from mypa.db import engine
from mypa.migrate import split_sql
from tests.conftest import make_admin


def _apply_fts():
    sql = (Path(__file__).parent.parent / "migrations" / "010_items_fts.sql").read_text()
    with engine().begin() as conn:
        for stmt in split_sql(sql):
            conn.exec_driver_sql(stmt)


@pytest.fixture
def uid():
    u = make_admin()
    set_request_context("ip", "rw", user_id=u)
    return u


def _titles(r):
    assert "error" not in r, r
    return [i["title"] for i in r["items"]]


def test_rebuild_indexes_existing_items(uid):
    mcp_mod.pa_add(kind="note", title="saved before the migration")
    _apply_fts()
    assert _titles(mcp_mod.pa_search("migration")) == ["saved before the migration"]


def test_title_hits_rank_above_body_hits(uid):
    _apply_fts()
    mcp_mod.pa_add(kind="note", title="Weekend plans", body="maybe get sushi")
    mcp_mod.pa_add(kind="place", title="Sushi Samba", body="rooftop")
    assert _titles(mcp_mod.pa_search("sushi")) == ["Sushi Samba", "Weekend plans"]


def test_stemming_prefix_and_diacritics(uid):
    _apply_fts()
    mcp_mod.pa_add(kind="note", title="Went running by the café")
    assert _titles(mcp_mod.pa_search("run"))
    assert _titles(mcp_mod.pa_search("caf"))
    assert _titles(mcp_mod.pa_search("cafe"))


def test_index_follows_updates_and_deletes(uid):
    _apply_fts()
    item = mcp_mod.pa_add(kind="note", title="old name")
    mcp_mod.pa_update(item["id"], title="new name")
    assert _titles(mcp_mod.pa_search("old")) == []
    assert _titles(mcp_mod.pa_search("new")) == ["new name"]
    mcp_mod.pa_delete(item["id"], confirm=True)
    assert _titles(mcp_mod.pa_search("new")) == []


def test_fts_syntax_in_query_is_harmless(uid):
    _apply_fts()
    mcp_mod.pa_add(kind="note", title="tom and jerry")
    for q in ['tom AND', 'NEAR(tom', '"tom', 'tom*', 'title:tom', '-tom']:
        assert "error" not in mcp_mod.pa_search(q), q
    assert mcp_mod.pa_search("!!!")["count"] == 0


def test_search_is_scoped_to_user(uid):
    _apply_fts()
    from mypa import users as users_lib
    from mypa.db import session_factory
    with session_factory()() as db:
        bob = users_lib.create_user(db, "bob@example.com", "bob-pw-1234567", name="B").id
    set_request_context("ip", "rw", user_id=bob)
    mcp_mod.pa_add(kind="note", title="bob secret")
    set_request_context("ip", "rw", user_id=uid)
    assert mcp_mod.pa_search("secret")["count"] == 0


@pytest.mark.parametrize("with_fts", [True, False])
def test_data_filters(uid, with_fts):
    if with_fts:
        _apply_fts()
    mcp_mod.pa_add(kind="place", title="Luigi's", data={"cuisine": "Italian", "rating": 5})
    mcp_mod.pa_add(kind="place", title="Mario's", data={"cuisine": "italian", "rating": 3})
    mcp_mod.pa_add(kind="place", title="Dishoom", data={"cuisine": "Indian", "rating": 5,
                                                        "address": {"city": "London"}})
    # "Which Italian places did I rate 5?"
    assert _titles(mcp_mod.pa_list(kind="place", where=["cuisine=italian", "rating>=5"])) == ["Luigi's"]
    assert sorted(_titles(mcp_mod.pa_list(where=["cuisine=ITALIAN"]))) == ["Luigi's", "Mario's"]
    assert _titles(mcp_mod.pa_list(where=["address.city~lond"])) == ["Dishoom"]
    assert sorted(_titles(mcp_mod.pa_list(where=["rating!=3"]))) == ["Dishoom", "Luigi's"]
    assert _titles(mcp_mod.pa_search("luigi", kind="place", where=["rating>4"])) == ["Luigi's"]
    assert "bad filter" in mcp_mod.pa_list(where=["rating >> 4"])["error"]
    assert "bad filter" in mcp_mod.pa_list(where=["x; DROP TABLE items=1"])["error"]
