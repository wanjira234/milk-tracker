"""Calves, heifers, mothers and the cows-in-milk link, against a real Postgres."""
import os
from datetime import date, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import db  # noqa: E402
from src.ingestion.manual_entry import (  # noqa: E402
    record_breeding_event,
    record_calving,
    record_cow,
    record_wean,
)

TODAY = date(2026, 10, 21)


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers RESTART IDENTITY CASCADE")


@pytest.fixture
def fid():
    return db.add_farmer("Test Farmer", "+254700000001")


def cow(fid, tag):
    return next(c for c in db.list_cows(fid) if c["tag"] == tag)


def test_a_calving_adds_the_calf_linked_to_its_mother(fid):
    mum = record_cow(fid, "Wanjiku", lactation="milking", since=TODAY - timedelta(days=300), today=TODAY)["id"]
    record_calving(fid, mum, TODAY - timedelta(days=2), "Pendo", "female", today=TODAY)
    calf = cow(fid, "Pendo")
    assert calf["mother_id"] == mum and calf["life_stage"] == "calf" and calf["sex"] == "female"
    assert calf["birth_date"] == TODAY - timedelta(days=2)


def test_a_heifer_becomes_a_cow_when_she_calves(fid):
    heifer = record_cow(fid, "Zawadi", life_stage="heifer", today=TODAY)["id"]
    assert cow(fid, "Zawadi")["life_stage"] == "heifer"
    record_calving(fid, heifer, TODAY, today=TODAY)
    assert cow(fid, "Zawadi")["life_stage"] == "cow"


def test_weaning_turns_a_female_calf_into_a_heifer_and_a_male_into_a_young_bull(fid):
    f = record_cow(fid, "Pendo", life_stage="calf", birth_date=TODAY - timedelta(days=100), today=TODAY)["id"]
    m = record_cow(fid, "Jabali", sex="male", life_stage="calf", today=TODAY)["id"]
    record_wean(fid, f, TODAY, today=TODAY)
    record_wean(fid, m, TODAY, today=TODAY)
    assert cow(fid, "Pendo")["life_stage"] == "heifer" and cow(fid, "Jabali")["life_stage"] == "bull"
    with pytest.raises(ValueError, match="calf"):
        record_wean(fid, f, TODAY, today=TODAY)  # no longer a calf


def test_odd_combinations_are_refused(fid):
    mum = record_cow(fid, "Wanjiku", today=TODAY)["id"]
    for kwargs in (
        {"sex": "male", "life_stage": "cow"}, {"sex": "female", "life_stage": "bull"}, {"life_stage": "pony"},
        {"life_stage": "heifer", "lactation": "milking"}, {"birth_date": TODAY + timedelta(days=1)},
        {"mother_id": 9999}, {"lactation": "sleeping"},
    ):
        with pytest.raises(ValueError):
            record_cow(fid, "X", today=TODAY, **kwargs)
    bull = record_cow(fid, "Jabali", sex="male", life_stage="bull", today=TODAY)["id"]
    with pytest.raises(ValueError, match="mother"):
        record_cow(fid, "Y", life_stage="calf", mother_id=bull, today=TODAY)
    with pytest.raises(ValueError, match="calf or bull"):
        record_breeding_event(fid, bull, TODAY, "heat", today=TODAY)
    assert mum


def test_the_calfs_tag_must_be_new_and_nothing_is_saved_if_it_is_not(fid):
    mum = record_cow(fid, "Wanjiku", lactation="milking", since=TODAY - timedelta(days=300), today=TODAY)["id"]
    with pytest.raises(ValueError, match="already an animal"):
        record_calving(fid, mum, TODAY, "Wanjiku", "female", today=TODAY)
    assert [e["kind"] for e in db.breeding_events(fid, mum)] == ["milking"]  # no calving was recorded


def test_only_a_milking_cow_can_be_dried_off(fid):
    c = record_cow(fid, "Wanjiku", today=TODAY)["id"]
    with pytest.raises(ValueError, match="not recorded as milking"):
        record_breeding_event(fid, c, TODAY, "dried_off", today=TODAY)
    record_breeding_event(fid, c, TODAY - timedelta(days=5), "milking", today=TODAY)
    record_breeding_event(fid, c, TODAY, "dried_off", today=TODAY)


def test_cows_in_milk_follows_the_cow_records_once_the_farm_switches_over(fid):
    db.set_cows_in_milk(fid, TODAY - timedelta(days=200), 6)  # the typed-in number
    a = record_cow(fid, "A", lactation="milking", since=TODAY - timedelta(days=100), today=TODAY)["id"]
    record_cow(fid, "B", lactation="milking", since=TODAY - timedelta(days=100), today=TODAY)
    assert db.cows_in_milk_on(fid, TODAY) == 6  # not switched yet: still the typed-in number
    db.set_cows_in_milk_from_records(fid, True)
    assert db.cows_in_milk_on(fid, TODAY) == 2 and db.cows_in_milk_on(fid, TODAY - timedelta(days=150)) is None
    record_breeding_event(fid, a, TODAY - timedelta(days=10), "dried_off", today=TODAY)
    assert db.cows_in_milk_on(fid, TODAY) == 1
    assert [(str(h["effective_date"]), h["cows_in_milk"]) for h in db.herd_history(fid)] == [
        (str(TODAY - timedelta(days=10)), 1), (str(TODAY - timedelta(days=100)), 2),
    ]
    db.set_cows_in_milk_from_records(fid, False)  # and back again
    assert db.cows_in_milk_on(fid, TODAY) == 6


def test_a_retired_cow_stops_counting_but_her_history_stays(fid):
    a = record_cow(fid, "A", lactation="milking", since=TODAY - timedelta(days=100), today=TODAY)["id"]
    record_cow(fid, "B", lactation="milking", since=TODAY - timedelta(days=100), today=TODAY)
    db.set_cows_in_milk_from_records(fid, True)
    db.retire_cow(fid, a, on=TODAY - timedelta(days=3))
    assert db.cows_in_milk_on(fid, TODAY) == 1 and db.cows_in_milk_on(fid, TODAY - timedelta(days=5)) == 2


def test_the_model_sees_the_derived_herd(fid):
    """assess_farmer reads herd_history, so the model works from the cow records too."""
    from src.loader import assess_farmer

    record_cow(fid, "A", lactation="milking", since=TODAY - timedelta(days=100), today=TODAY)
    db.set_cows_in_milk_from_records(fid, True)
    r = assess_farmer(fid, today=TODAY)
    assert not any(n["code"] == "no_cows" for n in r["decision"]["nudges"])


def test_one_farm_cannot_name_another_farms_cow_as_a_mother(fid):
    other = db.add_farmer("Other", "+254700000002")
    theirs = db.add_cow(other, "Theirs")
    with pytest.raises(ValueError, match="mother"):
        record_cow(fid, "Calf", life_stage="calf", mother_id=theirs, today=TODAY)
    with pytest.raises(Exception):  # and the database refuses it too
        db.add_cow(fid, "Calf2", life_stage="calf", mother_id=theirs)
