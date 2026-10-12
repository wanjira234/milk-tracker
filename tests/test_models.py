"""Model tests: no database, no Streamlit. Simulated farms have a known true answer."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.models import (
    CONFIDENCE,
    cows_series,
    distinct_levels,
    feed_effects,
    model_frame,
)
from tests.sim_farm import make_farm

COSTS = {"dairy meal": 37.0, "banana trunks": 1.6, "napier": 0.0}


def by_feed(results):
    return {r["feed"]: r for r in results}


# --- small pieces ---------------------------------------------------------------


def test_cows_series_carries_forward_and_is_unknown_before_the_first_entry():
    idx = pd.date_range("2026-10-01", periods=10, freq="D")
    s = cows_series(
        [{"effective_date": date(2026, 10, 3), "cows_in_milk": 6}, {"effective_date": date(2026, 10, 7), "cows_in_milk": 5}],
        idx,
    )
    assert s[:2].isna().all()
    assert (s["2026-10-03":"2026-10-06"] == 6).all()
    assert (s["2026-10-07":] == 5).all()


def test_cows_series_with_no_entries_is_all_unknown():
    assert cows_series([], pd.date_range("2026-10-01", periods=3)).isna().all()


def test_cows_entry_before_the_window_still_applies():
    s = cows_series([{"effective_date": date(2026, 9, 1), "cows_in_milk": 7}], pd.date_range("2026-10-01", periods=3))
    assert (s == 7).all()


def test_distinct_levels():
    assert distinct_levels([5, 5, 5, 5]) == 1
    assert distinct_levels([4, 5, 6]) == 3
    assert distinct_levels([5.0, 5.2, 5.3]) == 1           # within 10% of each other: the same amount
    assert distinct_levels([0, 0, 5, 5, 10]) == 3          # zero counts as an amount
    assert distinct_levels([]) == 0


def _frame(litres, cows, feed):
    idx = pd.date_range("2026-10-01", periods=len(litres), freq="D")
    daily = pd.DataFrame({"litres": litres, "complete": True}, index=idx)
    return daily, pd.DataFrame(feed, index=idx), pd.Series(cows, index=idx, dtype=float)


def test_unknown_herd_makes_the_day_unusable():
    daily, feed, cows = _frame([30] * 4, [np.nan, 6, 6, 6], {"meal": [4, 4, 4, 4]})
    litres_pc, kg_pc, _ = model_frame(daily, feed, cows)
    assert np.isnan(litres_pc.iloc[0]) and np.isnan(kg_pc["meal"].iloc[0])
    assert litres_pc.iloc[1] == 5.0 and kg_pc["meal"].iloc[1] == pytest.approx(4 / 6)


def test_a_day_with_no_feed_logged_is_unknown_not_zero():
    daily, feed, cows = _frame([30] * 4, [6] * 4, {"meal": [4, 0, 4, 4]})
    _, kg_pc, lagged = model_frame(daily, feed, cows)
    assert np.isnan(kg_pc["meal"].iloc[1])
    assert lagged["meal"].iloc[2:].isna().all()  # every 3-day window from day 3 on touches the gap


def test_incomplete_milking_day_is_excluded():
    daily, feed, cows = _frame([30] * 4, [6] * 4, {"meal": [4] * 4})
    daily.loc[daily.index[1], "complete"] = False
    litres_pc, _, _ = model_frame(daily, feed, cows)
    assert np.isnan(litres_pc.iloc[1]) and not np.isnan(litres_pc.iloc[0])


# --- the agreed rules -----------------------------------------------------------


def test_too_few_days_gives_no_estimate():
    rng = np.random.default_rng(1)
    daily, feed_kg, cows = make_farm(rng, n=10, effect=1.0, levels=(0, 4, 8, 12))
    r = by_feed(feed_effects(daily, feed_kg, cows))
    assert all(x["status"] == "too_few_days" and x["slope"] is None for x in r.values())


def test_a_constant_ration_says_nothing():
    daily, feed_kg, cows = make_farm(np.random.default_rng(1), effect=1.0, levels=(0, 4, 8, 12))
    assert by_feed(feed_effects(daily, feed_kg, cows))["napier"]["status"] == "too_few_amounts"


def test_feeds_that_always_move_together_are_refused_not_guessed():
    daily, feed_kg, cows = make_farm(np.random.default_rng(2), effect=1.0, together=True, levels=(2, 4, 6, 8))
    r = by_feed(feed_effects(daily, feed_kg, cows))
    assert r["dairy meal"]["status"] == "moves_with" and r["dairy meal"]["moves_with"] == "banana trunks"
    assert r["banana trunks"]["status"] == "moves_with" and r["banana trunks"]["slope"] is None


def test_finds_a_real_effect_with_a_range_that_contains_the_truth():
    daily, feed_kg, cows = make_farm(np.random.default_rng(3), effect=1.0, levels=(0, 4, 8, 12))
    meal = by_feed(feed_effects(daily, feed_kg, cows))["dairy meal"]
    assert meal["status"] == "clear"
    assert meal["ci_low"] <= 1.0 <= meal["ci_high"] and meal["ci_low"] > 0


def test_a_feed_with_no_effect_is_not_called_clear_on_a_typical_farm():
    daily, feed_kg, cows = make_farm(np.random.default_rng(4), effect=0.0, levels=(2, 4, 6, 8))
    r = by_feed(feed_effects(daily, feed_kg, cows))
    assert r["dairy meal"]["status"] == "unclear"
    assert r["dairy meal"]["ci_low"] < 0 < r["dairy meal"]["ci_high"]


def test_error_budget_is_split_across_the_feeds_tested():
    daily, feed_kg, cows = make_farm(np.random.default_rng(5), effect=1.0, levels=(0, 4, 8, 12))
    both = [x for x in feed_effects(daily, feed_kg, cows) if x["slope"] is not None]
    assert len(both) == 2 and both[0]["confidence_used"] == pytest.approx(1 - (1 - CONFIDENCE) / 2)
    one = [x for x in feed_effects(daily, feed_kg[["dairy meal", "napier"]], cows) if x["slope"] is not None]
    assert len(one) == 1 and one[0]["confidence_used"] == pytest.approx(CONFIDENCE)


def test_margin_needs_both_price_and_feed_cost():
    daily, feed_kg, cows = make_farm(np.random.default_rng(3), effect=1.0, levels=(0, 4, 8, 12))
    assert by_feed(feed_effects(daily, feed_kg, cows))["dairy meal"]["margin_per_kg"] is None
    assert by_feed(feed_effects(daily, feed_kg, cows, price=50))["dairy meal"]["margin_per_kg"] is None
    r = by_feed(feed_effects(daily, feed_kg, cows, cost_per_kg=COSTS, price=50))["dairy meal"]
    assert r["margin_per_kg"] == pytest.approx(r["slope"] * 50 - 37.0)


def test_empty_feed_table_is_safe():
    daily, _, cows = make_farm(np.random.default_rng(1))
    assert feed_effects(daily, pd.DataFrame(index=daily.index), cows) == []


# --- calibration: repeat the checks that justified the rules ---------------------
# Fixed seeds, so these are repeatable. Thresholds leave room for sampling noise.


def _rates(sims, **farm):
    rng = np.random.default_rng(42)
    any_clear = meal_clear = meal_tested = 0
    for _ in range(sims):
        daily, feed_kg, cows = make_farm(rng, **farm)
        res = feed_effects(daily, feed_kg, cows)
        any_clear += any(r["status"] == "clear" for r in res)
        for r in res:
            if r["feed"] == "dairy meal" and r["slope"] is not None:
                meal_tested += 1
                meal_clear += r["status"] == "clear"
    return any_clear / sims, meal_clear / max(meal_tested, 1)


def test_false_alarms_stay_low_when_feed_does_nothing():
    any_clear, _ = _rates(150, effect=0.0, levels=(2, 4, 6, 8))
    assert any_clear <= 0.12  # nominal 5% per farm; measured about 8% over 300 farms


def test_a_cow_drying_off_does_not_cause_false_alarms_when_it_is_logged():
    any_clear, _ = _rates(150, effect=0.0, levels=(2, 4, 6, 8), dry_off_day=30)
    assert any_clear <= 0.12


def test_large_ration_swings_are_detected_almost_always():
    _, meal_clear = _rates(100, effect=1.0, levels=(0, 4, 8, 12))
    assert meal_clear >= 0.9  # measured 99%


def test_small_ration_swings_are_mostly_missed_which_is_why_the_app_says_so():
    _, meal_clear = _rates(100, effect=1.0, levels=(3, 4, 5, 6))
    assert meal_clear <= 0.45  # measured about 23%: advice stays rare unless the ration really varies
