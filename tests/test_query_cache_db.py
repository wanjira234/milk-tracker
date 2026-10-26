"""Reads are cached briefly, writes through the app clear the cache, and a dropped connection is survived. Need TEST_DATABASE_URL."""
import os

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import db  # noqa: E402


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes RESTART IDENTITY CASCADE")
    db.clear_cache()


def test_a_repeat_read_is_served_from_memory_and_a_write_refreshes_it(monkeypatch):
    fid = db.add_farmer("Wanjiru", "+254700000001", "Green Farm")
    calls = []
    real = db._run_pooled
    monkeypatch.setattr(db, "_run_pooled", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert db.get_farmer(fid)["name"] == "Wanjiru"
    assert db.get_farmer(fid)["name"] == "Wanjiru"
    assert len(calls) == 1  # second read never reached the database
    db.add_farmer("Wanjiru K", "+254700000001")  # a write through the app
    assert db.get_farmer(fid)["name"] == "Wanjiru K"  # no stale answer


def test_changing_a_cached_result_does_not_change_the_cache():
    fid = db.add_farmer("Wanjiru", "+254700000001")
    db.get_farmer(fid)["name"] = "tampered"
    assert db.get_farmer(fid)["name"] == "Wanjiru"


def test_a_connection_the_server_dropped_is_replaced_for_reads():
    fid = db.add_farmer("Wanjiru", "+254700000001")
    db.clear_cache()
    pool = db._get_pool()
    conn = pool.getconn()
    db._last_used[id(conn)] = 0
    pool.putconn(conn)
    conn.close()  # as if the server closed it while idle
    assert db.get_farmer(fid)["name"] == "Wanjiru"
