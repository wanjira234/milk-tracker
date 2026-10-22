"""One-time SMS login codes. Pure: no database, no SMS.

A code is 6 digits, valid for 10 minutes, and allows 5 wrong tries. Only a keyed hash is stored.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

CODE_DIGITS = 6
CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
RESEND_GAP = timedelta(seconds=60)
MAX_CODES_PER_HOUR = 5


def new_code():
    return "".join(secrets.choice("0123456789") for _ in range(CODE_DIGITS))


def new_salt():
    return secrets.token_hex(16)


def hash_code(code, salt):
    return hmac.new(salt.encode(), code.encode(), hashlib.sha256).hexdigest()


def matches(entered, salt, stored_hash):
    entered = "".join(str(entered).split())
    return hmac.compare_digest(hash_code(entered, salt), stored_hash)


def usable(row, now):
    """A code can be tried only if it is unused, unexpired, and has tries left."""
    return (not row["used"]) and row["attempts"] < MAX_ATTEMPTS and now < row["expires_at"]


def may_send(recent_created_at, now):
    """(ok, reason). `recent_created_at` = when this person's codes in the last hour were made."""
    if recent_created_at and now - max(recent_created_at) < RESEND_GAP:
        return False, "wait a minute before asking for another code"
    if len(recent_created_at) >= MAX_CODES_PER_HOUR:
        return False, "too many codes requested: try again in an hour"
    return True, None


def message(code):
    return f"Milk Tracker: your login code is {code}. It works for 10 minutes. Do not share it."
