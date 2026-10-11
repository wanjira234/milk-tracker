"""SMS facts, templates and the safety check on rewordings. No network, no database."""
import pytest

from src.messages import (
    APP_NAME,
    _numbers_in,
    check_message,
    facts_from_decision,
    normalize,
    template_message,
)
from src.sms import sms_segments


def advice(verdict="increase", feed="dairy meal", step_kg=0.4, step_units=None, unit="bag", gain=15.0, recent=4.0):
    a = {"feed": feed, "verdict": verdict, "step_kg": step_kg, "step_units": step_units, "unit": unit,
         "gain_per_day_at_least": gain, "recent_kg": recent}
    return {"kind": "advice", "advice": a, "nudges": [], "feeds": []}


def nudge(*items):
    return {"kind": "nudge", "advice": None, "nudges": list(items), "feeds": []}


NO_COWS = {"code": "no_cows", "text": "tell the app how many cows are in milk"}
NO_PRICE = {"code": "no_price", "text": "set the milk price per litre"}
FEW_DAYS = {"code": "few_days", "days_needed": 5, "text": "5 more day(s) ..."}
NO_COST = {"code": "no_cost", "feed": "napier", "text": "add the price of napier"}


# --- facts -----------------------------------------------------------------------


def test_nothing_to_say_means_no_message():
    assert facts_from_decision({"kind": "none", "advice": None, "nudges": [], "feeds": []}) is None


def test_advice_facts_in_kg():
    f = facts_from_decision(advice())
    assert f["amount"] == "0.4 kg" and f["gain"] == 15 and f["percent"] == 10
    assert f["numbers"] == [0.4, 10.0, 15.0]


def test_advice_facts_use_the_farms_own_unit_with_a_sensible_plural():
    assert facts_from_decision(advice(step_units=1.5, unit="trunk"))["amount"] == "1.5 trunks"
    assert facts_from_decision(advice(step_units=1, unit="trunk"))["amount"] == "1 trunk"
    assert facts_from_decision(advice(step_units=2, unit="bags"))["amount"] == "2 bags"


def test_kg_are_rounded_to_something_a_farmer_can_measure():
    # always rounded DOWN, so the step never passes the 10% limit
    assert facts_from_decision(advice(step_kg=12.94, recent=130))["amount"] == "12 kg"
    assert facts_from_decision(advice(step_kg=3.26, recent=32.6))["amount"] == "3.2 kg"
    assert facts_from_decision(advice(step_kg=0.19, recent=1.9))["amount"] == "0.1 kg"
    assert facts_from_decision(advice(step_kg=0.04, recent=0.4)) is None


def test_the_gain_and_percent_describe_the_amount_shown_not_the_unrounded_step():
    f = facts_from_decision(advice(step_kg=3.26, recent=32.6, gain=15.0))
    assert f["amount"] == "3.2 kg" and f["gain"] == 14 and f["percent"] == 9  # 3.2 / 32.6 = 9.8%, shown rounded down
    assert f["numbers"] == [3.2, 9.0, 14.0]
    g = facts_from_decision(advice(step_kg=12.5, step_units=0.5, unit="trunk", recent=200, gain=20.0))
    assert g["amount"] == "0.5 trunks" and g["gain"] == 20 and g["percent"] == 6


def test_a_step_too_small_to_state_sends_nothing_rather_than_zero_kg():
    assert facts_from_decision(advice(step_kg=0.004)) is None


def test_a_gain_that_rounds_to_zero_is_left_out_not_stated_as_kes_0():
    f = facts_from_decision(advice(gain=0.3))
    assert f["gain"] is None and "KES" not in template_message(f)


def test_nudge_facts_use_only_the_first_two_items():
    f = facts_from_decision(nudge(NO_COWS, NO_PRICE, FEW_DAYS))
    assert [i["code"] for i in f["items"]] == ["no_cows", "no_price"] and f["numbers"] == []


def test_nudge_facts_carry_the_days_and_the_feed():
    f = facts_from_decision(nudge(FEW_DAYS, NO_COST))
    assert f["numbers"] == [5.0] and f["feeds"] == ["napier"] and 3.0 in f["extra_numbers"]


def test_unknown_language_is_refused():
    with pytest.raises(ValueError):
        facts_from_decision(advice(), "fr")


# --- templates ---------------------------------------------------------------------


def test_english_templates_say_what_the_decision_says():
    inc = template_message(facts_from_decision(advice("increase")))
    dec = template_message(facts_from_decision(advice("decrease", feed="banana trunks", step_kg=2.5, gain=40)))
    assert inc.startswith(APP_NAME) and "more dairy meal pays" in inc and "0.4 kg more a day" in inc and "KES 15" in inc
    assert "less banana trunks saves money" in dec and "2.5 kg less a day" in dec and "saves at least KES 40" in dec


def test_nudge_templates():
    en = template_message(facts_from_decision(nudge(NO_COWS, FEW_DAYS)))
    assert en == f"{APP_NAME}: to give you feed advice, please tell the app how many cows are in milk and log 5 more day(s) with all 3 milkings and the feed."
    assert "napier" in template_message(facts_from_decision(nudge(NO_COST)))


@pytest.mark.parametrize("lang", ["en", "sw"])
@pytest.mark.parametrize(
    "decision",
    [
        advice("increase"),
        advice("decrease", gain=40),
        advice("increase", feed="pineapple waste", step_units=1.5, unit="wheelbarrow", gain=120),
        advice("decrease", feed="extra protein mix"),     # the name contains a direction word
        advice("increase", feed="50kg dairy meal"),       # the name contains digits
        advice("increase", gain=2500),                    # a big number
        nudge(NO_COWS),
        nudge(NO_COWS, NO_PRICE),
        nudge(FEW_DAYS, NO_COST),
    ],
)
def test_every_template_passes_its_own_safety_check(decision, lang):
    f = facts_from_decision(decision, lang)
    assert check_message(template_message(f), f) == []


def test_a_typical_english_advice_sms_is_one_segment_and_the_longest_fit_in_two():
    assert sms_segments(template_message(facts_from_decision(advice()))) == 1
    longest = facts_from_decision(advice("decrease", feed="pineapple waste", step_units=12.5, unit="wheelbarrow", gain=12500))
    assert sms_segments(template_message(longest)) <= 2


# --- the check on a rewording --------------------------------------------------------

F = facts_from_decision(advice())  # increase dairy meal, 0.4 kg, 10%, KES 15
GOOD = "Milk Tracker: dairy meal is paying on your farm. Add 0.4 kg more a day (10% more) and keep logging. At least KES 15 a day."


def problems(text, facts=F):
    return check_message(text, facts)


def test_a_faithful_rewording_passes():
    assert problems(GOOD) == []


@pytest.mark.parametrize(
    "text,expected",
    [
        (GOOD.replace("0.4", "4"), "missing the number 0.4"),
        (GOOD.replace("KES 15", "KES 150"), "missing the number 15"),
        (GOOD + " Call 0712345678.", "not in the facts"),
        (GOOD.replace("dairy meal", "feed"), "does not name the feed"),
        (GOOD.replace("more a day (10% more)", "less a day (10% less)"), "opposite"),
        (GOOD + " This is guaranteed.", ""),                       # 'guarantee' is not a substring of 'guaranteed'? see below
        (GOOD + " I guarantee it.", "promise"),
        (GOOD + " See www.feeds.co.ke", "link"),
        (GOOD + " Good luck \U0001F404", "outside the basic SMS alphabet"),
        (GOOD.replace("dairy meal", "**dairy meal**"), "formatting"),
        (GOOD + " " + "word " * 60, "too long"),
        ("", "empty message"),
    ],
)
def test_the_check_catches_what_a_model_might_get_wrong(text, expected):
    found = problems(text)
    if expected == "":
        assert any("promise" in p for p in found)
    else:
        assert any(expected in p for p in found), found


def test_smart_punctuation_is_normalised_not_rejected():
    fancy = "Milk Tracker: dairy meal is paying on your farm. Add 0.4 kg more a day (10% more) – keep logging. At least KES 15 a day. Don’t stop."
    assert problems(fancy) == []
    assert normalize("it’s “ok” — yes…\n\n done") == 'it\'s "ok" - yes... done'


def test_a_thousands_separator_is_one_number():
    assert _numbers_in("KES 1,500 and 12,345.5") == [1500.0, 12345.5]
    f = facts_from_decision(advice(gain=1500))
    assert problems("Milk Tracker: dairy meal pays. Add 0.4 kg more a day (10% more). Worth at least KES 1,500 a day.", f) == []


def test_opposite_direction_is_caught_in_swahili_too():
    f = facts_from_decision(advice("increase"), "sw")
    bad = "Milk Tracker: punguza dairy meal kwa 0.4 kg kwa siku (10%). Faida angalau KES 15."
    assert any("opposite" in p for p in check_message(bad, f))


def test_a_decrease_message_may_not_say_more():
    f = facts_from_decision(advice("decrease"))
    assert any("opposite" in p for p in check_message(GOOD, f))


def test_a_direction_word_inside_the_feed_name_is_not_a_false_alarm():
    f = facts_from_decision(advice("decrease", feed="extra protein mix"))
    assert check_message("Milk Tracker: less extra protein mix saves money. Try 0.4 kg less a day (10% less). Saves at least KES 15.", f) == []


def test_extra_numbers_are_allowed_but_not_required():
    f = facts_from_decision(nudge(FEW_DAYS))
    assert check_message("Milk Tracker: please log 5 more days with the feed.", f) == []          # '3 milkings' dropped: fine
    assert check_message("Milk Tracker: please log 5 more days with all 3 milkings and the feed.", f) == []
    assert any("not in the facts" in p for p in check_message("Milk Tracker: please log 7 more days.", f))
