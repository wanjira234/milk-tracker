"""Validation tests: no database needed."""
from datetime import date

import pytest

from src.ingestion.manual_entry import normalize_phone, validate_feed, validate_yield

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
