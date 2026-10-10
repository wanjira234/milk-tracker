"""Decision-rule tests: no database, no model fitting. Effects are written by hand."""
import random

import pytest

from src.suggestions import MAX_STEP, current_cost_per_kg, decide


def clear(feed, lo, hi, slope=None):
    return {"feed": feed, "status": "clear", "slope": (lo + hi) / 2 if slope is None else slope, "ci_low": lo, "ci_high": hi}


def other(feed, status, **kw):
    return {"feed": feed, "status": status, "slope": None, "ci_low": None, "ci_high": None, **kw}


def run(effects, **over):
    args = dict(
        milk_price=50.0, cost_per_kg={"dairy meal": 5.0, "banana trunks": 1.6},
        recent_kg={"dairy meal": 20.0, "banana trunks": 100.0},
        usable_days=30, cows_known=True,
        catalogue={"dairy meal": {"unit": "bag", "kg_per_unit": 70}, "banana trunks": {"unit": "trunk", "kg_per_unit": 25}},
    )
    args.update(over)
    return decide(effects, **args)


# --- data nudges: what is missing, never advice -----------------------------------


def test_few_days_gives_a_nudge_with_the_exact_number_missing():
    r = run([other("dairy meal", "too_few_days")], usable_days=9)
    assert r["kind"] == "nudge" and r["advice"] is None
    assert r["nudges"][0] == {"code": "few_days", "days_needed": 5, "text": "5 more day(s) with all 3 milkings and the feed logged"}


def test_unknown_herd_is_the_first_thing_asked_for():
    r = run([], cows_known=False, usable_days=0, milk_price=None)
    assert r["kind"] == "nudge"
    assert [n["code"] for n in r["nudges"]][:3] == ["no_cows", "no_price", "few_days"]


def test_never_advice_while_cows_or_price_are_missing_even_if_the_model_found_something():
    assert run([clear("dairy meal", 1.0, 2.0)], cows_known=False)["kind"] == "nudge"
    assert run([clear("dairy meal", 1.0, 2.0)], milk_price=None)["kind"] == "nudge"


def test_a_clear_feed_with_no_price_asks_for_the_price_not_a_guess():
    r = run([clear("dairy meal", 1.0, 2.0)], cost_per_kg={})
    assert r["kind"] == "nudge" and r["nudges"][0] == {"code": "no_cost", "feed": "dairy meal", "text": "add the price of dairy meal"}


def test_nothing_to_say_sends_nothing():
    r = run([other("dairy meal", "unclear"), other("banana trunks", "too_few_amounts")])
    assert r["kind"] == "none" and r["nudges"] == []


def test_a_constant_ration_is_not_turned_into_an_sms():
    # needing variation is a fact about the farm, shown on the dashboard, not a nudge to experiment
    r = run([other("dairy meal", "too_few_amounts")])
    assert r["kind"] == "none"
    assert r["feeds"][0]["verdict"] == "no_evidence" and "nothing to learn" in r["feeds"][0]["reason"]


def test_feeds_that_move_together_say_which_one():
    r = run([other("dairy meal", "moves_with", moves_with="banana trunks")])
    assert "banana trunks" in r["feeds"][0]["reason"]


# --- advice: only when even the pessimistic end pays -----------------------------


def test_increase_when_even_the_low_end_beats_the_cost():
    # low end 0.3 L/kg x KES 50 = 15 vs cost 5: pays
    r = run([clear("dairy meal", 0.3, 1.9)])
    assert r["kind"] == "advice" and r["advice"]["verdict"] == "increase"
    assert r["advice"]["gain_per_day_at_least"] == pytest.approx(2.0 * (0.3 * 50 - 5))


def test_hold_when_it_moves_milk_but_might_not_pay():
    # low end 0.3 x 50 = 15 < cost 37, high end pays: a real effect, but unclear whether it pays
    r = run([clear("dairy meal", 0.3, 1.9)], cost_per_kg={"dairy meal": 37.0})
    assert r["kind"] == "none" and r["feeds"][0]["verdict"] == "hold"


def test_decrease_when_even_the_high_end_loses_money():
    # high end 0.1 x 50 = 5 < cost 37 even if the effect is on the optimistic side
    r = run([clear("dairy meal", 0.02, 0.1)], cost_per_kg={"dairy meal": 37.0})
    assert r["advice"]["verdict"] == "decrease"
    assert r["advice"]["gain_per_day_at_least"] == pytest.approx(2.0 * (37.0 - 0.1 * 50))


def test_decrease_when_more_feed_lowers_milk():
    r = run([clear("dairy meal", -0.9, -0.2)], cost_per_kg={"dairy meal": 5.0})
    assert r["advice"]["verdict"] == "decrease"


def test_the_milk_price_decides_whether_the_same_effect_pays():
    effect = [clear("dairy meal", 0.3, 1.9)]
    assert run(effect, cost_per_kg={"dairy meal": 12.0}, milk_price=50)["advice"]["verdict"] == "increase"
    assert run(effect, cost_per_kg={"dairy meal": 12.0}, milk_price=30)["kind"] == "none"  # 0.3 x 30 = 9 < 12


def test_step_is_ten_percent_and_expressed_in_farm_units():
    a = run([clear("dairy meal", 0.3, 1.9)])["advice"]
    assert a["step_kg"] == pytest.approx(2.0) and a["recent_kg"] == 20.0
    assert a["unit"] == "bag" and a["step_units"] is None  # 2 kg is under half a 70 kg bag: say it in kg
    b = run([clear("banana trunks", 0.05, 0.4)], cost_per_kg={"banana trunks": 1.0}, recent_kg={"banana trunks": 100.0})["advice"]
    assert b["step_kg"] == pytest.approx(10.0) and b["step_units"] == 0.5 and b["unit"] == "trunk"  # 10 kg of 25 kg trunks


def test_a_step_never_exceeds_the_agreed_maximum():
    rng = random.Random(0)
    for _ in range(300):
        lo = rng.uniform(-1, 2)
        hi = lo + rng.uniform(0.01, 2)
        recent = rng.uniform(0.5, 500)
        r = run([clear("dairy meal", lo, hi)], cost_per_kg={"dairy meal": rng.uniform(0, 60)}, recent_kg={"dairy meal": recent})
        if r["kind"] == "advice":
            assert r["advice"]["step_kg"] <= MAX_STEP * recent + 1e-9
            assert r["advice"]["gain_per_day_at_least"] > 0   # never recommends a change that could lose money


def test_a_feed_not_fed_recently_cannot_be_changed_by_ten_percent():
    r = run([clear("dairy meal", 0.3, 1.9)], recent_kg={"dairy meal": 0.0})
    assert r["kind"] == "none" and r["feeds"][0]["verdict"] == "hold"


def test_only_one_feed_is_recommended_the_one_that_pays_most():
    # dairy meal: step 2 kg x (0.3 x 50 - 5)  = KES 20 a day at least
    # banana trunks: step 10 kg x (0.1 x 50 - 1) = KES 40 a day at least
    effects = [clear("dairy meal", 0.3, 1.9), clear("banana trunks", 0.1, 0.5)]
    r = run(effects, cost_per_kg={"dairy meal": 5.0, "banana trunks": 1.0}, recent_kg={"dairy meal": 20.0, "banana trunks": 100.0})
    gains = {a["feed"]: a["gain_per_day_at_least"] for a in r["feeds"] if a["verdict"] == "increase"}
    assert gains == {"dairy meal": pytest.approx(20.0), "banana trunks": pytest.approx(40.0)}  # both qualify
    assert r["advice"]["feed"] == "banana trunks"  # only the better one is recommended


# --- costs ----------------------------------------------------------------------


def test_catalogue_price_wins_over_past_entries():
    costs = current_cost_per_kg(
        [{"name": "banana trunks", "kg_per_unit": 25, "kes_per_unit": 50}],
        {"banana trunks": 1.6, "hay": 23.3, "napier": None},
    )
    assert costs == {"banana trunks": 2.0, "hay": 23.3}
