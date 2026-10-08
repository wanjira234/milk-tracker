"""Dashboard calculation tests: no database, no Streamlit."""
from datetime import date
from decimal import Decimal

import pytest

from src.trends import daily_frame, signals, summary

START, END = date(2026, 10, 1), date(2026, 10, 10)


def y(day, litres, sessions=3):
    return {"log_date": date(2026, 10, day), "litres": Decimal(str(litres)), "sessions": sessions}


def f(day, feed, kg, cost):
    return {"log_date": date(2026, 10, day), "feed_type": feed, "kg": Decimal(str(kg)), "cost_kes": Decimal(str(cost))}


def test_one_row_per_calendar_day_even_when_empty():
    daily, feed_kg = daily_frame([], [], START, END)
    assert len(daily) == 10
    assert daily["litres"].isna().all()
    assert not daily["complete"].any()
    assert feed_kg.empty
    assert daily["cost_kes"].sum() == 0


def test_incomplete_days_are_flagged_and_excluded_from_stats():
    daily, _ = daily_frame([y(1, 30), y(2, 28), y(3, 10, sessions=1)], [], START, END)
    s = summary(daily)
    assert s["complete_days"] == 2
    assert s["partial_days"] == 1
    assert s["avg_litres"] == pytest.approx(29.0)  # the 10 L partial day does not drag it down
    assert s["best_day"] == (date(2026, 10, 1), 30.0)


def test_cost_per_litre_uses_complete_days_only():
    daily, _ = daily_frame(
        [y(1, 20), y(2, 20), y(3, 5, sessions=1)],
        [f(1, "dairy meal", 4, 200), f(2, "dairy meal", 4, 200), f(3, "dairy meal", 4, 999)],
        START,
        END,
    )
    assert summary(daily)["cost_per_litre"] == pytest.approx(400 / 40)
    assert summary(daily)["total_cost"] == pytest.approx(1399)


def test_feed_pivot_sums_by_type_and_fills_zero():
    _, feed_kg = daily_frame([], [f(1, "dairy meal", 2, 100), f(1, "dairy meal", 3, 150), f(2, "napier", 30, 0)], START, END)
    assert feed_kg.loc["2026-10-01", "dairy meal"] == 5
    assert feed_kg.loc["2026-10-01", "napier"] == 0
    assert feed_kg.loc["2026-10-02", "napier"] == 30


def test_summary_with_no_data_is_safe():
    s = summary(daily_frame([], [], START, END)[0])
    assert s["avg_litres"] is None and s["best_day"] is None and s["cost_per_litre"] is None


def test_signal_found_when_feed_tracks_yield():
    yields = [y(d, 20 + d) for d in range(1, 9)]
    feeds = [f(d, "dairy meal", 2 + d * 0.5, 100) for d in range(1, 9)]
    daily, feed_kg = daily_frame(yields, feeds, START, END)
    (feed_type, corr, n), = signals(daily, feed_kg)
    assert feed_type == "dairy meal" and corr == pytest.approx(1.0) and n == 8


def test_no_signal_for_constant_ration():
    yields = [y(d, 20 + d) for d in range(1, 9)]
    feeds = [f(d, "dairy meal", 5, 100) for d in range(1, 9)]
    daily, feed_kg = daily_frame(yields, feeds, START, END)
    assert signals(daily, feed_kg) == []


def test_no_signal_with_too_few_days():
    yields = [y(d, 20 + d) for d in range(1, 5)]
    feeds = [f(d, "dairy meal", d, 100) for d in range(1, 5)]
    daily, feed_kg = daily_frame(yields, feeds, START, END)
    assert signals(daily, feed_kg) == []


def test_signals_ignore_incomplete_days():
    yields = [y(d, 20 + d) for d in range(1, 9)] + [y(9, 2, sessions=1)]
    feeds = [f(d, "dairy meal", 2 + d * 0.5, 100) for d in range(1, 10)]
    daily, feed_kg = daily_frame(yields, feeds, START, END)
    assert signals(daily, feed_kg)[0][2] == 8  # day 9 excluded
