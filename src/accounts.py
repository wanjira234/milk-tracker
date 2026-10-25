"""Who is logging in, and what they may see. Logic only: no Streamlit.

Login is one of two ways, the person's choice:
  - a one-time code sent by SMS to their phone, or
  - email + password.
Roles: farmer (one farm), vet (the farms on the routes they are allocated), admin (everything).

Hard rules in here: wrong-password lockout is stored in the database (so reloading the page
does not reset it), a code is single-use and expires, and a failed login never says whether the
email exists.
"""
import os
import re
from datetime import datetime, timedelta, timezone

import psycopg2

from src import db, logincode, totp
from src.ingestion.manual_entry import normalize_phone
from src.passwords import DUMMY_HASH, check_strength, hash_password, verify_password

ROLES = ("admin", "vet", "farmer")
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now():
    return datetime.now(timezone.utc)


def normalize_email(raw):
    email = str(raw or "").strip().lower()
    if not _EMAIL.match(email) or len(email) > 120:
        raise ValueError("enter a valid email address")
    return email


def admin_phone():
    """The owner's phone, from ADMIN_PHONE: the first login by this number becomes the admin account."""
    raw = os.environ.get("ADMIN_PHONE", "").strip()
    try:
        return normalize_phone(raw) if raw else None
    except ValueError:
        return None


def session_user(row):
    """What the app remembers about a logged-in person (never the password hash)."""
    return {
        "id": row["id"], "role": row["role"], "name": row["name"],
        "farmer_id": row["farmer_id"], "must_change_password": bool(row["must_change_password"]),
        "route_admin": bool(row.get("route_admin")),
    }


def admin_scope(user):
    """None for anyone who may act on every route (the owner and head admins, and non-admins, who are
    limited elsewhere); for a route admin, the set of route ids they look after, read fresh each time."""
    if user["role"] == "admin" and user.get("route_admin") and user.get("id") is not None:
        return db.admin_route_ids(user["id"])
    return None


def is_head_admin(user):
    return bool(user) and user["role"] == "admin" and not user.get("route_admin")


# --- SMS code login ---------------------------------------------------------------


def user_for_phone(phone, owner_phone=None):
    """The account for a phone number. First use creates it when the number belongs to a registered
    farmer (farmer account) or is the owner's ADMIN_PHONE (admin account). Otherwise None."""
    user = db.user_by_phone(phone)
    if user:
        return user if user["active"] else None
    farmer = db.farmer_by_phone(phone)
    if farmer and farmer["active"]:
        uid = db.create_user("farmer", farmer["name"], phone=phone, farmer_id=farmer["id"])
        return db.get_user(uid)
    if owner_phone and phone == owner_phone:
        return db.get_user(db.create_user("admin", "Admin", phone=phone))
    return None


def request_code(raw_phone, send, now=None, owner_phone=None):
    """Make and send a login code. `send(phone, text)` returns True when the SMS was accepted.

    Returns {"status": "sent" | "unknown" | "throttled" | "failed", "message": plain words}.
    """
    now = now or _now()
    phone = normalize_phone(raw_phone)  # ValueError says what is wrong with the number
    user = user_for_phone(phone, owner_phone if owner_phone is not None else admin_phone())
    if user is None:
        return {"status": "unknown", "message": "This number is not registered. Ask your admin to add you."}
    recent = db.recent_login_code_times(user["id"], now - timedelta(hours=1))
    ok, why = logincode.may_send(recent, now)
    if not ok:
        return {"status": "throttled", "message": why[:1].upper() + why[1:] + "."}
    code, salt = logincode.new_code(), logincode.new_salt()
    db.add_login_code(user["id"], salt, logincode.hash_code(code, salt), now + logincode.CODE_TTL, now)
    if not send(phone, logincode.message(code)):
        return {"status": "failed", "message": "The SMS could not be sent. Try again, or log in with your email and password."}
    return {"status": "sent", "message": f"A 6-digit code was sent to {phone}. It works for 10 minutes."}


def verify_code(raw_phone, entered, now=None):
    """The user row when `entered` is the latest valid code for this phone, else None. Single use."""
    now = now or _now()
    try:
        phone = normalize_phone(raw_phone)
    except ValueError:
        return None
    user = db.user_by_phone(phone)
    if not user or not user["active"]:
        return None
    row = db.latest_login_code(user["id"])
    if not row or not logincode.usable(row, now):
        return None
    if not logincode.matches(entered, row["salt"], row["code_hash"]):
        db.bump_login_attempts(row["id"])
        return None
    db.use_login_code(row["id"])
    return user


# --- email + password login --------------------------------------------------------


class PendingApproval(Exception):
    """The email and password are right, but an admin has not approved this signup yet."""


def login_password(raw_email, password, now=None):
    """The user row for a correct email + password, else None. Locks the account after repeated failures."""
    now = now or _now()
    try:
        email = normalize_email(raw_email)
    except ValueError:
        verify_password(password or "", DUMMY_HASH)
        return None
    user = db.user_by_email(email)
    if user and user["pending"] and user.get("password_hash") and verify_password(password or "", user["password_hash"]):
        raise PendingApproval  # only said to someone who proved they own this signup
    if not user or not user["active"] or not user.get("password_hash"):
        verify_password(password or "", DUMMY_HASH)  # same time as a real check
        return None
    if user["locked_until"] and now < user["locked_until"]:
        return None
    if verify_password(password or "", user["password_hash"]):
        if user["failed_logins"] or user["locked_until"]:
            db.update_user(user["id"], failed_logins=0, locked_until=None)
        return {k: v for k, v in user.items() if k != "password_hash"}
    failed = user["failed_logins"] + 1
    db.update_user(user["id"], failed_logins=failed, locked_until=now + LOCKOUT if failed >= MAX_FAILED_LOGINS else None)
    return None


def locked_message(raw_email, now=None):
    """'Too many tries' text when the account is locked, so the person is told why; else None."""
    now = now or _now()
    try:
        user = db.user_by_email(normalize_email(raw_email))
    except ValueError:
        return None
    if user and user["locked_until"] and now < user["locked_until"]:
        minutes = int((user["locked_until"] - now).total_seconds() // 60) + 1
        return f"Too many wrong tries. Try again in about {minutes} minute(s), or log in with an SMS code."
    return None


def locked_message_for_id(user_id, now=None):
    """Same as locked_message, for the second-factor step where we already hold the user id."""
    now = now or _now()
    user = db.get_user(user_id)
    if user and user["locked_until"] and now < user["locked_until"]:
        minutes = int((user["locked_until"] - now).total_seconds() // 60) + 1
        return f"Too many wrong tries. Try again in about {minutes} minute(s), or log in with an SMS code."
    return None


def owner_locked_message(now=None):
    """The owner password is one shared secret, so wrong guesses count against everyone together:
    5 wrong tries lock the owner login for 15 minutes, however many browsers are used."""
    now = now or _now()
    state = db.owner_lockout()
    if state["locked_until"] and now < state["locked_until"]:
        minutes = int((state["locked_until"] - now).total_seconds() // 60) + 1
        return f"Too many wrong tries. The owner login is locked for about {minutes} minute(s). Use an admin email or SMS login."
    return None


def owner_login_failed(now=None):
    now = now or _now()
    state = db.owner_lockout()
    failed = state["failures"] + 1
    db.set_owner_lockout(failed, now + LOCKOUT if failed >= MAX_FAILED_LOGINS else None)


def owner_login_ok():
    state = db.owner_lockout()
    if state["failures"] or state["locked_until"]:
        db.set_owner_lockout(0, None)


def set_password(user_id, new_password, email=None):
    """Set (or change) a password, and optionally the email to use with it."""
    check_strength(new_password)
    fields = {"password_hash": hash_password(new_password), "must_change_password": False, "failed_logins": 0, "locked_until": None}
    if email:
        fields["email"] = normalize_email(email)
    try:
        db.update_user(user_id, **fields)
    except psycopg2.errors.UniqueViolation:
        raise ValueError("that email is already used by another account") from None


# --- two-factor login (optional, authenticator app) ---------------------------------------------


def totp_required(user_id):
    """True when this person has switched on two-factor login."""
    t = db.get_totp(user_id)
    return bool(t and t["enabled"] and t["secret"])


def begin_totp_setup(user_id):
    """Make a fresh key (not yet active) and return it. Active only once a code from the app is confirmed."""
    secret = totp.new_secret()
    db.set_totp(user_id, totp_secret=secret, totp_enabled=False, totp_last_step=None, totp_failed=0)
    return secret


def confirm_totp_setup(user_id, entered, now=None):
    """Switch two-factor on if `entered` is a valid code from the key made by begin_totp_setup."""
    t = db.get_totp(user_id)
    if not t or not t["secret"] or t["enabled"]:
        return False
    step = totp.verify(t["secret"], entered, now=(now or _now()).timestamp())
    if step is None:
        return False
    db.set_totp(user_id, totp_enabled=True, totp_last_step=step, totp_failed=0)
    return True


def verify_totp_login(user_id, entered, now=None):
    """Check the second factor. A code works once; five wrong codes lock the account for 15 minutes,
    the same lock the password step respects, so starting over with the password does not reset the count."""
    now = now or _now()
    t = db.get_totp(user_id)
    user = db.get_user(user_id)
    if not t or not t["enabled"] or not user or not user["active"]:
        return False
    if user["locked_until"] and now < user["locked_until"]:
        return False
    step = totp.verify(t["secret"], entered, now=now.timestamp(), after_step=t["last_step"])
    if step is None:
        failed = t["failed"] + 1
        if failed >= MAX_FAILED_LOGINS:
            db.set_totp(user_id, totp_failed=0)
            db.update_user(user_id, locked_until=now + LOCKOUT)
        else:
            db.set_totp(user_id, totp_failed=failed)
        return False
    db.set_totp(user_id, totp_failed=0, totp_last_step=step)
    return True


def disable_totp(user_id, entered, now=None):
    """Turn two-factor off; asks for a current code so a borrowed, logged-in phone cannot do it."""
    if not verify_totp_login(user_id, entered, now=now):
        return False
    db.set_totp(user_id, totp_secret=None, totp_enabled=False, totp_last_step=None, totp_failed=0)
    return True


def admin_reset_totp(actor, user_id):
    """For someone who lost their phone: an admin switches their two-factor off so they can set it up again."""
    _need_admin(actor)
    db.set_totp(user_id, totp_secret=None, totp_enabled=False, totp_last_step=None, totp_failed=0)


# --- creating accounts (admin) ----------------------------------------------------


def create_account(role, name, phone=None, email=None, temp_password=None, farmer_id=None, route_ids=None):
    """Create a login. With a temporary password, the person must change it at first login."""
    if role not in ROLES:
        raise ValueError("choose a role")
    name = " ".join(str(name or "").split())
    if not name:
        raise ValueError("enter a name")
    phone = normalize_phone(phone) if phone else None
    email = normalize_email(email) if email else None
    if not phone and not email:
        raise ValueError("enter a phone number or an email")
    if temp_password:
        if not email:
            raise ValueError("a password login needs an email")
        check_strength(temp_password)
    if role == "farmer":
        if farmer_id is None or db.get_farmer(farmer_id) is None:
            raise ValueError("choose the farm this farmer belongs to")
    else:
        farmer_id = None
    try:
        uid = db.create_user(
            role, name, phone, email,
            hash_password(temp_password) if temp_password else None, farmer_id, must_change_password=bool(temp_password),
            route_admin=route_ids is not None and role == "admin",
        )
        if route_ids is not None and role == "admin":
            db.set_admin_routes(uid, route_ids)
    except psycopg2.errors.UniqueViolation:
        raise ValueError("that phone number, email or farm already has a login") from None
    return uid


# --- routes -------------------------------------------------------------------------


def record_route(code, name=None):
    code = str(code or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9-]{1,10}", code):
        raise ValueError("a route code is letters and numbers, like 4A")
    return db.add_route(code, " ".join(str(name or "").split()) or None)


def allocate_vet(route_id, vet_user_id):
    """Allocate a vet to a route (or None to clear it)."""
    if vet_user_id is not None:
        vet = db.get_user(vet_user_id)
        if not vet or vet["role"] != "vet" or not vet["active"]:
            raise ValueError("choose a vet")
    db.set_route_vet(route_id, vet_user_id)


def assign_route(farmer_id, route_id):
    if route_id is not None and route_id not in {r["id"] for r in db.list_routes()}:
        raise ValueError("choose a route from the list")
    db.set_farmer_route(farmer_id, route_id)


# --- what each role may see ---------------------------------------------------------


def visible_farmers(user):
    """The farms this person may open: a farmer sees their own, a vet the farms on their routes, an admin all."""
    if user["role"] == "admin":
        scope = admin_scope(user)
        return db.list_farmers() if scope is None else db.farmers_on_routes(scope)
    if user["role"] == "vet":
        return db.farmers_on_vet_routes(user["id"])
    farm = db.get_farmer(user["farmer_id"]) if user["farmer_id"] else None
    return [farm] if farm and farm["active"] else []


# --- self-signup, approved by an admin ------------------------------------------------------

SIGNUP_ROLES = ("farmer", "vet")  # admin is never self-service
MAX_PENDING = 100  # stops a flood of fake signups filling the approval list


def signup(role, name, email, password, phone=None, farm_name=None):
    """Request a login. It cannot be used until an admin approves it. Returns the new user id."""
    if role not in SIGNUP_ROLES:
        raise ValueError("choose farmer or vet")
    name = " ".join(str(name or "").split())
    if not name or len(name) > 80:
        raise ValueError("enter your name")
    email = normalize_email(email)
    check_strength(password)
    if role == "farmer":
        if not phone:
            raise ValueError("enter your phone number")
        farm_name = " ".join(str(farm_name or "").split())[:80] or None
    else:
        farm_name = None
    phone = normalize_phone(phone) if phone else None
    if len(db.list_pending_users()) >= MAX_PENDING:
        raise ValueError("too many signups are waiting: try again later or ask the admin")
    try:
        return db.create_user(role, name, phone, email, hash_password(password), None,
                              active=False, pending=True, farm_name=farm_name)
    except psycopg2.errors.UniqueViolation:
        raise ValueError("that email or phone number already has an account or a signup waiting") from None


def approve_signup(user_id):
    """Activate a pending login. A farmer is linked to their farm (an existing record with the same
    phone, else a new one). Raises ValueError when it can't be approved."""
    user = db.get_user(user_id)
    if not user or not user["pending"]:
        raise ValueError("that signup is no longer waiting")
    farmer_id = None
    if user["role"] == "farmer":
        farm = db.farmer_by_phone(user["phone"])
        if farm and db._query("SELECT 1 FROM users WHERE farmer_id = %s", (farm["id"],), one=True):
            raise ValueError("that farm already has a login")
        farmer_id = farm["id"] if farm else db.add_farmer(user["name"], user["phone"], user["farm_name"])
    db.update_user(user_id, pending=False, active=True, farmer_id=farmer_id)
    return user_id


def reject_signup(user_id):
    db.delete_pending_user(user_id)


# --- deleting ------------------------------------------------------------------------------

CONFIRM_WORD = "DELETE"


def _confirmed(text):
    if str(text or "").strip() != CONFIRM_WORD:
        raise ValueError(f"type {CONFIRM_WORD} to confirm")


def _last_admin(user_id):
    target = db.get_user(user_id)
    return bool(target and target["role"] == "admin" and target["active"] and db.count_active_admins() <= 1)


def delete_own_account(user, confirm):
    """A person deletes their own account. A farmer's farm and all its records go too; a vet's semen list
    goes with them. The only admin cannot leave nobody in charge."""
    _confirmed(confirm)
    if not user or user.get("id") is None:
        raise ValueError("the owner password login has no account to delete")
    if _last_admin(user["id"]):
        raise ValueError("you are the only admin; make another admin first")
    row = db.get_user(user["id"])
    if not row:
        raise ValueError("that account no longer exists")
    if row["role"] == "farmer" and row["farmer_id"]:
        db.delete_farm(row["farmer_id"])  # the login goes with it
    else:
        db.delete_user(row["id"])


def _need_admin(actor):
    if not is_head_admin(actor):
        raise ValueError("only an admin can do that")


def set_route_admin_routes(actor, user_id, route_ids):
    """The head admin chooses which routes a route admin looks after."""
    _need_admin(actor)
    target = db.get_user(user_id)
    if not target or target["role"] != "admin" or not target["route_admin"]:
        raise ValueError("choose a route admin")
    valid = {r["id"] for r in db.list_routes()}
    if not set(route_ids) <= valid:
        raise ValueError("choose routes from the list")
    db.set_admin_routes(user_id, route_ids)


def admin_delete_login(actor, user_id, confirm):
    """Remove one login. A farmer's farm and records stay (use delete farm to remove those too)."""
    _need_admin(actor)
    _confirmed(confirm)
    if user_id == actor.get("id"):
        raise ValueError("you cannot delete your own login here; use My account")
    if _last_admin(user_id):
        raise ValueError("that is the only admin")
    if not db.get_user(user_id):
        raise ValueError("that login no longer exists")
    db.delete_user(user_id)


def admin_delete_farm(actor, farmer_id, confirm):
    """Remove a farm with every record for it, and its farmer login."""
    _need_admin(actor)
    _confirmed(confirm)
    if not db.get_farmer(farmer_id):
        raise ValueError("that farm no longer exists")
    db.delete_farm(farmer_id)


def admin_delete_route(actor, route_id, confirm):
    """Remove a route. Its farms stay, unassigned."""
    _need_admin(actor)
    _confirmed(confirm)
    if route_id not in {r["id"] for r in db.list_routes()}:
        raise ValueError("that route no longer exists")
    db.delete_route(route_id)
