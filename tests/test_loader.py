"""Loader tests: no database. Simulated farms are turned into rows and run end to end."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from src.loader import RECENT_FEED_DAYS, assess_rows, recent_kg_per_day, window
from src.models import WINDOW_DAYS
from tests.sim_farm import make_farm, to_rows

# The simulated farm covers 2026-08-01 .. 2026-09-29, so "today" is the day after.
TODAY = date(2026, 9, 30)
START, END = window(TODAY)
BAG = [{"name": "dairy meal", "unit": "bag", "kg_per_unit": 70, "kes_per_unit": 350}]  # KES 5 per kg


def farm(seed=3, **kw):
    kw = {"effect": 1.0, "levels": (0, 4, 8, 12), **kw}
    return to_rows(*make_farm(np.random.default_rng(seed), **kw))


def assess(rows, price=50, catalogue=BAG, logged=None, herd=None):
    y, f, h = rows
    return assess_rows(y, f, h if herd is None else herd, price, catalogue, logged or {}, START, END)


# --- the window ---------------------------------------------------------------


def test_window_ends_yesterday_and_spans_the_model_window():
    start, end = window(date(2026, 10, 10))
    assert end == date(2026, 10, 9)
    assert (end - start).days == WINDOW_DAYS - 1


# --- recent feed ----------------------------------------------------------------


def test_recent_amount_ignores_days_nobody_logged():
    idx = pd.date_range("2026-10-01", periods=6, freq="D")
    feed = pd.DataFrame({"meal": [4.0, 4.0, 0.0, 0.0, 4.0, 4.0]}, index=idx)  # two unlogged days
    assert recent_kg_per_day(feed)["meal"] == pytest.approx(4.0)  # not 2.67


def test_recent_amount_uses_only_the_last_days():
    idx = pd.date_range("2026-09-01", periods=40, freq="D")
    feed = pd.DataFrame({"meal": [10.0] * 26 + [2.0] * 14}, index=idx)
    assert RECENT_FEED_DAYS == 14
    assert recent_kg_per_day(feed)["meal"] == pytest.approx(2.0)


def test_recent_amount_with_no_feed_is_empty():
    assert recent_kg_per_day(pd.DataFrame(index=pd.date_range("2026-10-01", periods=3))) == {}
    assert recent_kg_per_day(pd.DataFrame({"meal": [0.0, 0.0]}, index=pd.date_range("2026-10-01", periods=2))) == {}


# --- end to end: rows in, decision out -----------------------------------------


def test_a_real_effect_with_everything_set_up_gives_advice_within_ten_percent():
    r = assess(farm())
    d = r["decision"]
    assert d["kind"] == "advice" and d["advice"]["feed"] == "dairy meal" and d["advice"]["verdict"] == "increase"
    a = d["advice"]
    assert a["step_kg"] <= 0.10 * r["recent_kg"]["dairy meal"] + 1e-9
    assert a["gain_per_day_at_least"] > 0
    assert r["costs"]["dairy meal"] == pytest.approx(5.0)  # catalogue price per kg
    assert r["usable_days"] >= 14


def test_no_milk_price_means_a_nudge_never_advice():
    d = assess(farm(), price=None)["decision"]
    assert d["kind"] == "nudge" and d["advice"] is None
    assert "no_price" in [n["code"] for n in d["nudges"]]


def test_no_cows_logged_means_a_nudge_never_advice():
    d = assess(farm(), herd=[])["decision"]
    assert d["kind"] == "nudge" and d["advice"] is None
    assert "no_cows" in [n["code"] for n in d["nudges"]]


def test_a_new_farm_is_told_exactly_how_many_days_are_missing():
    r = assess(farm(n=10))
    nudge = next(n for n in r["decision"]["nudges"] if n["code"] == "few_days")
    assert r["decision"]["kind"] == "nudge"
    assert nudge["days_needed"] == 14 - r["usable_days"] > 0


def test_a_farm_with_no_records_at_all_asks_for_the_basics_and_does_not_crash():
    r = assess_rows([], [], [], None, [], {}, START, END)
    codes = [n["code"] for n in r["decision"]["nudges"]]
    assert r["decision"]["kind"] == "nudge" and r["usable_days"] == 0
    assert codes[:3] == ["no_cows", "no_price", "few_days"]


def test_a_feed_not_in_the_catalogue_uses_the_price_actually_paid():
    r = assess(farm(), catalogue=[], logged={"dairy meal": 5.0})
    assert r["costs"] == {"dairy meal": 5.0}
    assert r["decision"]["kind"] == "advice"


def test_with_no_price_for_a_clear_feed_it_asks_for_the_price():
    d = assess(farm(), catalogue=[], logged={})["decision"]
    assert d["kind"] == "nudge"
    assert any(n["code"] == "no_cost" and n["feed"] == "dairy meal" for n in d["nudges"])


def test_days_with_fewer_than_three_milkings_are_not_used():
    y, f, h = farm()
    full = assess((y, f, h))["usable_days"]
    partial = [dict(r, sessions=1) if i % 2 == 0 else r for i, r in enumerate(y)]
    assert assess((partial, f, h))["usable_days"] < full


def test_nothing_is_read_from_today_or_later():
    y, f, h = farm()
    base = assess((y, f, h))["decision"]["kind"]
    junk_y = y + [{"log_date": TODAY, "litres": 9999, "sessions": 3}]
    junk_f = f + [{"log_date": TODAY, "feed_type": "dairy meal", "kg": 999, "cost_kes": None}]
    r = assess((junk_y, junk_f, h))
    assert r["decision"]["kind"] == base
    assert r["recent_kg"]["dairy meal"] < 20  # the 999 kg entry was not seen
