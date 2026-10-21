"""Breeding status and deworming dates. Pure, no database."""
from datetime import date, timedelta

from src.breeding import GESTATION_DAYS, cow_status, deworm_status

D = date(2026, 3, 1)


def ev(kind, day, semen=None):
    return {"event_date": day, "kind": kind, "semen": semen}


def test_a_cow_with_no_records():
    assert cow_status([], D)["state"] == "new"


def test_after_a_heat_the_next_heat_is_expected_in_21_days():
    s = cow_status([ev("heat", D)], D + timedelta(days=3))
    assert s["state"] == "open" and "22 Mar 2026" in s["next"] and s["due"] is None


def test_served_cow_gets_a_due_date_and_the_semen_is_named():
    s = cow_status([ev("heat", D), ev("served", D + timedelta(days=1), "Friesian - Kamau")], D + timedelta(days=5))
    assert s["state"] == "served" and "Friesian - Kamau" in s["label"]
    assert s["due"] == D + timedelta(days=1 + GESTATION_DAYS)
    assert "did not hold" in s["next"]


def test_served_cow_advice_changes_as_time_passes():
    served = D
    events = [ev("served", served)]
    assert "did not hold" in cow_status(events, served + timedelta(days=5))["next"]
    assert "check for pregnancy from" in cow_status(events, served + timedelta(days=30))["next"]
    assert "Time to have the vet check" in cow_status(events, served + timedelta(days=70))["next"]


def test_confirmed_in_calf_shows_due_and_dry_off_dates():
    events = [ev("served", D), ev("confirmed_pregnant", D + timedelta(days=60))]
    s = cow_status(events, D + timedelta(days=100))
    assert s["state"] == "in_calf" and s["due"] == D + timedelta(days=283)
    assert "Dry off about" in s["next"] and "due about" in s["label"]


def test_close_to_calving_and_overdue_calving():
    events = [ev("served", D), ev("confirmed_pregnant", D + timedelta(days=60))]
    assert "Dry period" in cow_status(events, D + timedelta(days=250))["next"]
    assert "Calving was expected" in cow_status(events, D + timedelta(days=290))["next"]


def test_not_pregnant_or_a_heat_after_service_clears_the_pregnancy():
    for undo in (ev("not_pregnant", D + timedelta(days=60)), ev("heat", D + timedelta(days=22)), ev("aborted", D + timedelta(days=90))):
        s = cow_status([ev("served", D), undo], D + timedelta(days=95))
        assert s["state"] == "open" and s["due"] is None


def test_calving_resets_the_cycle():
    events = [ev("served", D), ev("confirmed_pregnant", D + timedelta(days=60)), ev("calved", D + timedelta(days=283))]
    s = cow_status(events, D + timedelta(days=300))
    assert s["state"] == "calved" and "ready to be served from about" in s["next"]
    later = cow_status(events, D + timedelta(days=283 + 70))
    assert "watch for heat" in later["next"]


def test_events_can_be_given_in_any_order():
    a = [ev("served", D), ev("confirmed_pregnant", D + timedelta(days=60))]
    assert cow_status(a, D + timedelta(days=70)) == cow_status(list(reversed(a)), D + timedelta(days=70))


def test_confirmation_without_a_service_is_ignored():
    assert cow_status([ev("confirmed_pregnant", D)], D)["state"] == "new"


def test_deworming_every_three_months():
    today = date(2026, 6, 1)
    assert deworm_status(None, today)["state"] == "never"
    assert deworm_status(today - timedelta(days=30), today)["state"] == "ok"
    soon = deworm_status(today - timedelta(days=80), today)
    assert soon["state"] == "soon" and "10 day" in soon["text"]
    late = deworm_status(today - timedelta(days=100), today)
    assert late["state"] == "overdue" and "10 day" in late["text"]
    assert deworm_status(today - timedelta(days=90), today)["state"] == "soon"  # due today
