"""Outbreak alerts and notices from admins and vets to farmers. Logic only (no Streamlit).

Rules that matter:
  - an admin may alert one route or every route; a vet only their own routes;
  - a farmer sees the alerts for their route plus the ones sent to every route, until they expire;
  - sending by SMS is a one-time action per alert (claimed in the database first), goes only to the
    farms the alert is for, and is refused when the text would not fit in two SMS segments or
    uses characters outside the basic SMS alphabet.
"""
from datetime import date

from src import accounts, db, sms
from src.messages import APP_NAME, normalize

KINDS = {"outbreak": "Outbreak", "notice": "Notice"}
MAX_TITLE = 60
MAX_BODY = 400


def _routes_of(user):
    """None = any route (admin); otherwise the set of route ids this vet looks after."""
    if user["role"] == "admin":
        return None
    if user["role"] == "vet":
        return {r["id"] for r in db.list_routes() if r["vet_user_id"] == user["id"]}
    raise ValueError("only an admin or a vet can send alerts")


def sms_text(kind, title, body):
    """The SMS for an alert: 'Milk Tracker: OUTBREAK: <title>. <body>' as plain single-line text."""
    label = "OUTBREAK" if kind == "outbreak" else "Notice"
    title = normalize(title).rstrip(".")
    return normalize(f"{APP_NAME}: {label}: {title}. {body}")


def sms_problem(text):
    """Why this text can't go out as an SMS, or None when it can."""
    if sms.gsm_length(text) is None:
        return "uses characters outside the basic SMS alphabet (emoji or symbols): rewrite it in plain letters"
    n = sms.sms_segments(text)
    if n > sms.MAX_SEGMENTS:
        return f"is too long for SMS ({n} segments, the limit is {sms.MAX_SEGMENTS}): shorten it"
    return None


def can_send(user, alert):
    """Whether this login may text this alert (an admin any; a vet only alerts for their own routes)."""
    try:
        allowed = _routes_of(user)
    except ValueError:
        return False
    return allowed is None or alert["route_id"] in allowed


def post_alert(user, kind, title, body, route_id=None, expires_on=None, today=None):
    """Save an alert (in-app; texting is a separate step). Returns its id."""
    today = today or date.today()
    allowed = _routes_of(user)
    if kind not in KINDS:
        raise ValueError("choose outbreak or notice")
    title, body = " ".join(str(title or "").split()), " ".join(str(body or "").split())
    if not title:
        raise ValueError("write a short title")
    if len(title) > MAX_TITLE:
        raise ValueError(f"the title is too long ({MAX_TITLE} characters at most)")
    if not body:
        raise ValueError("write what farmers should know or do")
    if len(body) > MAX_BODY:
        raise ValueError(f"the message is too long ({MAX_BODY} characters at most)")
    if route_id is None:
        if allowed is not None:
            raise ValueError("a vet can alert only their own routes")
    elif route_id not in {r["id"] for r in db.list_routes()} or (allowed is not None and route_id not in allowed):
        raise ValueError("choose one of your routes")
    if expires_on is not None and expires_on < today:
        raise ValueError("the end date cannot be in the past")
    return db.add_alert(kind, title, body, route_id, user["id"] if user["id"] is not None else None, expires_on)


def send_alert_sms(alert_id, user, client=None):
    """Text an alert to the farms it is for, once. Returns {"ok": n, "failed": m}."""
    allowed = _routes_of(user)
    alert = db.get_alert(alert_id)
    if not alert:
        raise ValueError("that alert does not exist")
    if allowed is not None and alert["route_id"] not in allowed:
        raise ValueError("that alert is not for your routes")
    text = sms_text(alert["kind"], alert["title"], alert["body"])
    problem = sms_problem(text)
    if problem:
        raise ValueError(f"the text {problem}")
    farms = db.farmers_for_alert(alert["route_id"])
    if not farms:
        raise ValueError("no farm with a phone number is on that route")
    if not db.claim_alert_sms(alert_id):
        raise ValueError("this alert was already sent by SMS")
    ok = failed = 0
    for farm in farms:
        result = sms.send_to_farmer(farm["id"], farm["phone"], text, client=client, kind="alert")
        ok, failed = (ok + 1, failed) if result["ok"] else (ok, failed + 1)
    db.set_alert_sms_counts(alert_id, ok, failed)
    return {"ok": ok, "failed": failed}


def visible_alerts(user, today=None):
    """The alerts this login may read: admin all; vet their routes' plus all-route ones; farmer their route's."""
    today = today or date.today()
    if user["role"] == "admin":
        return db.list_alerts(today)
    if user["role"] == "vet":
        return db.list_alerts(today, _routes_of(user))
    farm = db.get_farmer(user["farmer_id"]) if user["farmer_id"] else None
    return db.list_alerts(today, [farm["route_id"]] if farm and farm["route_id"] else [])


def outbox(user, limit=50):
    """The SMS the system sent to the farms this login may see, newest first."""
    ids = None if user["role"] == "admin" else [f["id"] for f in accounts.visible_farmers(user)]
    return db.sms_outbox(ids, limit)
