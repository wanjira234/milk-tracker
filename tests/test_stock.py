"""Feed stock forecasting, pure (no database)."""
from datetime import date, timedelta

from src import stock

TODAY = date(2026, 11, 3)
NAPIER = {"id": 1, "name": "napier", "unit": "truck", "kg_per_unit": 3000, "lead_days": 3}


def day(n):
    return TODAY - timedelta(days=n)


def buy(n, kg=3000):
    return {"purchased_on": day(n), "kg": kg}


def count(n, kg):
    return {"counted_on": day(n), "kg": kg}


def fed(days, kg):
    return [{"log_date": day(n), "kg": kg} for n in days]


def test_nothing_recorded_means_nothing_to_say():
    s = stock.item_status(NAPIER, [], [], [], [], TODAY)
    assert s["on_hand_kg"] is None and s["days_left"] is None and not s["low"]


def test_stock_from_the_feed_log_after_a_purchase():
    s = stock.item_status(NAPIER, [buy(10)], [], fed(range(1, 11), 200), [day(n) for n in range(1, 15)], TODAY)
    assert s["on_hand_kg"] == 3000 - 10 * 200 and s["on_hand_units"] == 1000 / 3000
    # rate: 10 days fed 200 over the 14 logged days in the window (4 days with other feed logged, none of this)
    assert s["rate_from"] == "feed log" and round(s["daily_kg"], 2) == round(2000 / 14, 2)
    assert round(s["days_left"], 2) == round(1000 / (2000 / 14), 2) and s["runs_out_on"] == TODAY + timedelta(days=7)
    assert not s["low"]


def test_low_when_it_runs_out_within_the_warning_days():
    s = stock.item_status(NAPIER, [buy(14)], [], fed(range(1, 15), 200), [day(n) for n in range(1, 15)], TODAY)
    assert s["on_hand_kg"] == 200 and s["days_left"] == 1 and s["low"]


def test_without_a_feed_log_it_learns_from_how_long_the_last_truck_lasted():
    # full truck on day 30, finished on day 20 (10 days), new truck on day 20, nothing logged since
    s = stock.item_status(NAPIER, [buy(30), buy(20)], [count(20, 0)], [], [], TODAY)
    assert s["rate_from"] == "last load" and s["daily_kg"] == 300
    assert s["on_hand_kg"] == 3000 and s["days_left"] == 10 and s["runs_out_on"] == TODAY + timedelta(days=10)


def test_a_count_resets_stock_to_what_was_seen():
    # bought day 10, counted half a truck left on day 4, fed 100 a day since (days 3..1)
    s = stock.item_status(NAPIER, [buy(10)], [count(4, 1500)], fed(range(1, 10), 100), [day(n) for n in range(1, 10)], TODAY)
    assert s["on_hand_kg"] == 1500 - 3 * 100


def test_a_delivery_on_the_day_the_old_load_finished_is_counted():
    s = stock.item_status(NAPIER, [buy(30), buy(20)], [count(20, 0)], [], [], TODAY)
    assert s["on_hand_kg"] == 3000  # the day-20 truck arrived after the old one ran out


def test_too_few_logged_days_fall_back_to_the_last_load():
    s = stock.item_status(NAPIER, [buy(30), buy(20)], [count(20, 0)], fed([1, 2], 500), [day(1), day(2)], TODAY)
    assert s["rate_from"] == "last load"


def test_stock_never_goes_below_zero_and_counts_after_today_are_ignored():
    s = stock.item_status(NAPIER, [buy(5, kg=100)], [{"counted_on": TODAY + timedelta(days=1), "kg": 9999}],
                          fed(range(1, 6), 200), [day(n) for n in range(1, 6)], TODAY)
    assert s["on_hand_kg"] == 0 and s["days_left"] == 0 and s["low"]


def test_a_finished_load_with_no_purchase_to_measure_gives_no_rate():
    s = stock.item_status(NAPIER, [], [count(3, 0)], [], [], TODAY)
    assert s["on_hand_kg"] == 0 and s["daily_kg"] is None and s["days_left"] is None
