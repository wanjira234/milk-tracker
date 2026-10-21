"""Cows, breeding, semen and deworming against a real Postgres. Need TEST_DATABASE_URL."""
import os
from datetime import date, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import db  # noqa: E402
from src.breeding import cow_status  # noqa: E402
from src.ingestion.manual_entry import (  # noqa: E402
    record_breeding_event,
    record_cow,
    record_deworming,
    record_semen,
)

TODAY = date(2026, 10, 21)


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers RESTART IDENTITY CASCADE")


@pytest.fixture
def farm():
    fid = db.add_farmer("Test Farmer", "+254700000001")
    return fid, record_cow(fid, "Wanjiku")["id"], record_semen(fid, "Friesian - Kamau")["id"]


def test_adding_the_same_cow_twice_gives_one_cow_and_a_retired_cow_comes_back(farm):
    fid, cow, _ = farm
    assert record_cow(fid, "  Wanjiku ")["id"] == cow
    db.retire_cow(fid, cow)
    assert db.list_cows(fid) == [] and len(db.list_cows(fid, active_only=False)) == 1
    record_cow(fid, "Wanjiku")
    assert [c["tag"] for c in db.list_cows(fid)] == ["Wanjiku"]


def test_a_full_breeding_story_through_the_real_database(farm):
    fid, cow, semen = farm
    served = TODAY - timedelta(days=100)
    record_breeding_event(fid, cow, served - timedelta(days=1), "heat", today=TODAY)
    record_breeding_event(fid, cow, served, "served", semen, today=TODAY)
    record_breeding_event(fid, cow, served + timedelta(days=60), "confirmed_pregnant", today=TODAY)
    s = cow_status(db.breeding_events(fid, cow), TODAY)
    assert s["state"] == "in_calf" and "Friesian - Kamau" in s["label"]
    assert s["due"] == served + timedelta(days=283)


def test_a_pregnancy_result_needs_a_service_first(farm):
    fid, cow, _ = farm
    for kind in ("confirmed_pregnant", "not_pregnant"):
        with pytest.raises(ValueError, match="service first"):
            record_breeding_event(fid, cow, TODAY, kind, today=TODAY)


def test_semen_only_goes_with_a_service_and_must_be_the_farms_own(farm):
    fid, cow, semen = farm
    record_breeding_event(fid, cow, TODAY, "heat", semen, today=TODAY)  # semen ignored for a heat
    assert db.breeding_events(fid, cow)[0]["semen"] is None
    with pytest.raises(ValueError, match="semen"):
        record_breeding_event(fid, cow, TODAY, "served", 9999, today=TODAY)


def test_dates_and_kinds_are_checked(farm):
    fid, cow, _ = farm
    with pytest.raises(ValueError, match="future"):
        record_breeding_event(fid, cow, TODAY + timedelta(days=1), "heat", today=TODAY)
    with pytest.raises(ValueError):
        record_breeding_event(fid, cow, TODAY, "dancing", today=TODAY)
    with pytest.raises(ValueError, match="cow"):
        record_breeding_event(fid, 9999, TODAY, "heat", today=TODAY)


def test_one_farm_cannot_touch_another_farms_cow_or_semen(farm):
    fid, cow, semen = farm
    other = db.add_farmer("Other", "+254700000002")
    with pytest.raises(ValueError, match="cow"):
        record_breeding_event(other, cow, TODAY, "heat", today=TODAY)
    with pytest.raises(ValueError, match="cow"):
        record_deworming(other, TODAY, cow_id=cow, today=TODAY)
    # and the database itself refuses it even if the checks above were skipped
    with pytest.raises(Exception):
        db.add_breeding_event(other, cow, TODAY, "heat")
    with pytest.raises(Exception):
        db.add_breeding_event(other, db.add_cow(other, "Mine"), TODAY, "served", semen)


def test_deworming_for_the_whole_herd_or_one_cow(farm):
    fid, cow, _ = farm
    record_deworming(fid, TODAY - timedelta(days=60), product="Albendazole", today=TODAY)
    record_deworming(fid, TODAY - timedelta(days=10), cow_id=cow, today=TODAY)
    rows = db.dewormings(fid)
    assert [(r["cow_id"], r["product"]) for r in rows] == [(None, "Albendazole"), (cow, None)]
    with pytest.raises(ValueError, match="future"):
        record_deworming(fid, TODAY + timedelta(days=1), today=TODAY)


def test_a_mistaken_event_can_be_deleted(farm):
    fid, cow, _ = farm
    record_breeding_event(fid, cow, TODAY, "heat", today=TODAY)
    db.delete_breeding_event(fid, db.breeding_events(fid, cow)[0]["id"])
    assert db.breeding_events(fid, cow) == []
