"""Budget maths tests: no database, no Streamlit."""
from datetime import date

import pytest

from src.budget import (
    budget_status,
    days_in_month,
    next_month_estimate,
    next_month_start,
    prev_month_start,
    project_month_spend,
)


def test_month_navigation_crosses_year_boundaries():
    assert next_month_start(date(2026, 12, 15)) == date(2027, 1, 1)
    assert next_month_start(date(2026, 10, 9)) == date(2026, 11, 1)
    assert prev_month_start(date(2026, 1, 20)) == date(2025, 12, 1)
    assert prev_month_start(date(2026, 3, 1)) == date(2026, 2, 1)


def test_days_in_month_handles_leap_years():
    assert days_in_month(date(2028, 2, 10)) == 29
    assert days_in_month(date(2026, 2, 10)) == 28
    assert days_in_month(date(2026, 10, 1)) == 31


def test_projection_scales_pace_to_full_month():
    p = project_month_spend(3000, date(2026, 10, 10))  # 10 of 31 days
    assert p["projected"] == pytest.approx(3000 / 10 * 31)
    assert p["daily_rate"] == pytest.approx(300)
    assert p["days_left"] == 21
    assert p["reliable"] is True


def test_projection_unreliable_in_first_week():
    assert project_month_spend(5000, date(2026, 10, 3))["reliable"] is False
    assert project_month_spend(5000, date(2026, 10, 7))["reliable"] is True


def test_status_over_when_already_past_budget():
    p = project_month_spend(12000, date(2026, 10, 15))
    s = budget_status(10000, 12000, p)
    assert s["status"] == "over" and s["remaining"] == -2000 and s["daily_allowance"] is None


def test_status_watch_when_pace_exceeds_budget():
    p = project_month_spend(6000, date(2026, 10, 10))  # 6000/10*31 = 18600
    s = budget_status(15000, 6000, p)
    assert s["status"] == "watch"
    assert s["projected_overrun"] == pytest.approx(3600)
    assert s["daily_allowance"] == pytest.approx(9000 / 21)


def test_status_on_track():
    p = project_month_spend(3000, date(2026, 10, 10))  # projects 9300
    s = budget_status(10000, 3000, p)
    assert s["status"] == "on_track" and s["projected_overrun"] == 0
    assert s["pct_used"] == pytest.approx(0.3)


def test_no_watch_warning_in_first_week_even_if_pace_is_high():
    p = project_month_spend(4000, date(2026, 10, 2))  # would project 62000, but too early to trust
    assert budget_status(10000, 4000, p)["status"] == "on_track"


def test_no_budget_returns_none():
    assert budget_status(None, 500, project_month_spend(500, date(2026, 10, 10))) is None


def test_zero_budget_does_not_divide_by_zero():
    s = budget_status(0, 0, project_month_spend(0, date(2026, 10, 10)))
    assert s["pct_used"] is None


def test_last_day_of_month_has_no_daily_allowance():
    p = project_month_spend(9000, date(2026, 10, 31))
    assert p["days_left"] == 0
    assert budget_status(10000, 9000, p)["daily_allowance"] is None


def test_estimate_uses_this_month_once_reliable():
    amount, source = next_month_estimate(date(2026, 10, 10), 3000, prev_month_spend=99999)
    assert source == "this month's pace"
    assert amount == pytest.approx(3000 / 10 * 30)  # November has 30 days


def test_estimate_falls_back_to_last_month_early_in_month():
    amount, source = next_month_estimate(date(2026, 10, 3), 500, prev_month_spend=9000)  # September: 30 days
    assert source == "last month's spend"
    assert amount == pytest.approx(9000 / 30 * 30)


def test_estimate_none_without_history():
    assert next_month_estimate(date(2026, 10, 3), 0, None) is None
    assert next_month_estimate(date(2026, 10, 3), 500, 0) is None
