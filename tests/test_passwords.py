"""Password hashing and SMS login codes. Pure."""
from datetime import datetime, timedelta, timezone

import pytest

from src import logincode
from src.passwords import check_strength, hash_password, verify_password

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def test_a_password_checks_out_only_against_itself():
    h = hash_password("maziwa-bora-2026")
    assert verify_password("maziwa-bora-2026", h)
    assert not verify_password("maziwa-bora-2027", h) and not verify_password("", h)


def test_the_same_password_hashes_differently_each_time_and_is_never_stored_plain():
    a, b = hash_password("maziwa-bora-2026"), hash_password("maziwa-bora-2026")
    assert a != b and "maziwa" not in a and a.startswith("scrypt$")


def test_a_malformed_stored_value_is_simply_a_failed_login():
    for bad in ("", "garbage", "scrypt$1$2", None, "md5$x$y$z$a$b"):
        assert verify_password("anything", bad) is False


def test_password_strength_rules():
    check_strength("a-decent-pass")
    for bad in ("short", "11111111", " leading-space", "x" * 300, None):
        with pytest.raises(ValueError):
            check_strength(bad)


def test_codes_are_six_digits_and_unique_enough():
    codes = {logincode.new_code() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codes) and len(codes) > 150


def test_a_code_matches_only_itself_even_with_spaces_typed_in():
    salt = logincode.new_salt()
    h = logincode.hash_code("123456", salt)
    assert logincode.matches("123456", salt, h) and logincode.matches(" 123 456 ", salt, h)
    assert not logincode.matches("123457", salt, h) and not logincode.matches("", salt, h)
    assert "123456" not in h


def row(**kw):
    return {"used": False, "attempts": 0, "expires_at": NOW + timedelta(minutes=5), **kw}


def test_a_code_is_usable_only_when_fresh_unused_and_with_tries_left():
    assert logincode.usable(row(), NOW)
    assert not logincode.usable(row(used=True), NOW)
    assert not logincode.usable(row(attempts=logincode.MAX_ATTEMPTS), NOW)
    assert not logincode.usable(row(expires_at=NOW - timedelta(seconds=1)), NOW)


def test_sending_limits():
    assert logincode.may_send([], NOW) == (True, None)
    assert not logincode.may_send([NOW - timedelta(seconds=30)], NOW)[0]
    assert logincode.may_send([NOW - timedelta(seconds=61)], NOW)[0]
    many = [NOW - timedelta(minutes=10 + i) for i in range(logincode.MAX_CODES_PER_HOUR)]
    assert not logincode.may_send(many, NOW)[0]


def test_the_sms_fits_one_segment_and_says_the_code():
    from src.sms import sms_segments

    text = logincode.message("123456")
    assert "123456" in text and sms_segments(text) == 1
