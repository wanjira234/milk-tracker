"""The daily job and weekly snapshot against a real Postgres, with fake Claude and SMS clients."""
import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import db  # noqa: E402
from src.dispatch import run_daily, run_weekly_snapshot  # noqa: E402
from tests.test_loader_db import TODAY, seed  # noqa: E402


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, model_snapshots, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers RESTART IDENTITY CASCADE")


class FakeSms:
    def __init__(self):
        self.sent = []

    def send(self, message, recipients, sender_id=None):
        self.sent.append((message, recipients))
        return {"SMSMessageData": {"Recipients": [{"statusCode": 101, "status": "Success", "messageId": f"ATX{len(self.sent)}"}]}}


class NoHaiku:  # a client whose API always fails, so the template goes out
    messages = SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(TimeoutError("down")))


def test_dry_run_sends_and_logs_nothing():
    seed()
    sms = FakeSms()
    rows = run_daily(TODAY, send=False, llm_client=NoHaiku(), sms_client=sms)
    assert [r["action"] for r in rows] == ["would_send"] and rows[0]["kind"] == "advice"
    assert sms.sent == [] and db._query("SELECT count(*) AS n FROM sms_log", one=True)["n"] == 0


def stamp(day):
    """Pretend every message was sent at noon (Nairobi) on `day`. The simulated farm lives in
    September while the clock is real, so the tests set the send time themselves."""
    from src.dispatch import TZ

    db._query("UPDATE sms_log SET sent_at = %s", (datetime(day.year, day.month, day.day, 12, tzinfo=TZ),))


def test_a_farmer_with_evidence_gets_one_logged_advice_sms_and_not_a_second_today():
    seed()
    sms = FakeSms()
    rows = run_daily(TODAY, llm_client=NoHaiku(), sms_client=sms)
    assert rows[0]["action"] == "sent" and rows[0]["source"] == "template"
    assert len(sms.sent) == 1 and sms.sent[0][1] == ["+254700000001"]
    log = db._query("SELECT kind, status, body FROM sms_log", one=True)
    assert log["kind"] == "advice" and log["status"] == "sent" and "dairy meal" in log["body"]
    stamp(TODAY)
    again = run_daily(TODAY, llm_client=NoHaiku(), sms_client=sms)
    assert again[0]["action"] == "skip" and "today" in again[0]["reason"] and len(sms.sent) == 1
    soon = run_daily(TODAY + timedelta(days=13), llm_client=NoHaiku(), sms_client=sms)  # inside the 14-day gap
    assert soon[0]["action"] == "skip" and "advice" in soon[0]["reason"] and len(sms.sent) == 1


def test_a_farm_that_is_not_set_up_gets_a_nudge_once_a_week():
    seed(price=False, cows=False, catalogue=False)
    sms = FakeSms()
    first = run_daily(TODAY, llm_client=NoHaiku(), sms_client=sms)[0]
    assert first["action"] == "sent" and first["kind"] == "nudge"
    stamp(TODAY)
    assert run_daily(TODAY + timedelta(days=6), llm_client=NoHaiku(), sms_client=sms)[0]["action"] == "skip"
    assert run_daily(TODAY + timedelta(days=7), llm_client=NoHaiku(), sms_client=sms)[0]["action"] == "sent"
    assert len(sms.sent) == 2


def test_advice_below_the_minimum_gain_is_not_sent(monkeypatch):
    seed()
    assert run_daily(TODAY, send=False, llm_client=NoHaiku())[0]["action"] == "would_send"
    monkeypatch.setattr("src.dispatch.MIN_GAIN_KES", 10**6)
    row = run_daily(TODAY, send=False, llm_client=NoHaiku())[0]
    assert row["action"] == "skip" and "gain under" in row["reason"]


def test_a_failing_send_is_logged_failed_and_does_not_block_other_farmers():
    seed()
    other = db.add_farmer("Other", "+254700000002")

    class Down:
        def send(self, *a, **k):
            raise ConnectionError("no network")

    rows = run_daily(TODAY, llm_client=NoHaiku(), sms_client=Down())
    assert {r["farmer_id"]: r["action"] for r in rows}[1] == "failed"
    assert db._query("SELECT status FROM sms_log", one=True)["status"] == "failed"
    assert any(r["farmer_id"] == other for r in rows)
    # a failed message does not count as sent, so tomorrow it is tried again
    assert db.recent_sms(1) == []


def test_weekly_snapshot_stores_the_model_beliefs_and_replaces_the_same_day():
    fid = seed()
    assert run_weekly_snapshot(TODAY) == [fid]
    run_weekly_snapshot(TODAY)
    snaps = db.list_snapshots(fid)
    assert len(snaps) == 1 and snaps[0]["decision_kind"] == "advice"
    effect = next(e for e in snaps[0]["effects"] if e["feed"] == "dairy meal")
    assert effect["feed"] == "dairy meal" and effect["status"] == "clear" and effect["slope"] > 0.5
    assert snaps[0]["recent_kg"]["dairy meal"] > 0
