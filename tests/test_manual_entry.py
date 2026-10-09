"""Validation tests: no database needed."""
from datetime import date

import pytest

from src.ingestion.manual_entry import (
    clean_name,
    feed_from_units,
    normalize_phone,
    validate_catalogue_item,
    validate_cows,
    validate_feed,
    validate_milk_price,
    validate_yield,
)

TODAY = date(2026, 10, 9)
PAST = date(2026, 10, 8)


def test_yield_cleans_session_and_rounds():
    assert validate_yield(PAST, "  Morning ", "12.345", today=TODAY) == (PAST, "morning", 12.35)


def test_yield_allows_zero():
    assert validate_yield(PAST, "evening", 0, today=TODAY)[2] == 0


@pytest.mark.parametrize(
    "session,litres,day",
    [
        ("midnight", 5, PAST),   # unknown session
        ("morning", -1, PAST),   # negative
        ("morning", "abc", PAST),  # not a number
        ("morning", None, PAST),
        ("morning", 1000, PAST),  # implausible typo
        ("morning", 5, date(2026, 10, 10)),  # future
    ],
)
def test_yield_rejects_bad_input(session, litres, day):
    with pytest.raises(ValueError):
        validate_yield(day, session, litres, today=TODAY)


def test_feed_normalises_type_and_cost():
    assert validate_feed(PAST, "  Dairy   MEAL ", "4", "240.5", today=TODAY) == (PAST, "dairy meal", 4.0, 240.5)


def test_feed_cost_is_optional():
    assert validate_feed(PAST, "napier", 30, None, today=TODAY)[3] is None
    assert validate_feed(PAST, "napier", 30, "", today=TODAY)[3] is None


@pytest.mark.parametrize(
    "feed_type,kg,cost",
    [
        ("", 5, None),        # missing type
        ("   ", 5, None),
        ("hay", 0, None),     # zero kg
        ("hay", -2, None),
        ("hay", "lots", None),
        ("hay", 99999, None),  # implausible
        ("hay", 5, -10),      # negative cost
        ("hay", 5, "free"),
    ],
)
def test_feed_rejects_bad_input(feed_type, kg, cost):
    with pytest.raises(ValueError):
        validate_feed(PAST, feed_type, kg, cost, today=TODAY)


def test_feed_rejects_future_date():
    with pytest.raises(ValueError):
        validate_feed(date(2026, 10, 10), "hay", 5, today=TODAY)


@pytest.mark.parametrize(
    "raw",
    ["0712345678", "712345678", "254712345678", "+254712345678", "+254 712 345 678", "0712-345-678", "(0712) 345 678"],
)
def test_phone_normalises_to_e164(raw):
    assert normalize_phone(raw) == "+254712345678"


def test_phone_accepts_01_prefix_numbers():
    assert normalize_phone("0112345678") == "+254112345678"


@pytest.mark.parametrize("raw", ["", "071234567", "07123456789", "0212345678", "abc", "+1 415 555 0100", "0712x45678"])
def test_phone_rejects_bad_numbers(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)


# --- farm setup ---------------------------------------------------------------


def test_clean_name_tidies_case_and_spaces():
    assert clean_name("  Banana   TRUNKS ") == "banana trunks"


def test_catalogue_item_is_cleaned():
    assert validate_catalogue_item(" Banana Trunks", "Trunk ", "25", "40") == ("banana trunks", "trunk", 25.0, 40.0)


def test_catalogue_item_allows_free_feed():
    assert validate_catalogue_item("napier", "bundle", 10, 0)[3] == 0


@pytest.mark.parametrize(
    "name,unit,kg,kes",
    [
        ("", "trunk", 25, 40),        # no name
        ("hay", "  ", 25, 40),        # no unit
        ("hay", "bale", 0, 40),       # zero kg
        ("hay", "bale", -5, 40),
        ("hay", "bale", "heavy", 40),
        ("hay", "bale", 999999, 40),  # implausible
        ("hay", "bale", 20, -1),      # negative price
        ("hay", "bale", 20, "cheap"),
        ("hay", "bale", 20, 99999999),
    ],
)
def test_catalogue_item_rejects_bad_input(name, unit, kg, kes):
    with pytest.raises(ValueError):
        validate_catalogue_item(name, unit, kg, kes)


def test_milk_price_ok_and_rejects_bad():
    assert validate_milk_price("50") == 50.0
    for bad in (0, -5, "abc", None, 5000):
        with pytest.raises(ValueError):
            validate_milk_price(bad)


def test_cows_must_be_a_whole_number_not_in_the_future():
    assert validate_cows(PAST, "6", today=TODAY) == (PAST, 6)
    assert validate_cows(PAST, 0, today=TODAY)[1] == 0  # all dry is valid
    for bad in (6.5, -1, "six", None, 9999):
        with pytest.raises(ValueError):
            validate_cows(PAST, bad, today=TODAY)
    with pytest.raises(ValueError):
        validate_cows(date(2026, 10, 10), 6, today=TODAY)


def test_feed_from_units_converts_to_kg_and_cost():
    item = {"kg_per_unit": 25, "kes_per_unit": 40}
    assert feed_from_units(item, 6) == (150.0, 240.0)
    assert feed_from_units(item, "1.5") == (37.5, 60.0)
    for bad in (0, -1, "lots", None):
        with pytest.raises(ValueError):
            feed_from_units(item, bad)
