"""Sending SMS through Africa's Talking, and counting what a message will cost.

Everything here is cheap to test: the Africa's Talking client is injected, and the SDK is
only imported when a real client is needed. A message is checked BEFORE it leaves (length,
number, empty text), and every attempt is written to `sms_log`, successful or not.

Use username "sandbox" while testing. Sandbox messages show up in the Africa's Talking
simulator and never reach a real phone.
"""
import math
import os
import re

MAX_SEGMENTS = 2  # CONTEXT.md: keep suggestion text within one or two SMS segments

# GSM 03.38 basic set: one septet each. Anything outside it (curly quotes, many accented
# letters, emoji) pushes the whole message to UCS-2, where a segment holds only 70 characters.
_GSM_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM_EXTENDED = "^{}\\[~]|€"  # two septets each (escape + character)

_PHONE = re.compile(r"^\+254[17]\d{8}$")
SUCCESS_CODES = {100, 101, 102}  # Africa's Talking: Processed, Sent, Queued


class SmsError(Exception):
    """The message was refused before sending, or could not be sent."""


def gsm_length(text):
    """Septets needed to send `text` in the GSM alphabet, or None if it needs UCS-2."""
    total = 0
    for ch in text:
        if ch in _GSM_BASIC:
            total += 1
        elif ch in _GSM_EXTENDED:
            total += 2
        else:
            return None
    return total


def sms_segments(text):
    """How many billable segments `text` takes. 0 for empty text."""
    if not text:
        return 0
    septets = gsm_length(text)
    if septets is not None:
        return 1 if septets <= 160 else math.ceil(septets / 153)
    return 1 if len(text) <= 70 else math.ceil(len(text) / 67)


def check_sendable(phone, text):
    """Raise SmsError if the number or message should not be sent. Returns the segment count."""
    if not _PHONE.match(phone or ""):
        raise SmsError(f"not a Kenyan mobile number in +254 format: {phone!r}")
    if not text or not text.strip():
        raise SmsError("empty message")
    segments = sms_segments(text)
    if segments > MAX_SEGMENTS:
        raise SmsError(f"message takes {segments} segments; the limit is {MAX_SEGMENTS}")
    return segments


class AfricasTalkingClient:
    """Sends through Africa's Talking's HTTP API (the same request their SDK makes).

    Why not the SDK: `requests` hands urllib3 certifi's CA bundle through the `ca_certs`
    connection option, and on this network that exact combination fails the TLS handshake
    with api.sandbox.africastalking.com (SSL "WRONG_VERSION_NUMBER"), even though a browser
    and a plain socket connect fine. Here the connection verifies against certifi using an
    SSLContext we build ourselves and never sets `ca_certs`, which avoids the bad handshake.
    """

    TIMEOUT = (3.05, 9.05)  # connect, read: seconds

    def __init__(self, username, api_key, session=None):
        self.username = username
        self.url = (
            "https://api.sandbox.africastalking.com" if username == "sandbox" else "https://api.africastalking.com"
        ) + "/version1/messaging"
        self.headers = {"Accept": "application/json", "apiKey": api_key}
        self.session = session or self._verified_session()

    @staticmethod
    def _verified_session():
        import ssl

        import certifi
        import requests
        from requests.adapters import HTTPAdapter

        class CertifiAdapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                kwargs["ssl_context"] = ssl.create_default_context(cafile=certifi.where())
                super().init_poolmanager(*args, **kwargs)

            def cert_verify(self, conn, url, verify, cert):
                # Deliberately empty: letting requests set `ca_certs` on the connection is
                # what breaks the handshake. The SSLContext above already trusts certifi.
                pass

        session = requests.Session()
        session.mount("https://", CertifiAdapter())
        return session

    def send(self, message, recipients, sender_id=None):
        """Same call as the SDK's SMS.send: returns the provider's JSON reply, or raises."""
        data = {"username": self.username, "to": ",".join(recipients), "message": message, "bulkSMSMode": 1}
        if sender_id:
            data["from"] = sender_id
        res = self.session.post(self.url, headers=self.headers, data=data, timeout=self.TIMEOUT)
        if not 200 <= res.status_code < 300:
            raise RuntimeError(f"Africa's Talking replied {res.status_code}: {res.text[:150]}")
        try:
            return res.json()
        except ValueError:
            raise RuntimeError(f"Africa's Talking sent an unreadable reply: {res.text[:150]}") from None


def make_client():
    """The real Africa's Talking sender, from AT_USERNAME and AT_API_KEY."""
    username, api_key = os.environ.get("AT_USERNAME"), os.environ.get("AT_API_KEY")
    if not username or not api_key:
        raise SmsError("AT_USERNAME and AT_API_KEY must be set")
    return AfricasTalkingClient(username, api_key)


def parse_response(response):
    """Africa's Talking reply -> {ok, status, message_id, cost, detail}."""
    try:
        recipients = response["SMSMessageData"]["Recipients"]
    except (KeyError, TypeError):
        return {"ok": False, "status": "unreadable reply", "message_id": None, "cost": None, "detail": str(response)[:200]}
    if not recipients:
        message = (response.get("SMSMessageData") or {}).get("Message", "no recipients")
        return {"ok": False, "status": "not accepted", "message_id": None, "cost": None, "detail": message}
    r = recipients[0]
    return {
        "ok": r.get("statusCode") in SUCCESS_CODES,
        "status": r.get("status", "unknown"),
        "message_id": r.get("messageId"),
        "cost": r.get("cost"),
        "detail": str(r)[:200],
    }


def send_sms(phone, text, *, client=None, sender_id=None):
    """Check a message, send it, and return the parsed result. Never logs; see send_to_farmer.

    Raises SmsError if the message is refused before sending. A send that fails on the
    network or at the provider comes back as ok=False, not as an exception, so one bad
    number can't stop a whole batch.
    """
    check_sendable(phone, text)
    client = client or make_client()
    sender_id = sender_id if sender_id is not None else (os.environ.get("AT_SENDER_ID") or None)
    try:
        response = client.send(text, [phone], sender_id)
    except Exception as e:  # network error, bad credentials, provider error
        return {"ok": False, "status": "send error", "message_id": None, "cost": None, "detail": f"{type(e).__name__}: {e}"[:200]}
    return parse_response(response)


def send_to_farmer(farmer_id, phone, text, *, client=None, sender_id=None, kind="other"):
    """Send and record the attempt in sms_log ('sent' or 'failed'). Returns the parsed result.

    A message refused before sending (too long, bad number) is logged as 'failed' too, so
    nothing a farmer should have received goes missing without a trace.
    """
    from src import db  # imported here so the pure helpers above work without a database

    try:
        result = send_sms(phone, text, client=client, sender_id=sender_id)
    except SmsError as e:
        result = {"ok": False, "status": "refused", "message_id": None, "cost": None, "detail": str(e)}
    db.log_sms(farmer_id, text or "", status="sent" if result["ok"] else "failed", provider_ref=result["message_id"], kind=kind)
    return result
