"""Postgres access layer. Raw SQL via psycopg2 on purpose: no ORM."""
import os
import threading
from contextlib import contextmanager
from datetime import date

import psycopg2
from psycopg2.extras import RealDictCursor

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv is optional at runtime (Modal passes env directly)
    pass


_local = threading.local()


@contextmanager
def batch():
    """Run many queries on ONE connection and ONE transaction: fast on a slow link, and all-or-nothing.

    For scripts that write a lot (the demo seed). Not for code that wants to catch a database error
    and carry on: after a failed statement the whole batch is rolled back. Nested use joins the
    outer batch. Each thread has its own, so web requests are unaffected.
    """
    if getattr(_local, "conn", None) is not None:
        yield
        return
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    _local.conn = conn
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _local.conn = None
        conn.close()


@contextmanager
def get_conn():
    """Yield a connection; commit on success, roll back on error, always close.
    Inside `batch()` the shared connection is used instead and the batch does the commit."""
    shared = getattr(_local, "conn", None)
    if shared is not None:
        yield shared
        return
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _query(sql, params=(), one=False):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        if cur.description is None:
            return None
        return cur.fetchone() if one else cur.fetchall()


# --- farmers -----------------------------------------------------------------

def add_farmer(name, phone, farm_name=None, herd_size=None):
    """Create a farmer, or update the existing one with the same phone. Returns id."""
    row = _query(
        """
        INSERT INTO farmers (name, phone, farm_name, herd_size)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (phone) DO UPDATE
            SET name = EXCLUDED.name,
                farm_name = COALESCE(EXCLUDED.farm_name, farmers.farm_name),
                herd_size = COALESCE(EXCLUDED.herd_size, farmers.herd_size)
        RETURNING id
        """,
        (name, phone, farm_name, herd_size),
        one=True,
    )
    return row["id"]


def list_farmers(active_only=True):
    sql = "SELECT * FROM farmers"
    if active_only:
        sql += " WHERE active"
    return _query(sql + " ORDER BY id")


# --- yield and feed ----------------------------------------------------------

def upsert_yield(farmer_id, log_date, session, litres, source="manual"):
    """Record one milking session. Re-entering the same session overwrites it."""
    _query(
        """
        INSERT INTO yield_logs (farmer_id, log_date, session, litres, source)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (farmer_id, log_date, session) DO UPDATE
            SET litres = EXCLUDED.litres, source = EXCLUDED.source
        """,
        (farmer_id, log_date, session, litres, source),
    )


def add_feed(farmer_id, log_date, feed_type, kg, cost_kes=None, units=None, catalogue_id=None):
    """Record one feed entry. kg and cost_kes are canonical; units/catalogue_id say how it was entered."""
    _query(
        """
        INSERT INTO feed_logs (farmer_id, log_date, feed_type, kg, cost_kes, units, catalogue_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (farmer_id, log_date, feed_type, kg, cost_kes, units, catalogue_id),
    )


def daily_yield(farmer_id, start, end):
    """Total litres per day (all sessions summed), oldest first."""
    return _query(
        """
        SELECT log_date, SUM(litres) AS litres, COUNT(*) AS sessions
        FROM yield_logs
        WHERE farmer_id = %s AND log_date BETWEEN %s AND %s
        GROUP BY log_date ORDER BY log_date
        """,
        (farmer_id, start, end),
    )


def daily_feed(farmer_id, start, end):
    """Feed per day per type, oldest first."""
    return _query(
        """
        SELECT log_date, feed_type, SUM(kg) AS kg, SUM(cost_kes) AS cost_kes
        FROM feed_logs
        WHERE farmer_id = %s AND log_date BETWEEN %s AND %s
        GROUP BY log_date, feed_type ORDER BY log_date, feed_type
        """,
        (farmer_id, start, end),
    )


# --- water -------------------------------------------------------------------

def set_water(farmer_id, log_date, litres):
    """Set the herd's total water for a day (saving the same day again replaces it)."""
    _query(
        """
        INSERT INTO water_logs (farmer_id, log_date, litres) VALUES (%s, %s, %s)
        ON CONFLICT (farmer_id, log_date) DO UPDATE SET litres = EXCLUDED.litres
        """,
        (farmer_id, log_date, litres),
    )


def daily_water(farmer_id, start, end):
    """[{log_date, litres}] oldest first."""
    return _query(
        "SELECT log_date, litres FROM water_logs WHERE farmer_id = %s AND log_date BETWEEN %s AND %s ORDER BY log_date",
        (farmer_id, start, end),
    )


# --- cows: breeding, semen, deworming ------------------------------------------

def add_cow(farmer_id, tag, kind="cow", sex="female", dam_id=None, born_on=None):
    """Add an animal (or bring a retired one back; an existing animal keeps her details). Returns her id."""
    return _query(
        """
        INSERT INTO cows (farmer_id, tag, kind, sex, dam_id, born_on) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (farmer_id, tag) DO UPDATE SET active = TRUE
        RETURNING id
        """,
        (farmer_id, tag, kind, sex, dam_id, born_on), one=True,
    )["id"]


def list_cows(farmer_id, active_only=True):
    sql = "SELECT id, tag, active, kind, sex, dam_id, born_on, weaned_on FROM cows WHERE farmer_id = %s"
    if active_only:
        sql += " AND active"
    return _query(sql + " ORDER BY tag", (farmer_id,))


def set_cow_kind(farmer_id, cow_id, kind):
    _query("UPDATE cows SET kind = %s WHERE id = %s AND farmer_id = %s", (kind, cow_id, farmer_id))


def set_weaned(farmer_id, cow_id, weaned_on, kind=None):
    """Record weaning; kind (e.g. 'heifer') changes her stage in the same step."""
    _query(
        "UPDATE cows SET weaned_on = %s, kind = COALESCE(%s, kind) WHERE id = %s AND farmer_id = %s",
        (weaned_on, kind, cow_id, farmer_id),
    )


def retire_cow(farmer_id, cow_id):
    """Sold or died: hide her from the lists. Her history stays."""
    _query("UPDATE cows SET active = FALSE WHERE id = %s AND farmer_id = %s", (cow_id, farmer_id))


def add_semen(farmer_id, name):
    return _query(
        """
        INSERT INTO semen_options (farmer_id, name) VALUES (%s, %s)
        ON CONFLICT (farmer_id, name) DO UPDATE SET active = TRUE
        RETURNING id
        """,
        (farmer_id, name), one=True,
    )["id"]


def list_semen(farmer_id, active_only=True):
    sql = "SELECT id, name, active FROM semen_options WHERE farmer_id = %s"
    if active_only:
        sql += " AND active"
    return _query(sql + " ORDER BY name", (farmer_id,))


def retire_semen(farmer_id, semen_id):
    _query("UPDATE semen_options SET active = FALSE WHERE id = %s AND farmer_id = %s", (semen_id, farmer_id))


def add_breeding_event(farmer_id, cow_id, event_date, kind, semen_id=None):
    """The database refuses a cow or semen that belongs to another farm."""
    _query(
        "INSERT INTO breeding_events (farmer_id, cow_id, event_date, kind, semen_id) VALUES (%s, %s, %s, %s, %s)",
        (farmer_id, cow_id, event_date, kind, semen_id),
    )


def breeding_events(farmer_id, cow_id=None):
    """[{cow_id, event_date, kind, semen}] oldest first (semen = its name, or None)."""
    sql = """
        SELECT b.id, b.cow_id, b.event_date, b.kind, s.name AS semen
        FROM breeding_events b LEFT JOIN semen_options s ON s.id = b.semen_id
        WHERE b.farmer_id = %s
    """
    args = [farmer_id]
    if cow_id is not None:
        sql += " AND b.cow_id = %s"
        args.append(cow_id)
    return _query(sql + " ORDER BY b.event_date, b.id", tuple(args))


def delete_breeding_event(farmer_id, event_id):
    """For fixing a mistake."""
    _query("DELETE FROM breeding_events WHERE id = %s AND farmer_id = %s", (event_id, farmer_id))


def add_deworming(farmer_id, given_on, cow_id=None, product=None):
    """cow_id None = the whole herd."""
    _query(
        "INSERT INTO dewormings (farmer_id, cow_id, given_on, product) VALUES (%s, %s, %s, %s)",
        (farmer_id, cow_id, given_on, product),
    )


def dewormings(farmer_id):
    """[{cow_id (None = whole herd), given_on, product}] oldest first."""
    return _query(
        "SELECT cow_id, given_on, product FROM dewormings WHERE farmer_id = %s ORDER BY given_on, id", (farmer_id,)
    )


# --- accounts, routes, login codes -----------------------------------------------

USER_COLUMNS = "id, role, name, phone, email, farmer_id, must_change_password, active, failed_logins, locked_until, pending, farm_name"


def create_user(role, name, phone=None, email=None, password_hash=None, farmer_id=None, must_change_password=False,
                active=True, pending=False, farm_name=None):
    return _query(
        """
        INSERT INTO users (role, name, phone, email, password_hash, farmer_id, must_change_password, active, pending, farm_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (role, name, phone, email, password_hash, farmer_id, must_change_password, active, pending, farm_name), one=True,
    )["id"]


def list_pending_users():
    return _query(f"SELECT {USER_COLUMNS}, created_at FROM users WHERE pending ORDER BY created_at, id")


def delete_pending_user(user_id):
    """Reject a signup. Only ever removes a login that is still pending."""
    _query("DELETE FROM users WHERE id = %s AND pending", (user_id,))


def get_user(user_id):
    return _query(f"SELECT {USER_COLUMNS} FROM users WHERE id = %s", (user_id,), one=True)


def user_by_phone(phone):
    return _query(f"SELECT {USER_COLUMNS} FROM users WHERE phone = %s", (phone,), one=True)


def user_by_email(email):
    """Includes password_hash, for checking a login. Never show it."""
    return _query(f"SELECT {USER_COLUMNS}, password_hash FROM users WHERE email = %s", (email,), one=True)


def list_users(role=None):
    sql = f"SELECT {USER_COLUMNS} FROM users"
    args = ()
    if role:
        sql += " WHERE role = %s"
        args = (role,)
    return _query(sql + " ORDER BY role, name", args)


def update_user(user_id, **fields):
    allowed = {"name", "phone", "email", "password_hash", "must_change_password", "active", "failed_logins", "locked_until", "pending", "farmer_id"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot update {sorted(bad)}")
    if not fields:
        return
    sets = ", ".join(f"{k} = %s" for k in fields)
    _query(f"UPDATE users SET {sets} WHERE id = %s", (*fields.values(), user_id))


def count_active_admins():
    return _query("SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND active AND NOT pending", one=True)["n"]


def delete_user(user_id):
    """Remove a login. A vet's priced semen goes with them, so past requests keep their price but
    forget which list item it was."""
    with batch():
        _query(
            "UPDATE service_requests SET semen_id = NULL WHERE semen_id IN (SELECT id FROM vet_semen WHERE vet_user_id = %s)",
            (user_id,),
        )
        _query("DELETE FROM users WHERE id = %s", (user_id,))


def delete_farm(farmer_id):
    """Remove a farm with everything recorded for it, and its login (the database cascades)."""
    _query("DELETE FROM farmers WHERE id = %s", (farmer_id,))


def delete_route(route_id):
    """Remove a route. Its farms stay, unassigned; alerts and vaccination days for it go with it."""
    _query("DELETE FROM routes WHERE id = %s", (route_id,))


def farmer_by_phone(phone):
    return _query("SELECT * FROM farmers WHERE phone = %s", (phone,), one=True)


def get_farmer(farmer_id):
    return _query("SELECT * FROM farmers WHERE id = %s", (farmer_id,), one=True)


def add_route(code, name=None):
    return _query(
        """
        INSERT INTO routes (code, name) VALUES (%s, %s)
        ON CONFLICT (code) DO UPDATE SET name = COALESCE(EXCLUDED.name, routes.name)
        RETURNING id
        """,
        (code, name), one=True,
    )["id"]


def list_routes():
    return _query(
        """
        SELECT r.id, r.code, r.name, r.vet_user_id, u.name AS vet_name,
               (SELECT COUNT(*) FROM farmers f WHERE f.route_id = r.id) AS farms
        FROM routes r LEFT JOIN users u ON u.id = r.vet_user_id ORDER BY r.code
        """
    )


def set_route_vet(route_id, vet_user_id):
    _query("UPDATE routes SET vet_user_id = %s WHERE id = %s", (vet_user_id, route_id))


def set_farmer_route(farmer_id, route_id):
    _query("UPDATE farmers SET route_id = %s WHERE id = %s", (route_id, farmer_id))


def farmers_on_vet_routes(vet_user_id):
    return _query(
        "SELECT f.* FROM farmers f JOIN routes r ON r.id = f.route_id WHERE r.vet_user_id = %s AND f.active ORDER BY f.id",
        (vet_user_id,),
    )


def add_login_code(user_id, salt, code_hash, expires_at, created_at):
    """created_at comes from the app's clock (not the database's) so throttling and expiry agree."""
    _query(
        "INSERT INTO login_codes (user_id, salt, code_hash, expires_at, created_at) VALUES (%s, %s, %s, %s, %s)",
        (user_id, salt, code_hash, expires_at, created_at),
    )


def recent_login_code_times(user_id, since):
    return [r["created_at"] for r in _query(
        "SELECT created_at FROM login_codes WHERE user_id = %s AND created_at > %s", (user_id, since)
    )]


def latest_login_code(user_id):
    return _query(
        "SELECT id, salt, code_hash, expires_at, attempts, used FROM login_codes WHERE user_id = %s "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        (user_id,), one=True,
    )


def bump_login_attempts(code_id):
    _query("UPDATE login_codes SET attempts = attempts + 1 WHERE id = %s", (code_id,))


def use_login_code(code_id):
    _query("UPDATE login_codes SET used = TRUE WHERE id = %s", (code_id,))


# --- budget ------------------------------------------------------------------

def month_start(d: date) -> date:
    return d.replace(day=1)


def month_feed_spend(farmer_id, month: date):
    """Total feed cost logged in the month containing `month`."""
    row = _query(
        """
        SELECT COALESCE(SUM(cost_kes), 0) AS spent
        FROM feed_logs
        WHERE farmer_id = %s
          AND log_date >= date_trunc('month', %s::date)::date
          AND log_date <  (date_trunc('month', %s::date) + interval '1 month')::date
        """,
        (farmer_id, month, month),
        one=True,
    )
    return row["spent"]


def monthly_feed_spend(farmer_id, today: date, months=6):
    """Feed spend per month for the current month and the previous `months`, newest first.

    `uncosted` counts entries with no cost, which makes `spent` an understatement.
    """
    return _query(
        """
        SELECT date_trunc('month', log_date)::date AS month,
               COALESCE(SUM(cost_kes), 0)          AS spent,
               COUNT(*)                            AS entries,
               COUNT(*) FILTER (WHERE cost_kes IS NULL) AS uncosted
        FROM feed_logs
        WHERE farmer_id = %s
          AND log_date >= (date_trunc('month', %s::date) - make_interval(months => %s))::date
          AND log_date <= %s::date
        GROUP BY 1 ORDER BY 1 DESC
        """,
        (farmer_id, today, months, today),
    )


def set_budget(farmer_id, month: date, feed_budget_kes):
    _query(
        """
        INSERT INTO monthly_budgets (farmer_id, month, feed_budget_kes)
        VALUES (%s, %s, %s)
        ON CONFLICT (farmer_id, month) DO UPDATE SET feed_budget_kes = EXCLUDED.feed_budget_kes
        """,
        (farmer_id, month_start(month), feed_budget_kes),
    )


def get_budget(farmer_id, month: date):
    row = _query(
        "SELECT feed_budget_kes FROM monthly_budgets WHERE farmer_id = %s AND month = %s",
        (farmer_id, month_start(month)),
        one=True,
    )
    return row["feed_budget_kes"] if row else None


# --- sms ---------------------------------------------------------------------

def log_sms(farmer_id, body, status="queued", provider_ref=None, kind="other"):
    _query(
        "INSERT INTO sms_log (farmer_id, body, status, provider_ref, kind) VALUES (%s, %s, %s, %s, %s)",
        (farmer_id, body, status, provider_ref, kind),
    )


def recent_sms(farmer_id, days=30):
    """Messages sent (not failed) to a farmer in the last `days` days: kind and sent_at, newest first."""
    return _query(
        """
        SELECT kind, sent_at FROM sms_log
        WHERE farmer_id = %s AND status = 'sent' AND sent_at > now() - make_interval(days => %s)
        ORDER BY sent_at DESC
        """,
        (farmer_id, days),
    )


def save_snapshot(farmer_id, taken_on, usable_days, decision_kind, effects_json, recent_kg_json):
    """Store (or replace, for the same day) what the model believed about a farm."""
    _query(
        """
        INSERT INTO model_snapshots (farmer_id, taken_on, usable_days, decision_kind, effects, recent_kg)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
        ON CONFLICT (farmer_id, taken_on) DO UPDATE
            SET usable_days = EXCLUDED.usable_days, decision_kind = EXCLUDED.decision_kind,
                effects = EXCLUDED.effects, recent_kg = EXCLUDED.recent_kg
        """,
        (farmer_id, taken_on, usable_days, decision_kind, effects_json, recent_kg_json),
    )


def list_snapshots(farmer_id):
    return _query("SELECT * FROM model_snapshots WHERE farmer_id = %s ORDER BY taken_on", (farmer_id,))


# --- farm setup: milk price, feed catalogue, cows in milk --------------------

def set_milk_price(farmer_id, price_kes):
    _query("UPDATE farmers SET milk_price_kes = %s WHERE id = %s", (price_kes, farmer_id))


def get_milk_price(farmer_id):
    """KES per litre, or None if the farmer has not set one."""
    row = _query("SELECT milk_price_kes FROM farmers WHERE id = %s", (farmer_id,), one=True)
    return row["milk_price_kes"] if row else None


def upsert_catalogue_item(farmer_id, name, unit, kg_per_unit, kes_per_unit):
    """Add a feed to the farm's catalogue, or update it (and reactivate it). Returns id."""
    row = _query(
        """
        INSERT INTO feed_catalogue (farmer_id, name, unit, kg_per_unit, kes_per_unit)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (farmer_id, name) DO UPDATE
            SET unit = EXCLUDED.unit,
                kg_per_unit = EXCLUDED.kg_per_unit,
                kes_per_unit = EXCLUDED.kes_per_unit,
                active = TRUE
        RETURNING id
        """,
        (farmer_id, name, unit, kg_per_unit, kes_per_unit),
        one=True,
    )
    return row["id"]


def list_catalogue(farmer_id, active_only=True):
    sql = "SELECT * FROM feed_catalogue WHERE farmer_id = %s"
    if active_only:
        sql += " AND active"
    return _query(sql + " ORDER BY name", (farmer_id,))


def retire_catalogue_item(item_id):
    """Hide a feed from the logging form. Past entries keep their numbers."""
    _query("UPDATE feed_catalogue SET active = FALSE WHERE id = %s", (item_id,))


def set_cows_in_milk(farmer_id, effective_date, cows):
    """Cows in milk from effective_date until the next entry. Same date overwrites."""
    _query(
        """
        INSERT INTO herd_log (farmer_id, effective_date, cows_in_milk)
        VALUES (%s, %s, %s)
        ON CONFLICT (farmer_id, effective_date) DO UPDATE SET cows_in_milk = EXCLUDED.cows_in_milk
        """,
        (farmer_id, effective_date, cows),
    )


def herd_history(farmer_id):
    """Every cows-in-milk entry, newest first."""
    return _query(
        "SELECT effective_date, cows_in_milk FROM herd_log WHERE farmer_id = %s ORDER BY effective_date DESC",
        (farmer_id,),
    )


def cows_in_milk_on(farmer_id, day):
    """Cows in milk on `day`: the latest entry on or before it, or None if there is none yet."""
    row = _query(
        """
        SELECT cows_in_milk FROM herd_log
        WHERE farmer_id = %s AND effective_date <= %s
        ORDER BY effective_date DESC LIMIT 1
        """,
        (farmer_id, day),
        one=True,
    )
    return row["cows_in_milk"] if row else None


# --- model inputs ------------------------------------------------------------

def feed_cost_per_kg(farmer_id, start, end):
    """Average KES per kg actually paid, per feed, over [start, end].

    Only entries that have a cost count, in both the money and the kilograms, so an entry
    logged without a cost can't drag the price toward zero. Feeds with no costed entry are
    left out (the price is unknown, which is not the same as free).
    """
    rows = _query(
        """
        SELECT feed_type,
               SUM(cost_kes) / NULLIF(SUM(kg) FILTER (WHERE cost_kes IS NOT NULL), 0) AS cost_per_kg
        FROM feed_logs
        WHERE farmer_id = %s AND log_date BETWEEN %s AND %s
        GROUP BY feed_type
        """,
        (farmer_id, start, end),
    )
    return {r["feed_type"]: float(r["cost_per_kg"]) for r in rows if r["cost_per_kg"] is not None}


# --- vets' semen and service requests -----------------------------------------------------------


def add_vet_semen(vet_user_id, name, price_kes):
    """Add a bull/breed with its price, or update the price of one already listed (and relist it)."""
    return _query(
        """
        INSERT INTO vet_semen (vet_user_id, name, price_kes) VALUES (%s, %s, %s)
        ON CONFLICT (vet_user_id, name) DO UPDATE SET price_kes = EXCLUDED.price_kes, active = TRUE
        RETURNING id
        """,
        (vet_user_id, name, price_kes), one=True,
    )["id"]


def list_vet_semen(vet_user_id, active_only=True):
    sql = "SELECT id, vet_user_id, name, price_kes, active FROM vet_semen WHERE vet_user_id = %s"
    if active_only:
        sql += " AND active"
    return _query(sql + " ORDER BY name", (vet_user_id,))


def get_vet_semen(semen_id):
    return _query("SELECT id, vet_user_id, name, price_kes, active FROM vet_semen WHERE id = %s", (semen_id,), one=True)


def retire_vet_semen(vet_user_id, semen_id):
    _query("UPDATE vet_semen SET active = FALSE WHERE id = %s AND vet_user_id = %s", (semen_id, vet_user_id))


def route_vet_id(farmer_id):
    """The vet on this farm's route, or None (no route, or the route has no vet)."""
    row = _query(
        "SELECT r.vet_user_id FROM farmers f JOIN routes r ON r.id = f.route_id WHERE f.id = %s", (farmer_id,), one=True
    )
    return row["vet_user_id"] if row else None


REQUEST_SELECT = """
    SELECT q.id, q.farmer_id, q.cow_id, q.kind, q.notes, q.preferred_date, q.status, q.scheduled_for,
           q.semen_id, q.semen_price_kes, q.done_on, q.done_by_user_id, q.vet_notes, q.created_at,
           f.name AS farmer_name, f.farm_name, f.phone AS farmer_phone, r.code AS route_code,
           r.vet_user_id AS vet_user_id, v.name AS vet_name, c.tag AS cow_tag, s.name AS semen_name,
           q.vaccination_day_id, q.animals, vd.vaccine
    FROM service_requests q
    JOIN farmers f ON f.id = q.farmer_id
    LEFT JOIN routes r ON r.id = f.route_id
    LEFT JOIN users v ON v.id = r.vet_user_id
    LEFT JOIN cows c ON c.id = q.cow_id
    LEFT JOIN vet_semen s ON s.id = q.semen_id
    LEFT JOIN vaccination_days vd ON vd.id = q.vaccination_day_id
"""


def add_request(farmer_id, kind, preferred_date, cow_id=None, semen_id=None, semen_price_kes=None, notes=None):
    return _query(
        """
        INSERT INTO service_requests (farmer_id, cow_id, kind, notes, preferred_date, semen_id, semen_price_kes)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (farmer_id, cow_id, kind, notes, preferred_date, semen_id, semen_price_kes), one=True,
    )["id"]


def get_request(request_id):
    return _query(REQUEST_SELECT + " WHERE q.id = %s", (request_id,), one=True)


def requests_for_farm(farmer_id, limit=50):
    return _query(REQUEST_SELECT + " WHERE q.farmer_id = %s ORDER BY q.created_at DESC, q.id DESC LIMIT %s", (farmer_id, limit))


def requests_for_vet(vet_user_id, statuses):
    """Requests from farms on this vet's routes, oldest wish first."""
    return _query(
        REQUEST_SELECT + " WHERE r.vet_user_id = %s AND q.status = ANY(%s) "
        "ORDER BY COALESCE(q.scheduled_for, q.preferred_date), q.id",
        (vet_user_id, list(statuses)),
    )


def requests_for_attendance(day):
    """Everything still to do, plus what was finished on `day`: the admin's attended-or-not view."""
    return _query(
        REQUEST_SELECT + " WHERE q.status IN ('open', 'scheduled') OR (q.status = 'done' AND q.done_on = %s) "
        "ORDER BY COALESCE(q.scheduled_for, q.preferred_date), q.id",
        (day,),
    )


def open_request_count(farmer_id):
    return _query(
        "SELECT COUNT(*) AS n FROM service_requests WHERE farmer_id = %s AND status IN ('open', 'scheduled')", (farmer_id,), one=True
    )["n"]


def has_open_request(farmer_id, cow_id, kind):
    return _query(
        "SELECT 1 FROM service_requests WHERE farmer_id = %s AND cow_id = %s AND kind = %s AND status IN ('open', 'scheduled')",
        (farmer_id, cow_id, kind), one=True,
    ) is not None


def update_request(request_id, **fields):
    allowed = {"status", "scheduled_for", "semen_id", "semen_price_kes", "done_on", "done_by_user_id", "vet_notes"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot update {sorted(bad)}")
    sets = ", ".join(f"{k} = %s" for k in fields)
    _query(f"UPDATE service_requests SET {sets} WHERE id = %s", (*fields.values(), request_id))


def semen_cost(farmer_id, start, end):
    """KES of semen on AI visits completed from `start` to `end` inclusive."""
    row = _query(
        "SELECT COALESCE(SUM(semen_price_kes), 0) AS kes, COUNT(*) AS n FROM service_requests "
        "WHERE farmer_id = %s AND kind = 'ai' AND status = 'done' AND semen_price_kes IS NOT NULL AND done_on BETWEEN %s AND %s",
        (farmer_id, start, end), one=True,
    )
    return float(row["kes"]), int(row["n"])


# --- alerts and the SMS outbox -------------------------------------------------------------------

ALERT_SELECT = """
    SELECT a.id, a.kind, a.title, a.body, a.route_id, a.created_by_user_id, a.created_at, a.expires_on,
           a.sms_sent_at, a.sms_ok, a.sms_failed, r.code AS route_code, u.name AS author
    FROM alerts a LEFT JOIN routes r ON r.id = a.route_id LEFT JOIN users u ON u.id = a.created_by_user_id
"""


def add_alert(kind, title, body, route_id, created_by_user_id, expires_on=None):
    return _query(
        "INSERT INTO alerts (kind, title, body, route_id, created_by_user_id, expires_on) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (kind, title, body, route_id, created_by_user_id, expires_on), one=True,
    )["id"]


def get_alert(alert_id):
    return _query(ALERT_SELECT + " WHERE a.id = %s", (alert_id,), one=True)


def list_alerts(today, route_ids=None, limit=50):
    """Alerts still in force on `today`, newest first. route_ids=None means every route (admin);
    otherwise only alerts for those routes plus the ones sent to all routes."""
    sql = ALERT_SELECT + " WHERE (a.expires_on IS NULL OR a.expires_on >= %s)"
    args = [today]
    if route_ids is not None:
        sql += " AND (a.route_id IS NULL OR a.route_id = ANY(%s))"
        args.append(list(route_ids))
    return _query(sql + " ORDER BY a.created_at DESC, a.id DESC LIMIT %s", (*args, limit))


def claim_alert_sms(alert_id):
    """Mark the alert's SMS as sent-now. True only for the first caller, so a double click can't text everyone twice."""
    return _query(
        "UPDATE alerts SET sms_sent_at = now() WHERE id = %s AND sms_sent_at IS NULL RETURNING id", (alert_id,), one=True
    ) is not None


def set_alert_sms_counts(alert_id, ok, failed):
    _query("UPDATE alerts SET sms_ok = %s, sms_failed = %s WHERE id = %s", (ok, failed, alert_id))


def farmers_for_alert(route_id):
    """Active farms with a phone on one route, or on every route when route_id is None."""
    sql = "SELECT id, name, farm_name, phone, route_id FROM farmers WHERE active AND phone IS NOT NULL"
    args = ()
    if route_id is not None:
        sql += " AND route_id = %s"
        args = (route_id,)
    return _query(sql + " ORDER BY id", args)


def sms_outbox(farmer_ids=None, limit=50):
    """Messages the system sent (or tried to), newest first. farmer_ids=None means every farm."""
    sql = ("SELECT s.id, s.farmer_id, f.name AS farmer_name, s.body, s.status, s.kind, s.sent_at "
           "FROM sms_log s JOIN farmers f ON f.id = s.farmer_id")
    args = []
    if farmer_ids is not None:
        sql += " WHERE s.farmer_id = ANY(%s)"
        args.append(list(farmer_ids))
    return _query(sql + " ORDER BY s.sent_at DESC, s.id DESC LIMIT %s", (*args, limit))


# --- vaccination days ----------------------------------------------------------------------------

VACCINATION_SELECT = """
    SELECT d.id, d.vaccine, d.day, d.place, d.notes, d.route_id, d.cancelled, d.created_at,
           r.code AS route_code, u.name AS author,
           (SELECT COUNT(*) FROM service_requests q WHERE q.vaccination_day_id = d.id AND q.status IN ('scheduled', 'done')) AS bookings,
           (SELECT COALESCE(SUM(q.animals), 0) FROM service_requests q WHERE q.vaccination_day_id = d.id AND q.status IN ('scheduled', 'done')) AS animals
    FROM vaccination_days d LEFT JOIN routes r ON r.id = d.route_id LEFT JOIN users u ON u.id = d.created_by_user_id
"""


def add_vaccination_day(vaccine, day, route_id, created_by_user_id, place=None, notes=None):
    return _query(
        "INSERT INTO vaccination_days (vaccine, day, place, notes, route_id, created_by_user_id) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (vaccine, day, place, notes, route_id, created_by_user_id), one=True,
    )["id"]


def get_vaccination_day(day_id):
    return _query(VACCINATION_SELECT + " WHERE d.id = %s", (day_id,), one=True)


def list_vaccination_days(today, route_ids=None):
    """Days not yet past and not cancelled, soonest first. route_ids=None means every route; otherwise
    those routes plus the days for all routes."""
    sql = VACCINATION_SELECT + " WHERE NOT d.cancelled AND d.day >= %s"
    args = [today]
    if route_ids is not None:
        sql += " AND (d.route_id IS NULL OR d.route_id = ANY(%s))"
        args.append(list(route_ids))
    return _query(sql + " ORDER BY d.day, d.id", args)


def cancel_vaccination_day(day_id):
    """Cancel the day and every booking on it that is not already done."""
    _query("UPDATE vaccination_days SET cancelled = TRUE WHERE id = %s", (day_id,))
    _query(
        "UPDATE service_requests SET status = 'cancelled' WHERE vaccination_day_id = %s AND status IN ('open', 'scheduled')", (day_id,)
    )


def add_vaccination_booking(farmer_id, day_id, day, animals, notes):
    """Book a farm on a vaccination day as a visit already scheduled for that day."""
    return _query(
        """
        INSERT INTO service_requests (farmer_id, kind, notes, preferred_date, status, scheduled_for, vaccination_day_id, animals)
        VALUES (%s, 'vaccination', %s, %s, 'scheduled', %s, %s, %s) RETURNING id
        """,
        (farmer_id, notes, day, day, day_id, animals), one=True,
    )["id"]


def bookings_for_day(day_id):
    return _query(
        REQUEST_SELECT + " WHERE q.vaccination_day_id = %s AND q.status IN ('scheduled', 'done') ORDER BY f.name", (day_id,)
    )
