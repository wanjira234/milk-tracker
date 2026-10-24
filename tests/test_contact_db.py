"""The public Contact us form and the admin's inbox. Need TEST_DATABASE_URL (tests truncate tables)."""
import os

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import contact, db  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    db._query("TRUNCATE contact_messages RESTART IDENTITY")


def test_a_valid_message_is_saved_and_tidied():
    mid = contact.post_message("  Wanjiru   K ", " 0712 345 678 ", "  Do you cover Limuru?  \n  We have 12 cows. ")
    row = db.list_contact_messages()[0]
    assert row["id"] == mid and row["name"] == "Wanjiru K" and row["contact"] == "0712 345 678"
    assert row["message"] == "Do you cover Limuru?\nWe have 12 cows." and not row["handled"]


@pytest.mark.parametrize("args,word", [
    (("", "a@b.co", "A long enough message"), "name"),
    (("A", "", "A long enough message"), "email"),
    (("A", "a@b.co", "short"), "more"),
    (("A" * 81, "a@b.co", "A long enough message"), "name"),
    (("A", "x" * 121, "A long enough message"), "email"),
    (("A", "a@b.co", "m" * 1001), "long"),
])
def test_bad_messages_are_refused_with_a_reason(args, word):
    with pytest.raises(ValueError, match=word):
        contact.post_message(*args)
    assert db.list_contact_messages() == []


def test_the_inbox_has_a_ceiling_and_clearing_it_reopens_the_form(monkeypatch):
    monkeypatch.setattr(contact, "MAX_UNHANDLED", 2)
    ids = [contact.post_message("A", "a@b.co", f"Message number {i} here") for i in range(2)]
    with pytest.raises(ValueError, match="try again later"):
        contact.post_message("A", "a@b.co", "One message too many")
    db.set_message_handled(ids[0])
    contact.post_message("A", "a@b.co", "Room again after one is handled")
    db.delete_contact_message(ids[1])
    assert len(db.list_contact_messages()) == 2


def test_the_public_pages_render_and_the_form_saves_without_logging_in():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=30).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "How it works" in text and "Get started" in text  # the landing page
    assert "About us" in text and "Talk to us" in text
    next(t for t in at.text_input if t.key == "contact_name").set_value("Wanjiru")
    next(t for t in at.text_input if t.key == "contact_how").set_value("wanjiru@example.com")
    next(t for t in at.text_area if t.key == "contact_message").set_value("Please tell me how to join a route.")
    next(b for b in at.button if b.label == "Send message").click().run()
    assert not at.exception and any("Thank you" in s.value for s in at.success)
    assert db.list_contact_messages()[0]["name"] == "Wanjiru"
    next(t for t in at.text_input if t.key == "contact_name").set_value("Again")  # a second send within a minute waits
    next(t for t in at.text_input if t.key == "contact_how").set_value("a@b.co")
    next(t for t in at.text_area if t.key == "contact_message").set_value("A second message right away.")
    next(b for b in at.button if b.label == "Send message").click().run()
    assert any("wait a minute" in e.value for e in at.error) and len(db.list_contact_messages()) == 1
