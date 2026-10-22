"""Password hashing with scrypt from the standard library (no extra package). Pure.

A stored password looks like  scrypt$N$r$p$salt$hash  (salt and hash in base64): the settings are
stored with it, so they can be raised later without locking anyone out.
"""
import base64
import hashlib
import hmac
import secrets

N, R, P = 2**14, 8, 1
MIN_LENGTH = 8
MAX_LENGTH = 200


def _b64(b):
    return base64.b64encode(b).decode()


def _derive(password, salt, n, r, p):
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=64 * 1024 * 1024)


def check_strength(password):
    """Raise ValueError with a plain message if the password is not acceptable."""
    if not isinstance(password, str) or len(password) < MIN_LENGTH:
        raise ValueError(f"the password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise ValueError("that password is too long")
    if password.strip() != password:
        raise ValueError("the password cannot start or end with a space")
    if password.isdigit() and len(set(password)) <= 2:
        raise ValueError("choose a password that is harder to guess")


def hash_password(password):
    salt = secrets.token_bytes(16)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(_derive(password, salt, N, R, P))}"


def verify_password(password, stored):
    """True if `password` matches `stored`. Never raises on a malformed or empty stored value."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
    except Exception:
        return False
    return hmac.compare_digest(actual, expected)


# A throwaway hash, so checking an email that does not exist takes as long as one that does.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
