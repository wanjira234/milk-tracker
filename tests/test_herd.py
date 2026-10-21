"""Calf / heifer / cow cards, family lines and the milking count. Pure."""
from datetime import date, timedelta

from src.herd import age_text, animal_card, milking_summary

T = date(2026, 10, 21)


def cow(kind="cow", **kw):
    return {"id": 1, "kind": kind, "tag": "A", "sex": "female", "born_on": None, "weaned_on": None, **kw}


def ev(kind, days_ago, semen=None):
    return {"event_date": T - timedelta(days=days_ago), "kind": kind, "semen": semen}


def test_age_in_plain_words():
    assert age_text(T - timedelta(days=12), T) == "12 day(s) old"
    assert age_text(T - timedelta(days=100), T) == "3 months old"
    assert age_text(T - timedelta(days=3 * 365), T) == "3 years old"
    assert age_text(T + timedelta(days=1), T) is None


def test_a_calf_on_milk_knows_its_mother_and_when_weaning_is_usual():
    c = animal_card(cow("calf", born_on=T - timedelta(days=30)), [], "Wanjiku", [], T)
    assert c["stage"] == "Calf" and "still on milk" in c["status"] and "30 day(s) old" in c["status"]
    assert c["family"] == ["Mother: Wanjiku"] and "about 3 months" in c["next"] and c["milk"] is None


def test_an_old_enough_calf_is_flagged_for_weaning_and_a_weaned_one_is_not():
    old = animal_card(cow("calf", born_on=T - timedelta(days=120)), [], None, [], T)
    assert "Old enough to wean" in old["next"]
    done = animal_card(cow("calf", born_on=T - timedelta(days=120), weaned_on=T - timedelta(days=5)), [], None, [], T)
    assert "weaned" in done["status"] and done["next"] is None and "still on milk" not in done["status"]


def test_a_heifer_waiting_for_her_first_heat():
    young = animal_card(cow("heifer", born_on=T - timedelta(days=300)), [], None, [], T)
    assert young["stage"] == "Heifer" and young["status"] == "Waiting for first heat" and "about 15 months" in young["next"]
    ready = animal_card(cow("heifer", born_on=T - timedelta(days=500)), [], None, [], T)
    assert "Old enough to serve" in ready["next"]
    assert animal_card(cow("heifer"), [], None, [], T)["next"] == "Watch for her first heat."


def test_a_heifer_that_has_been_served_shows_her_breeding_status():
    c = animal_card(cow("heifer"), [ev("served", 30, "Friesian - Kamau")], None, [], T)
    assert c["status"].startswith("Served") and c["milk"] is None


def test_a_cow_shows_milking_or_dry_and_her_calves():
    kids = [{"tag": "Nyota", "born_on": date(2026, 3, 12)}]
    milking = animal_card(cow(), [ev("calved", 100)], None, kids, T)
    assert milking["milk"] == "Milking" and milking["family"] == ["Calves: Nyota (born 12 Mar 2026)"]
    dry = animal_card(cow(), [ev("served", 250), ev("confirmed_pregnant", 190)], None, [], T)
    assert dry["milk"] == "Dry"  # due in 33 days: inside the 60-day dry period


def test_dried_off_by_hand_until_she_calves():
    assert animal_card(cow(), [ev("calved", 200), ev("dried_off", 5)], None, [], T)["milk"] == "Dry"
    assert animal_card(cow(), [ev("calved", 200), ev("dried_off", 100), ev("calved", 5)], None, [], T)["milk"] == "Milking"


def test_milking_count_ignores_calves_and_heifers_and_counts_unrecorded_cows_as_milking():
    cows = [cow(id=1), cow(id=2), cow(id=3), cow("heifer", id=4), cow("calf", id=5)]
    events = {2: [ev("dried_off", 3)], 3: [ev("served", 250), ev("confirmed_pregnant", 190)]}
    assert milking_summary(cows, events, T) == (1, 2)
