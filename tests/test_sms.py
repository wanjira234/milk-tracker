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
