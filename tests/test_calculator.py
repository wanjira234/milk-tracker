import pandas as pd
import pytest

from src.calculator import FIXED_MEASURES, breakdown, money, price_per_kg, total_kg
from src.profit import profit_summary


def test_a_truck_load_counted_in_mtungis():
    kg = total_kg(150, 20)  # about 150 big mtungis in a Dyna load
    assert kg == 3000 and price_per_kg(15000, kg) == pytest.approx(5.0)


def test_breakdown_gives_the_price_of_each_everyday_measure():
    rows = {r["unit"]: r for r in breakdown(15000, 3000)}
    assert rows["tilly"]["kes"] == pytest.approx(5.0)
    assert rows["2 kg tilly"]["kes"] == pytest.approx(10.0)
    assert rows["mtungi"]["kes"] == pytest.approx(100.0)
    assert "bucket" not in rows  # a bucket's weight depends on the feed: only with a kg given


def test_a_bucket_appears_once_its_weight_is_given():
    rows = {r["unit"]: r for r in breakdown(15000, 3000, bucket_kg=8)}
    assert rows["bucket"]["kg"] == 8 and rows["bucket"]["kes"] == pytest.approx(40.0)


def test_a_free_feed_is_allowed_but_a_missing_price_is_not():
    assert price_per_kg(0, 100) == 0
    for bad in (None, "", "abc", -5, float("nan")):
        with pytest.raises(ValueError):
            price_per_kg(bad, 100)


def test_nonsense_amounts_are_refused():
    for count, each in ((0, 20), (-1, 20), (5, 0), ("x", 1), (1e9, 20)):
        with pytest.raises(ValueError):
            total_kg(count, each)
    with pytest.raises(ValueError):
        price_per_kg(100, 0)
    with pytest.raises(ValueError):
        price_per_kg(10**9, 100)


def test_fixed_measures_match_what_the_farm_uses():
    assert {u: kg for u, kg in FIXED_MEASURES.values()} == {"tilly": 1.0, "2 kg tilly": 2.0, "mtungi": 20.0, "bag": 50.0}


def test_money_keeps_cents_for_small_prices():
    assert money(3.3333) == "KES 3.33" and money(100.4) == "KES 100" and money(1234.5) == "KES 1,234"


# --- profit ---------------------------------------------------------------------


def daily(rows):
    return pd.DataFrame(rows, columns=["litres", "complete", "cost_kes"])


def test_profit_is_milk_income_minus_feed_cost_on_complete_days_only():
    d = daily([(100.0, True, 1000.0), (90.0, True, 900.0), (30.0, False, 700.0)])  # day 3 is incomplete
    s = profit_summary(d, 50)
    assert s["days"] == 2 and s["litres"] == 190
    assert s["income"] == 9500 and s["feed_cost"] == 1900 and s["profit"] == 7600
    assert s["profit_per_day"] == 3800 and s["profit_per_litre"] == pytest.approx(40)
    assert s["feed_per_100"] == pytest.approx(20)


def test_a_losing_period_shows_a_negative_profit():
    s = profit_summary(daily([(10.0, True, 800.0)]), 50)
    assert s["profit"] == -300 and s["feed_per_100"] > 100


def test_no_price_or_no_complete_days_gives_nothing_to_show():
    assert profit_summary(daily([(100.0, True, 10.0)]), None) is None
    assert profit_summary(daily([(100.0, False, 10.0)]), 50) is None
    assert profit_summary(daily([]), 50) is None


def test_ai_semen_is_a_separate_cost_that_leaves_the_feed_margin_alone():
    d = daily([(100.0, True, 1000.0), (90.0, True, 900.0)])
    s = profit_summary(d, 50, semen_kes=2700, semen_n=2)
    assert s["profit"] == 7600 and s["semen"] == 2700 and s["semen_n"] == 2 and s["after_semen"] == 4900
    plain = profit_summary(d, 50)
    assert plain["semen"] == 0 and plain["after_semen"] == plain["profit"]


def test_uncosted_entries_are_carried_through():
    assert profit_summary(daily([(100.0, True, 10.0)]), 50, uncosted=3)["uncosted"] == 3


# --- water -----------------------------------------------------------------------

from datetime import date  # noqa: E402

from src.ingestion.manual_entry import validate_water  # noqa: E402
from src.water import water_summary  # noqa: E402

D = date(2026, 10, 20)


def test_water_counted_in_20_litre_buckets():
    assert validate_water(D, 6, bucket=True, today=D) == (D, 120.0)
    assert validate_water(D, 85.5, today=D) == (D, 85.5)


def test_nonsense_water_is_refused():
    for amount in (0, -5, "abc", float("nan"), 1_000_000):
        with pytest.raises(ValueError):
            validate_water(D, amount, today=D)
    with pytest.raises(ValueError):
        validate_water(date(2026, 10, 21), 10, today=D)


def test_water_summary_averages_over_recorded_days_only():
    assert water_summary([]) is None
    s = water_summary([{"log_date": D, "litres": 100}, {"log_date": D, "litres": 140}], cows=6)
    assert s["days"] == 2 and s["avg_per_day"] == 120 and s["per_cow"] == 20
    assert water_summary([{"log_date": D, "litres": 100}])["per_cow"] is None


def test_a_load_fed_out_over_days_is_counted_in_buckets():
    from src.calculator import load_buckets

    assert load_buckets(10, 5) == 50
    for bad in ((0, 5), (10, 0), (-1, 5), ("x", 5), (10_000, 100)):
        with pytest.raises(ValueError):
            load_buckets(*bad)
