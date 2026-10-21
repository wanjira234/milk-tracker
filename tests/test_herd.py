"""Milking/dry status and the cows-in-milk count worked out from cow records. Pure."""
from datetime import date

from src.breeding import age_text, cow_status
from src.herd import cows_in_milk_on, history, lactation_on


def ev(cow, kind, day, id=0):
    return {"id": id, "cow_id": cow, "kind": kind, "event_date": day}


def cow(id, sex="female", retired_on=None):
    return {"id": id, "sex": sex, "retired_on": retired_on}


def d(m, day):
    return date(2026, m, day)


def test_a_cow_milks_from_calving_until_dried_off_and_again_after_the_next_calving():
    events = [ev(1, "calved", d(1, 10)), ev(1, "dried_off", d(8, 1)), ev(1, "calved", d(11, 1))]
    assert lactation_on(events, d(1, 9)) is None
    assert lactation_on(events, d(1, 10)) == "milking"
    assert lactation_on(events, d(8, 1)) == "dry"
    assert lactation_on(events, d(12, 1)) == "milking"


def test_heat_service_and_other_events_do_not_change_milking():
    events = [ev(1, "milking", d(1, 1)), ev(1, "served", d(3, 1)), ev(1, "confirmed_pregnant", d(5, 1))]
    assert lactation_on(events, d(6, 1)) == "milking"


def test_same_day_events_use_the_one_recorded_last():
    events = [ev(1, "calved", d(3, 1), id=5), ev(1, "dried_off", d(3, 1), id=4)]
    assert lactation_on(events, d(3, 1)) == "milking"


def test_the_count_counts_only_milking_females_and_ignores_the_rest():
    cows = [cow(1), cow(2), cow(3), cow(4, sex="male")]
    events = [ev(1, "milking", d(1, 1)), ev(2, "milking", d(1, 1)), ev(2, "dried_off", d(6, 1)), ev(4, "milking", d(1, 1))]
    assert cows_in_milk_on(cows, events, d(5, 1)) == 2  # cow 3 never milked, cow 4 is male
    assert cows_in_milk_on(cows, events, d(7, 1)) == 1


def test_no_count_before_anything_was_recorded():
    assert cows_in_milk_on([cow(1)], [], d(5, 1)) is None
    assert cows_in_milk_on([cow(1)], [ev(1, "milking", d(5, 1))], d(4, 1)) is None


def test_a_cow_who_was_sold_stops_counting_from_that_day():
    cows = [cow(1, retired_on=d(6, 15)), cow(2)]
    events = [ev(1, "milking", d(1, 1)), ev(2, "milking", d(1, 1))]
    assert cows_in_milk_on(cows, events, d(6, 14)) == 2 and cows_in_milk_on(cows, events, d(6, 15)) == 1


def test_history_lists_only_changes_newest_first_in_the_shape_the_model_expects():
    cows = [cow(1), cow(2), cow(3)]
    events = [
        ev(1, "milking", d(1, 1)), ev(2, "milking", d(1, 1)),   # 2 cows
        ev(3, "calved", d(4, 1)),                                # 3
        ev(3, "served", d(4, 20)),                               # no change: not a milking event
        ev(1, "dried_off", d(9, 1)),                             # 2
    ]
    assert history(cows, events) == [
        {"effective_date": d(9, 1), "cows_in_milk": 2},
        {"effective_date": d(4, 1), "cows_in_milk": 3},
        {"effective_date": d(1, 1), "cows_in_milk": 2},
    ]
    assert history(cows, []) == []


def test_age_in_words():
    t = date(2026, 10, 21)
    assert age_text(None, t) is None
    assert age_text(date(2026, 10, 10), t) == "under a month"
    assert age_text(date(2026, 5, 21), t) == "5 months"
    assert age_text(date(2025, 7, 1), t) == "1 year 3 months"
    assert age_text(date(2024, 10, 21), t) == "2 years"


def test_a_heifer_with_no_records_is_waiting_for_her_first_heat():
    s = cow_status([], date(2026, 10, 21), life_stage="heifer")
    assert s["label"] == "Waiting for first heat" and "15 months" in s["next"]
    assert cow_status([], date(2026, 10, 21))["label"] == "No breeding records yet"
