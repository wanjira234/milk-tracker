"""The public Contact us form. Anyone can reach it, so every input is capped and the inbox has a ceiling."""
from src import db

MAX_NAME, MAX_CONTACT, MAX_MESSAGE, MIN_MESSAGE = 80, 120, 1000, 10
MAX_UNHANDLED = 200  # a flood fills the inbox to here and then the form says to try later


def clean(text):
    return " ".join(str(text or "").split())


def post_message(name, contact, message):
    """Save a message from a visitor. Raises ValueError with a reason a visitor can act on."""
    name, contact = clean(name), clean(contact)
    message = "\n".join(line.strip() for line in str(message or "").strip().splitlines())
    if not name:
        raise ValueError("please tell us your name")
    if len(name) > MAX_NAME:
        raise ValueError(f"the name is too long ({MAX_NAME} characters at most)")
    if not contact:
        raise ValueError("please give an email or a phone number so we can reply")
    if len(contact) > MAX_CONTACT:
        raise ValueError(f"the email or phone is too long ({MAX_CONTACT} characters at most)")
    if len(message) < MIN_MESSAGE:
        raise ValueError("please write a little more, so we can help")
    if len(message) > MAX_MESSAGE:
        raise ValueError(f"the message is too long ({MAX_MESSAGE} characters at most)")
    if db.count_unhandled_messages() >= MAX_UNHANDLED:
        raise ValueError("we cannot take new messages right now; please try again later")
    return db.add_contact_message(name, contact, message)
