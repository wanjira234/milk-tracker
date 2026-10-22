from src import sms_check


def test_usage_when_no_number_is_given():
    assert "usage" in sms_check.check(["x"])


def test_a_bad_number_is_reported_not_crashed(monkeypatch):
    monkeypatch.setenv("AT_USERNAME", "sandbox")
    monkeypatch.setenv("AT_API_KEY", "k")
    monkeypatch.setattr(sms_check, "make_client", lambda: object())
    assert "Not sent" in sms_check.check(["x", "0712"])


def test_accepted_message_says_where_to_look(monkeypatch, capsys):
    monkeypatch.setenv("AT_USERNAME", "sandbox")
    monkeypatch.setenv("AT_API_KEY", "k")

    class Fake:
        def send(self, message, recipients, sender_id=None):
            return {"SMSMessageData": {"Recipients": [{"statusCode": 101, "status": "Success", "messageId": "ATX1"}]}}

    monkeypatch.setattr(sms_check, "make_client", lambda: Fake())
    out = sms_check.check(["x", "+254712345678"])
    assert "simulator" in out and "AT_API_KEY set: True" in capsys.readouterr().out


def test_exit_code_is_zero_only_when_the_message_was_accepted(monkeypatch, capsys):
    monkeypatch.setattr(sms_check, "check", lambda argv: "Accepted by Africa's Talking.")
    assert sms_check.main(["x", "+254712345678"]) == 0
    monkeypatch.setattr(sms_check, "check", lambda argv: "Not sent: nope")
    assert sms_check.main(["x", "0712"]) == 1
    assert "Not sent" in capsys.readouterr().out
