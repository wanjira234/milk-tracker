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

def log_sms(farmer_id, body, status="queued", provider_ref=None):
    _query(
        "INSERT INTO sms_log (farmer_id, body, status, provider_ref) VALUES (%s, %s, %s, %s)",
        (farmer_id, body, status, provider_ref),
    )


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
