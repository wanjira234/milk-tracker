"""Accounts, login, routes and who-sees-what against a real Postgres. Need TEST_DATABASE_URL."""
import os
from datetime import datetime, timedelta, timezone

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import accounts, db, logincode  # noqa: E402

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
OWNER = "+254703687201"


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes RESTART IDENTITY CASCADE")


class Outbox:
    """Stands in for the SMS sender and remembers what was 'sent'."""

    def __init__(self, ok=True):
        self.ok, self.sent = ok, []

    def __call__(self, phone, text):
        self.sent.append((phone, text))
        return self.ok

    def last_code(self):
        return self.sent[-1][1].split("login code is ")[1][:6]


@pytest.fixture
def farm():
    return db.add_farmer("Mama Wanjiru", "+254700000001", "Maziwa Bora")


# --- SMS code login ------------------------------------------------------------------------


def test_a_registered_farmer_logs_in_with_a_code_and_gets_a_farmer_account(farm):
    out = Outbox()
    r = accounts.request_code("0700 000 001", out, NOW, owner_phone=None)
    assert r["status"] == "sent" and out.sent[0][0] == "+254700000001"
    user = accounts.verify_code("0700000001", out.last_code(), NOW)
    assert user["role"] == "farmer" and user["farmer_id"] == farm


def test_an_unregistered_number_gets_no_sms():
    out = Outbox()
    assert accounts.request_code("0711111111", out, NOW, owner_phone=None)["status"] == "unknown"
    assert out.sent == []


def test_the_owner_phone_becomes_the_admin_on_first_login():
    out = Outbox()
    assert accounts.request_code(OWNER, out, NOW, owner_phone=OWNER)["status"] == "sent"
    assert accounts.verify_code(OWNER, out.last_code(), NOW)["role"] == "admin"


def test_a_code_works_once_only(farm):
    out = Outbox()
    accounts.request_code("0700000001", out, NOW, owner_phone=None)
    code = out.last_code()
    assert accounts.verify_code("0700000001", code, NOW)
    assert accounts.verify_code("0700000001", code, NOW) is None


def test_a_wrong_code_is_refused_and_five_wrong_tries_burn_the_code(farm):
    out = Outbox()
    accounts.request_code("0700000001", out, NOW, owner_phone=None)
    code = out.last_code()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(logincode.MAX_ATTEMPTS):
        assert accounts.verify_code("0700000001", wrong, NOW) is None
    assert accounts.verify_code("0700000001", code, NOW) is None  # even the right one is dead now


def test_a_code_expires(farm):
    out = Outbox()
    accounts.request_code("0700000001", out, NOW, owner_phone=None)
    assert accounts.verify_code("0700000001", out.last_code(), NOW + logincode.CODE_TTL + timedelta(seconds=1)) is None


def test_asking_again_gets_a_new_code_and_only_the_newest_works(farm):
    out = Outbox()
    accounts.request_code("0700000001", out, NOW, owner_phone=None)
    first = out.last_code()
    later = NOW + timedelta(minutes=2)
    accounts.request_code("0700000001", out, later, owner_phone=None)
    second = out.last_code()
    if first != second:
        assert accounts.verify_code("0700000001", first, later) is None
    assert accounts.verify_code("0700000001", second, later)


def test_code_requests_are_limited(farm):
    out = Outbox()
    accounts.request_code("0700000001", out, NOW, owner_phone=None)
    assert accounts.request_code("0700000001", out, NOW + timedelta(seconds=10), owner_phone=None)["status"] == "throttled"
    for i in range(1, logincode.MAX_CODES_PER_HOUR):
        assert accounts.request_code("0700000001", out, NOW + timedelta(minutes=i * 2), owner_phone=None)["status"] == "sent"
    assert accounts.request_code("0700000001", out, NOW + timedelta(minutes=12), owner_phone=None)["status"] == "throttled"
    assert len(out.sent) == logincode.MAX_CODES_PER_HOUR


def test_a_failed_sms_is_reported_and_a_bad_number_says_what_is_wrong(farm):
    assert accounts.request_code("0700000001", Outbox(ok=False), NOW, owner_phone=None)["status"] == "failed"
    with pytest.raises(ValueError, match="Kenyan"):
        accounts.request_code("12345", Outbox(), NOW)


def test_the_code_is_never_stored_in_clear(farm):
    out = Outbox()
    accounts.request_code("0700000001", out, NOW, owner_phone=None)
    row = db._query("SELECT * FROM login_codes", one=True)
    assert out.last_code() not in str(dict(row)) and row["code_hash"] != out.last_code()


def test_a_deactivated_user_cannot_log_in(farm):
    out = Outbox()
    accounts.request_code("0700000001", out, NOW, owner_phone=None)
    db.update_user(db.user_by_phone("+254700000001")["id"], active=False)
    assert accounts.verify_code("0700000001", out.last_code(), NOW) is None
    assert accounts.request_code("0700000001", out, NOW + timedelta(hours=2), owner_phone=None)["status"] == "unknown"


# --- email + password ------------------------------------------------------------------------


def test_admin_creates_a_farmer_login_with_a_temporary_password_that_must_be_changed(farm):
    accounts.create_account("farmer", "Mama Wanjiru", email="Mama@Example.com", temp_password="temp-pass-1", farmer_id=farm)
    user = accounts.login_password("mama@example.com", "temp-pass-1", NOW)
    assert user["role"] == "farmer" and user["must_change_password"] is True and "password_hash" not in user
    accounts.set_password(user["id"], "my-own-password")
    again = accounts.login_password("MAMA@example.com", "my-own-password", NOW)
    assert again["must_change_password"] is False
    assert accounts.login_password("mama@example.com", "temp-pass-1", NOW) is None


def test_wrong_passwords_and_unknown_emails_are_refused_the_same_way(farm):
    accounts.create_account("farmer", "Mama", email="mama@example.com", temp_password="temp-pass-1", farmer_id=farm)
    assert accounts.login_password("mama@example.com", "nope", NOW) is None
    assert accounts.login_password("nobody@example.com", "temp-pass-1", NOW) is None
    assert accounts.login_password("not an email", "x", NOW) is None
    assert accounts.login_password("mama@example.com", "", NOW) is None


def test_five_wrong_passwords_lock_the_account_even_for_the_right_one_and_the_lock_ends(farm):
    accounts.create_account("farmer", "Mama", email="mama@example.com", temp_password="temp-pass-1", farmer_id=farm)
    for _ in range(accounts.MAX_FAILED_LOGINS):
        accounts.login_password("mama@example.com", "wrong-pass", NOW)
    assert accounts.login_password("mama@example.com", "temp-pass-1", NOW) is None
    assert "Too many" in accounts.locked_message("mama@example.com", NOW)
    assert accounts.login_password("mama@example.com", "temp-pass-1", NOW + accounts.LOCKOUT + timedelta(seconds=1))
    assert accounts.locked_message("mama@example.com", NOW + accounts.LOCKOUT + timedelta(minutes=1)) is None


def test_a_success_resets_the_failure_count(farm):
    accounts.create_account("farmer", "Mama", email="mama@example.com", temp_password="temp-pass-1", farmer_id=farm)
    for _ in range(accounts.MAX_FAILED_LOGINS - 1):
        accounts.login_password("mama@example.com", "wrong-pass", NOW)
    assert accounts.login_password("mama@example.com", "temp-pass-1", NOW)
    for _ in range(accounts.MAX_FAILED_LOGINS - 1):
        accounts.login_password("mama@example.com", "wrong-pass", NOW)
    assert accounts.login_password("mama@example.com", "temp-pass-1", NOW)  # still not locked


def test_passwords_are_stored_hashed(farm):
    accounts.create_account("farmer", "Mama", email="mama@example.com", temp_password="temp-pass-1", farmer_id=farm)
    assert "temp-pass-1" not in str(db._query("SELECT * FROM users", one=True))


def test_a_farmer_can_add_a_password_after_an_sms_login(farm):
    out = Outbox()
    accounts.request_code("0700000001", out, NOW, owner_phone=None)
    user = accounts.verify_code("0700000001", out.last_code(), NOW)
    accounts.set_password(user["id"], "my-own-password", email="mama@example.com")
    assert accounts.login_password("mama@example.com", "my-own-password", NOW)["id"] == user["id"]


# --- creating accounts and routes -------------------------------------------------------------


def test_account_validation(farm):
    for kwargs, why in (
        (dict(role="boss", name="X", email="a@b.co"), "role"),
        (dict(role="vet", name=" ", email="a@b.co"), "name"),
        (dict(role="vet", name="X"), "phone number or an email"),
        (dict(role="vet", name="X", phone="123"), "Kenyan"),
        (dict(role="vet", name="X", email="nope"), "valid email"),
        (dict(role="vet", name="X", phone="0712345678", temp_password="longenough1"), "needs an email"),
        (dict(role="vet", name="X", email="a@b.co", temp_password="short"), "at least"),
        (dict(role="farmer", name="X", email="a@b.co"), "farm"),
    ):
        with pytest.raises(ValueError, match=why):
            accounts.create_account(**kwargs)


def test_a_phone_email_or_farm_can_have_only_one_login(farm):
    accounts.create_account("vet", "Dr Kibet", phone="0712345678", email="kibet@example.com")
    for kwargs in (dict(phone="0712345678"), dict(email="kibet@example.com")):
        with pytest.raises(ValueError, match="already has a login"):
            accounts.create_account("vet", "Other", **kwargs)
    accounts.create_account("farmer", "A", phone="0700000001", farmer_id=farm)
    with pytest.raises(ValueError, match="already has a login"):
        accounts.create_account("farmer", "B", email="b@example.com", farmer_id=farm)


def test_routes_vets_and_farms():
    vet = accounts.create_account("vet", "Dr Kibet", phone="0712345678")
    farmer = accounts.create_account("farmer", "F", phone="0700000009", farmer_id=db.add_farmer("F", "+254700000009"))
    other = db.add_farmer("Other", "+254700000002")
    r4a = accounts.record_route(" 4a ", "Tigoni")
    assert db.list_routes()[0]["code"] == "4A"
    assert accounts.record_route("4A", "Tigoni north") == r4a  # same code: updated, not duplicated
    with pytest.raises(ValueError, match="route code"):
        accounts.record_route("a route!")
    with pytest.raises(ValueError, match="vet"):
        accounts.allocate_vet(r4a, farmer)  # a farmer is not a vet
    accounts.allocate_vet(r4a, vet)
    assert db.list_routes()[0]["vet_name"] == "Dr Kibet"
    accounts.assign_route(db.get_user(farmer)["farmer_id"], r4a)
    assert db.list_routes()[0]["farms"] == 1
    with pytest.raises(ValueError, match="route"):
        accounts.assign_route(other, 9999)
    accounts.allocate_vet(r4a, None)
    assert db.list_routes()[0]["vet_name"] is None


def test_who_can_see_which_farms():
    f1 = db.add_farmer("On 4A", "+254700000001")
    f2 = db.add_farmer("On 5B", "+254700000002")
    f3 = db.add_farmer("No route", "+254700000003")
    vet = accounts.create_account("vet", "Dr Kibet", phone="0712345678")
    admin = accounts.create_account("admin", "Boss", phone="0722222222")
    farmer = accounts.create_account("farmer", "F1", phone="0700000001", farmer_id=f1)
    r4a, r5b = accounts.record_route("4A"), accounts.record_route("5B")
    accounts.allocate_vet(r4a, vet)
    accounts.assign_route(f1, r4a)
    accounts.assign_route(f2, r5b)
    ids = lambda uid: sorted(f["id"] for f in accounts.visible_farmers(accounts.session_user(db.get_user(uid))))  # noqa: E731
    assert ids(admin) == [f1, f2, f3]
    assert ids(vet) == [f1]  # only the farms on the vet's own route
    assert ids(farmer) == [f1]
    db.update_user(vet, active=True)
    accounts.allocate_vet(r5b, vet)
    assert ids(vet) == [f1, f2]


def test_deleting_a_farm_removes_its_login(farm):
    accounts.create_account("farmer", "Mama", phone="0700000001", farmer_id=farm)
    db._query("DELETE FROM farmers WHERE id = %s", (farm,))
    assert db.list_users() == []
