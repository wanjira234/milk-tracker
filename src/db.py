"""Postgres access layer. Raw SQL via psycopg2 on purpose: no ORM."""
import os
from contextlib import contextmanager
from datetime import date

import psycopg2
from psycopg2.extras import RealDictCursor

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv is optional at runtime (Modal passes env directly)
    pass


@contextmanager
def get_conn():
    """Yield a connection; commit on success, roll back on error, always close."""
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

COW_COLUMNS = "id, tag, active, sex, life_stage, birth_date, weaned_on, retired_on, mother_id"


def add_cow(farmer_id, tag, sex="female", life_stage="cow", birth_date=None, mother_id=None):
    """Add a cow (or bring a retired one back). Returns her id.

    A cow already on the farm under this tag keeps her details; only her active flag is reset.
    """
    return _query(
        """
        INSERT INTO cows (farmer_id, tag, sex, life_stage, birth_date, mother_id) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (farmer_id, tag) DO UPDATE SET active = TRUE, retired_on = NULL
        RETURNING id
        """,
        (farmer_id, tag, sex, life_stage, birth_date, mother_id), one=True,
    )["id"]


def list_cows(farmer_id, active_only=True):
    sql = f"SELECT {COW_COLUMNS} FROM cows WHERE farmer_id = %s"
    if active_only:
        sql += " AND active"
    return _query(sql + " ORDER BY tag", (farmer_id,))


def retire_cow(farmer_id, cow_id, on=None):
    """Sold or died: hide her from the lists. Her history stays."""
    _query(
        "UPDATE cows SET active = FALSE, retired_on = COALESCE(%s, CURRENT_DATE) WHERE id = %s AND farmer_id = %s",
        (on, cow_id, farmer_id),
    )


def wean_calf(farmer_id, cow_id, on):
    """A calf stops drinking milk: a female becomes a heifer, a male a young bull."""
    _query(
        """
        UPDATE cows SET weaned_on = %s,
               life_stage = CASE WHEN sex = 'female' THEN 'heifer' ELSE 'bull' END
        WHERE id = %s AND farmer_id = %s AND life_stage = 'calf'
        """,
        (on, cow_id, farmer_id),
    )


def make_adult(farmer_id, cow_id):
    """A heifer who has calved becomes a cow."""
    _query("UPDATE cows SET life_stage = 'cow' WHERE id = %s AND farmer_id = %s AND life_stage = 'heifer'", (cow_id, farmer_id))


def cows_in_milk_from_records(farmer_id):
    row = _query("SELECT cows_in_milk_from_records AS f FROM farmers WHERE id = %s", (farmer_id,), one=True)
    return bool(row and row["f"])


def set_cows_in_milk_from_records(farmer_id, on):
    _query("UPDATE farmers SET cows_in_milk_from_records = %s WHERE id = %s", (bool(on), farmer_id))


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
    """Every cows-in-milk entry, newest first. Worked out from the cow records when the farm chose that."""
    if cows_in_milk_from_records(farmer_id):
        from src import herd

        return herd.history(list_cows(farmer_id, active_only=False), breeding_events(farmer_id))
    return _query(
        "SELECT effective_date, cows_in_milk FROM herd_log WHERE farmer_id = %s ORDER BY effective_date DESC",
        (farmer_id,),
    )


def cows_in_milk_on(farmer_id, day):
    """Cows in milk on `day`: the latest entry on or before it, or None if there is none yet."""
    if cows_in_milk_from_records(farmer_id):
        from src import herd

        return herd.cows_in_milk_on(list_cows(farmer_id, active_only=False), breeding_events(farmer_id), day)
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
