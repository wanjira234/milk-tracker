"""SMS length counting, pre-send checks and the Africa's Talking sender. Fake client, no network."""
import pytest

from src import sms
from src.sms import SmsError, check_sendable, gsm_length, parse_response, send_sms, sms_segments

OK_REPLY = {"SMSMessageData": {"Message": "Sent to 1/1", "Recipients": [
    {"statusCode": 101, "number": "+254700000001", "status": "Success", "cost": "KES 0.8000", "messageId": "ATXid_1"}]}}


class FakeSms:
    def __init__(self, reply=OK_REPLY, error=None):
        self.reply, self.error, self.sent = reply, error, []

    def send(self, message, recipients, sender_id=None):
        self.sent.append((message, recipients, sender_id))
        if self.error:
            raise self.error
        return self.reply


def test_segment_counting():
    assert sms_segments("") == 0
    assert sms_segments("a" * 160) == 1 and sms_segments("a" * 161) == 2
    assert sms_segments("a" * 306) == 2 and sms_segments("a" * 307) == 3  # 153 per part once joined
    assert gsm_length("a{") == 3 and gsm_length("\U0001F42E") is None  # extended char costs 2; emoji is not GSM
    assert sms_segments("’" * 70) == 1 and sms_segments("’" * 71) == 2  # UCS-2: 70 per segment


def test_checks_before_sending():
    assert check_sendable("+254700000001", "hello") == 1
    for phone in ("0700000001", "+254600000001", "+25470000", None):
        with pytest.raises(SmsError):
            check_sendable(phone, "hello")
    with pytest.raises(SmsError):
        check_sendable("+254700000001", "  ")
    with pytest.raises(SmsError):
        check_sendable("+254700000001", "a" * 400)


def test_parse_response():
    r = parse_response(OK_REPLY)
    assert r["ok"] and r["message_id"] == "ATXid_1" and r["status"] == "Success"
    bad = {"SMSMessageData": {"Recipients": [{"statusCode": 403, "status": "InvalidPhoneNumber", "messageId": "None"}]}}
    assert not parse_response(bad)["ok"]
    assert not parse_response({"SMSMessageData": {"Message": "Insufficient balance", "Recipients": []}})["ok"]
    assert not parse_response("<html>gateway error</html>")["ok"] and not parse_response(None)["ok"]


def test_send_passes_text_number_and_sender():
    c = FakeSms()
    assert send_sms("+254700000001", "hello", client=c, sender_id="MILK")["ok"]
    assert c.sent == [("hello", ["+254700000001"], "MILK")]


def test_a_refused_message_is_never_sent():
    c = FakeSms()
    with pytest.raises(SmsError):
        send_sms("0700", "hello", client=c)
    assert c.sent == []


def test_a_provider_error_comes_back_as_a_failed_result_not_an_exception():
    r = send_sms("+254700000001", "hello", client=FakeSms(error=ConnectionError("down")))
    assert r["ok"] is False and r["status"] == "send error" and "ConnectionError" in r["detail"]


def test_missing_credentials_are_reported(monkeypatch):
    monkeypatch.delenv("AT_USERNAME", raising=False)
    monkeypatch.delenv("AT_API_KEY", raising=False)
    with pytest.raises(SmsError):
        sms.make_client()


# --- the HTTP client (TLS 1.2 cap; no network) --------------------------------------

import ssl  # noqa: E402

from src.sms import AfricasTalkingClient  # noqa: E402


class FakeSession:
    def __init__(self, status=200, body=None, text=""):
        self.status, self.body, self.text, self.calls = status, body, text, []

    def post(self, url, headers, data, timeout):
        self.calls.append((url, headers, data, timeout))
        outer = self

        class R:
            status_code = outer.status
            text = outer.text

            def json(self_inner):
                if outer.body is None:
                    raise ValueError("not json")
                return outer.body

        return R()


def test_the_client_sends_the_same_request_as_the_sdk_to_the_right_host():
    s = FakeSession(body=OK_REPLY)
    c = AfricasTalkingClient("sandbox", "KEY", session=s)
    assert c.send("hello", ["+254700000001", "+254700000002"], "MILK") == OK_REPLY
    url, headers, data, timeout = s.calls[0]
    assert url == "https://api.sandbox.africastalking.com/version1/messaging"
    assert headers["apiKey"] == "KEY" and headers["Accept"] == "application/json"
    assert data == {"username": "sandbox", "to": "+254700000001,+254700000002", "message": "hello", "bulkSMSMode": 1, "from": "MILK"}
    assert AfricasTalkingClient("someone", "K", session=s).url == "https://api.africastalking.com/version1/messaging"
    s2 = FakeSession(body=OK_REPLY)
    AfricasTalkingClient("sandbox", "K", session=s2).send("hi", ["+254700000001"])
    assert "from" not in s2.calls[0][2]  # no sender id: not sent


def test_provider_errors_and_unreadable_replies_raise_and_become_a_failed_result():
    for session in (FakeSession(status=401, text="The supplied authentication is invalid"), FakeSession(text="<html>oops")):
        c = AfricasTalkingClient("sandbox", "K", session=session)
        with pytest.raises(RuntimeError):
            c.send("hello", ["+254700000001"])
        r = send_sms("+254700000001", "hello", client=c)
        assert r["ok"] is False and r["status"] == "send error"
    assert "401" in send_sms("+254700000001", "hello", client=AfricasTalkingClient("sandbox", "K", session=FakeSession(status=401, text="bad key")))["detail"]


def test_the_real_session_verifies_certifi_without_the_ca_certs_option():
    adapter = AfricasTalkingClient._verified_session().get_adapter("https://api.sandbox.africastalking.com")
    context = adapter.poolmanager.connection_pool_kw["ssl_context"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname

    class Conn:
        pass

    conn = Conn()
    adapter.cert_verify(conn, "https://api.sandbox.africastalking.com", True, None)
    assert not hasattr(conn, "ca_certs")  # requests' default would set this and break the TLS handshake


def test_make_client_builds_the_http_client_from_the_environment(monkeypatch):
    monkeypatch.setenv("AT_USERNAME", "sandbox")
    monkeypatch.setenv("AT_API_KEY", "k")
    c = sms.make_client()
    assert isinstance(c, AfricasTalkingClient) and "sandbox" in c.url
