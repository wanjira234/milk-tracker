"""Time-based one-time codes (RFC 6238), the kind an authenticator app shows. Standard library only."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6


def new_secret():
    """A random 160-bit key, base32 so it can be typed into an authenticator app."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret):
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def step_at(now=None):
    return int((time.time() if now is None else now) // STEP)


def code_for(secret, step):
    mac = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    n = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return f"{n:0{DIGITS}d}"


def verify(secret, entered, now=None, after_step=None, window=1):
    """The step number the code matches (so it can be remembered and never accepted twice), else None.
    One step either side allows for a slightly wrong phone clock. A step at or before `after_step` is refused."""
    entered = (entered or "").strip().replace(" ", "")
    if len(entered) != DIGITS or not entered.isdigit():
        return None
    now_step = step_at(now)
    found = None
    for s in range(now_step - window, now_step + window + 1):  # check all, so timing does not reveal which
        if hmac.compare_digest(code_for(secret, s), entered) and found is None:
            found = s
    if found is None or (after_step is not None and found <= after_step):
        return None
    return found


def uri(secret, account, issuer="Maziwa Plus"):
    """The otpauth:// link an authenticator app reads from a QR code."""
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP}"
