"""Shop hours and time slots (pure)."""
from datetime import date, datetime, time

import pytest

from src import hours

MON = date(2026, 11, 2)  # a Monday
WEEK = {wd: {"opens": time(8), "closes": time(12), "delivers": wd == 1} for wd in range(6)}  # Mon-Sat 8-12, delivers Tue


def test_slots_follow_the_hours_and_the_slot_length():
    assert hours.slots_on(WEEK, MON) == [time(8), time(9), time(10), time(11)]
    assert hours.slots_on(WEEK, MON, minutes=120) == [time(8), time(10)]
    assert hours.slots_on(WEEK, date(2026, 11, 8)) == []  # Sunday: closed
    assert hours.slots_on(WEEK, MON, "delivery") == [] and hours.slots_on(WEEK, date(2026, 11, 3), "delivery")


def test_today_only_offers_slots_the_shop_can_still_get_ready():
    assert hours.slots_on(WEEK, MON, now=datetime(2026, 11, 2, 8, 40)) == [time(10), time(11)]
    assert hours.slots_on(WEEK, MON, now=datetime(2026, 11, 2, 11, 30)) == []
    days = hours.days_open(WEEK, MON, now=datetime(2026, 11, 2, 11, 30), days=7)
    assert MON not in days and date(2026, 11, 3) in days and date(2026, 11, 8) not in days


def test_delivery_days_are_only_the_days_the_shop_delivers():
    days = hours.days_open(WEEK, MON, "delivery", days=13, now=datetime(2026, 11, 2, 7))
    assert days == [date(2026, 11, 3), date(2026, 11, 10)]


def test_a_shop_without_hours_takes_any_day_and_no_time():
    assert len(hours.days_open({}, MON, days=3)) == 4
    hours.check({}, MON, None)
    with pytest.raises(ValueError, match="hasn't set its hours"):
        hours.check({}, MON, time(9))


def test_check_refuses_closed_days_and_odd_times():
    now = datetime(2026, 11, 2, 7)
    hours.check(WEEK, MON, time(9), now=now)
    with pytest.raises(ValueError, match="closed on Sundays"):
        hours.check(WEEK, date(2026, 11, 8), time(9), now=now)
    with pytest.raises(ValueError, match="doesn't deliver"):
        hours.check(WEEK, MON, time(9), "delivery", now=now)
    with pytest.raises(ValueError, match="one of the shop's times"):
        hours.check(WEEK, MON, time(9, 15), now=now)
    with pytest.raises(ValueError, match="choose a time"):
        hours.check(WEEK, MON, None, now=now)


def test_summary_and_parse():
    assert hours.summary(WEEK) == "Mon-Sat 08:00-12:00 · delivers Tue"
    assert hours.summary({}) == "Hours not set"
    rows = [{"weekday": 0, "open": True, "opens": time(8), "closes": time(17), "delivers": True},
            {"weekday": 6, "open": False, "opens": time(8), "closes": time(17)}]
    assert hours.parse(rows) == {0: {"opens": time(8), "closes": time(17), "delivers": True}}
    with pytest.raises(ValueError, match="closing must be after opening"):
        hours.parse([{"weekday": 2, "open": True, "opens": time(17), "closes": time(8)}])
    assert hours.label(time(10), 30) == "10:00-10:30" and hours.label(None) == "Any time"
