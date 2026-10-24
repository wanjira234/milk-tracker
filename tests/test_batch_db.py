"""db.batch(): one connection, all-or-nothing. Need TEST_DATABASE_URL."""
import os

import psycopg2
import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import db, demo_seed  # noqa: E402


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, alerts, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes RESTART IDENTITY CASCADE")


@pytest.fixture
def connects(monkeypatch):
    calls = []
    real = psycopg2.connect

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(psycopg2, "connect", counting)
    return calls


def test_many_queries_in_a_batch_use_one_connection(connects):
    with db.batch():
        for i in range(5):
            db.add_farmer(f"F{i}", f"+25470000010{i}")
    assert len(connects) == 1 and len(db.list_farmers()) == 5
    before = len(connects)
    for i in range(3):
        db.list_farmers()
    assert len(connects) <= before + 1  # outside a batch, queries reuse pooled connections instead of reconnecting


def test_a_failure_inside_a_batch_undoes_everything():
    with pytest.raises(RuntimeError):
        with db.batch():
            db.add_farmer("Ghost", "+254700000199")
            raise RuntimeError("stop")
    assert db.list_farmers() == []


def test_a_batch_commits_on_success_and_nested_batches_join_the_outer_one(connects):
    with db.batch():
        with db.batch():
            db.add_farmer("A", "+254700000101")
        db.add_farmer("B", "+254700000102")
    assert len(connects) == 1 and len(db.list_farmers()) == 2


def test_the_shared_connection_is_released_afterwards(connects):
    with db.batch():
        db.add_farmer("A", "+254700000101")
    assert getattr(db._local, "conn", None) is None
    db.add_farmer("B", "+254700000102")
    assert len(connects) <= 2  # the batch's own connection, plus at most one pooled one


def test_the_demo_seed_runs_on_a_single_connection_and_leaves_nothing_behind_if_it_fails(connects, monkeypatch):
    assert demo_seed.main(ask=lambda p: "demo") == 0
    assert len(connects) == 1 and len(db.list_users()) == 3 and len(db.list_farmers()) == 1
    db._query("TRUNCATE farmers, users, routes RESTART IDENTITY CASCADE")
    monkeypatch.setattr(demo_seed, "seed_farm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cut off midway")))
    with pytest.raises(RuntimeError):
        demo_seed.main(ask=lambda p: "demo")
    assert db.list_users() == [] and db.list_farmers() == [] and db.list_routes() == []  # nothing half-seeded
