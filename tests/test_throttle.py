"""Throttling rules, pure."""
from datetime import date, timedelta

from src.dispatch import ADVICE_EVERY_DAYS, NUDGE_EVERY_DAYS, throttle

TODAY = date(2026, 10, 12)


def ago(kind, days):
    return {"kind": kind, "day": TODAY - timedelta(days=days)}


def test_nothing_sent_before_means_ok():
    assert throttle("advice", [], TODAY) == (True, None)
    assert throttle("nudge", [], TODAY) == (True, None)


def test_one_message_a_day_whatever_the_kind():
    ok, why = throttle("nudge", [ago("advice", 0)], TODAY)
    assert not ok and "today" in why


def test_advice_waits_its_gap():
    assert not throttle("advice", [ago("advice", ADVICE_EVERY_DAYS - 1)], TODAY)[0]
    assert throttle("advice", [ago("advice", ADVICE_EVERY_DAYS)], TODAY)[0]


def test_nudge_waits_its_gap_and_is_not_blocked_by_old_advice():
    assert not throttle("nudge", [ago("nudge", NUDGE_EVERY_DAYS - 1)], TODAY)[0]
    assert throttle("nudge", [ago("nudge", NUDGE_EVERY_DAYS)], TODAY)[0]
    assert throttle("nudge", [ago("advice", 2)], TODAY)[0]  # a different kind has its own clock
