"""Outbreak alerts, who may send them, SMS sending once, and the outbox. Need TEST_DATABASE_URL."""
import os
from datetime import date, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import accounts, alerts, db  # noqa: E402

TODAY = date(2026, 10, 24)


class FakeSms:
    def __init__(self, fail_for=()):
        self.sent, self.fail_for = [], set(fail_for)

    def send(self, message, recipients, sender_id=None):
        if recipients[0] in self.fail_for:
            raise ConnectionError("no network")
        self.sent.append((message, recipients[0]))
        return {"SMSMessageData": {"Recipients": [{"statusCode": 101, "status": "Success", "messageId": f"ATX{len(self.sent)}"}]}}


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, alerts, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes RESTART IDENTITY CASCADE")


@pytest.fixture
def world():
    r4a, r5b = accounts.record_route("4A"), accounts.record_route("5B")
    as_user = lambda uid: accounts.session_user(db.get_user(uid))  # noqa: E731
    vet_a = as_user(accounts.create_account("vet", "Dr Kibet", phone="0712345678"))
    vet_b = as_user(accounts.create_account("vet", "Dr Achieng", phone="0722222222"))
    admin = as_user(accounts.create_account("admin", "Fresha Admin", phone="0733333333"))
    accounts.allocate_vet(r4a, vet_a["id"])
    accounts.allocate_vet(r5b, vet_b["id"])
    fa1, fa2 = db.add_farmer("A1", "+254700000001", "A1 Farm"), db.add_farmer("A2", "+254700000002")
    fb, lone = db.add_farmer("B1", "+254700000003"), db.add_farmer("Lone", "+254700000004")
    for f, r in ((fa1, r4a), (fa2, r4a), (fb, r5b)):
        accounts.assign_route(f, r)
    farmer_a1 = as_user(accounts.create_account("farmer", "A1", phone="0700000001", farmer_id=fa1))
    farmer_b = as_user(accounts.create_account("farmer", "B1", phone="0700000003", farmer_id=fb))
    return dict(r4a=r4a, r5b=r5b, vet_a=vet_a, vet_b=vet_b, admin=admin, farmer_a1=farmer_a1, farmer_b=farmer_b, fa1=fa1, fa2=fa2, fb=fb, lone=lone)


def post(w, who="admin", route="r4a", **kw):
    args = dict(kind="outbreak", title="Foot and mouth near Tigoni", body="Keep cows in. Do not move animals. Call your vet if a cow limps.", today=TODAY)
    return alerts.post_alert(w[who], route_id=w.get(route) if route else None, **(args | kw))


# --- posting -------------------------------------------------------------------------------------


def test_who_may_post_to_which_routes(world):
    assert post(world)  # admin to one route
    assert post(world, route=None)  # admin to every route
    assert post(world, who="vet_a")  # a vet to their own route
    with pytest.raises(ValueError, match="your routes"):
        post(world, who="vet_a", route="r5b")
    with pytest.raises(ValueError, match="only their own routes"):
        post(world, who="vet_a", route=None)
    with pytest.raises(ValueError, match="only an admin or a vet"):
        post(world, who="farmer_a1")
    with pytest.raises(ValueError, match="your routes"):
        alerts.post_alert(world["admin"], "outbreak", "T", "B", route_id=9999, today=TODAY)


def test_alert_validation(world):
    for kw, why in (
        (dict(kind="party"), "outbreak or notice"), (dict(title=" "), "short title"), (dict(title="x" * 61), "too long"),
        (dict(body=""), "what farmers should know"), (dict(body="x" * 401), "too long"),
        (dict(expires_on=TODAY - timedelta(days=1)), "past"),
    ):
        with pytest.raises(ValueError, match=why):
            post(world, **kw)


# --- who sees what ---------------------------------------------------------------------------------


def test_farmers_see_their_routes_alerts_and_the_all_route_ones_until_they_expire(world):
    mine, theirs, everyone = post(world, title="For 4A"), post(world, route="r5b", title="For 5B"), post(world, route=None, title="For all")
    old = post(world, title="Ends soon", expires_on=TODAY)
    titles = lambda u, day=TODAY: sorted(a["title"] for a in alerts.visible_alerts(u, day))  # noqa: E731
    assert titles(world["farmer_a1"]) == ["Ends soon", "For 4A", "For all"]
    assert titles(world["farmer_b"]) == ["For 5B", "For all"]
    assert titles(world["farmer_a1"], TODAY + timedelta(days=1)) == ["For 4A", "For all"]  # one has expired
    assert titles(world["vet_a"]) == ["Ends soon", "For 4A", "For all"] and len(titles(world["admin"])) == 4
    assert mine and theirs and everyone and old


def test_a_farm_with_no_route_sees_only_the_all_route_alerts(world):
    post(world, title="For 4A")
    post(world, route=None, title="For all")
    lone = accounts.session_user(db.get_user(accounts.create_account("farmer", "Lone", phone="0700000004", farmer_id=world["lone"])))
    assert [a["title"] for a in alerts.visible_alerts(lone, TODAY)] == ["For all"]


# --- SMS -----------------------------------------------------------------------------------------


def test_the_sms_text_is_plain_labelled_and_fits_two_segments():
    text = alerts.sms_text("outbreak", "Foot and mouth near Tigoni.", "Keep cows in.   Call your vet.")
    assert text == "Maziwa Plus: OUTBREAK: Foot and mouth near Tigoni. Keep cows in. Call your vet."
    assert alerts.sms_problem(text) is None
    assert "too long" in alerts.sms_problem(alerts.sms_text("notice", "T", "x" * 400))
    assert "alphabet" in alerts.sms_problem("Maziwa Plus: Notice: cows \U0001F404 are safe")
    assert alerts.sms_text("notice", "Vaccine day", "Bring your cows.").startswith("Maziwa Plus: Notice: Vaccine day.")


def test_sending_texts_only_the_farms_on_that_route_and_logs_each_message(world):
    aid = post(world)
    fake = FakeSms()
    assert alerts.send_alert_sms(aid, world["admin"], client=fake) == {"ok": 2, "failed": 0}
    assert sorted(to for _, to in fake.sent) == ["+254700000001", "+254700000002"]  # 4A only
    assert all(m.startswith("Maziwa Plus: OUTBREAK:") for m, _ in fake.sent)
    a = db.get_alert(aid)
    assert a["sms_ok"] == 2 and a["sms_failed"] == 0 and a["sms_sent_at"] is not None
    log = db.sms_outbox()
    assert len(log) == 2 and {r["kind"] for r in log} == {"alert"} and {r["status"] for r in log} == {"sent"}


def test_an_alert_is_texted_once_even_if_asked_twice(world):
    aid = post(world)
    alerts.send_alert_sms(aid, world["admin"], client=(fake := FakeSms()))
    with pytest.raises(ValueError, match="already sent"):
        alerts.send_alert_sms(aid, world["admin"], client=fake)
    assert len(fake.sent) == 2


def test_an_all_route_alert_reaches_every_farm_but_only_an_admin_may_send_it(world):
    aid = post(world, route=None)
    with pytest.raises(ValueError, match="not for your routes"):
        alerts.send_alert_sms(aid, world["vet_a"], client=FakeSms())
    assert alerts.send_alert_sms(aid, world["admin"], client=(fake := FakeSms()))["ok"] == 4
    assert len(fake.sent) == 4


def test_a_vet_cannot_text_another_routes_alert_and_a_farmer_cannot_text_at_all(world):
    aid = post(world, route="r5b")
    with pytest.raises(ValueError, match="not for your routes"):
        alerts.send_alert_sms(aid, world["vet_a"], client=FakeSms())
    with pytest.raises(ValueError, match="only an admin or a vet"):
        alerts.send_alert_sms(aid, world["farmer_b"], client=FakeSms())
    assert db.get_alert(aid)["sms_sent_at"] is None
    assert alerts.send_alert_sms(aid, world["vet_b"], client=FakeSms())["ok"] == 1


def test_one_failed_number_is_counted_and_does_not_stop_the_rest(world):
    aid = post(world)
    result = alerts.send_alert_sms(aid, world["admin"], client=FakeSms(fail_for=["+254700000001"]))
    assert result == {"ok": 1, "failed": 1}
    assert {r["status"] for r in db.sms_outbox()} == {"sent", "failed"}


def test_an_unsendable_text_or_an_empty_route_is_refused_before_anyone_is_texted(world):
    long_one = post(world, body="x" * 400)
    with pytest.raises(ValueError, match="too long for SMS"):
        alerts.send_alert_sms(long_one, world["admin"], client=(fake := FakeSms()))
    empty_route = accounts.record_route("9Z")
    nobody = alerts.post_alert(world["admin"], "notice", "T", "Hello", route_id=empty_route, today=TODAY)
    with pytest.raises(ValueError, match="no farm with a phone"):
        alerts.send_alert_sms(nobody, world["admin"], client=fake)
    assert fake.sent == [] and db.get_alert(long_one)["sms_sent_at"] is None  # nothing was claimed, so it can be fixed and retried


def test_farmers_with_no_credentials_get_failed_logs_not_a_crash(world, monkeypatch):
    monkeypatch.delenv("AT_USERNAME", raising=False)
    monkeypatch.delenv("AT_API_KEY", raising=False)
    aid = post(world)
    assert alerts.send_alert_sms(aid, world["admin"]) == {"ok": 0, "failed": 2}


# --- the outbox ----------------------------------------------------------------------------------


def test_each_role_sees_only_its_own_messages_in_the_outbox(world):
    alerts.send_alert_sms(post(world, route=None), world["admin"], client=FakeSms())
    names = lambda u: sorted(r["farmer_name"] for r in alerts.outbox(u))  # noqa: E731
    assert names(world["admin"]) == ["A1", "A2", "B1", "Lone"]
    assert names(world["vet_a"]) == ["A1", "A2"]
    assert names(world["farmer_a1"]) == ["A1"] and names(world["farmer_b"]) == ["B1"]
