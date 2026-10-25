"""Two-factor codes: the maths (RFC 6238 test vector) and the replay / window rules. No database needed."""
import base64

from src import totp

SECRET = base64.b32encode(b"12345678901234567890").decode()  # the RFC 6238 test key


def test_matches_the_rfc_6238_test_vector():
    assert totp.code_for(SECRET, 59 // 30) == "287082"
    assert totp.code_for(SECRET, 1111111109 // 30) == "081804"


def test_a_code_works_now_and_a_step_either_side_but_not_further():
    t = 1_700_000_000
    step = totp.step_at(t)
    assert totp.verify(SECRET, totp.code_for(SECRET, step), now=t) == step
    assert totp.verify(SECRET, totp.code_for(SECRET, step - 1), now=t) == step - 1
    assert totp.verify(SECRET, totp.code_for(SECRET, step + 1), now=t) == step + 1
    assert totp.verify(SECRET, totp.code_for(SECRET, step - 3), now=t) is None


def test_a_used_code_is_refused_the_second_time():
    t = 1_700_000_000
    step = totp.step_at(t)
    code = totp.code_for(SECRET, step)
    assert totp.verify(SECRET, code, now=t, after_step=step) is None
    assert totp.verify(SECRET, code, now=t, after_step=step - 1) == step


def test_junk_is_refused():
    for bad in ("", None, "12345", "1234567", "abcdef", "12 34"):
        assert totp.verify(SECRET, bad, now=1_700_000_000) is None


def test_new_secrets_are_random_and_decode():
    a, b = totp.new_secret(), totp.new_secret()
    assert a != b and len(base64.b32decode(a + "=" * (-len(a) % 8))) == 20


def test_the_setup_link_names_the_app_and_carries_the_key():
    u = totp.uri("ABC", "a@b.co")
    assert u.startswith("otpauth://totp/Maziwa%20Plus:a%40b.co?secret=ABC") and "issuer=Maziwa%20Plus" in u
