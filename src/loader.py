"""Assemble one farmer's data, run the model, and decide what to say.

`assess_rows` is pure (rows in, result out) so it can be tested without a database.
`assess_farmer` loads the rows from Postgres and calls it.

The window ends YESTERDAY. Today's milkings and feed are usually still being logged, and
half a day of feed would look like a drop in feeding.

Run it by hand to see what the model thinks of one farm:

    python -m src.loader FARMER_ID
"""
import sys
from datetime import date, timedelta

from src import db
from src.models import WINDOW_DAYS, cows_series, feed_effects
from src.suggestions import current_cost_per_kg, decide
from src.trends import daily_frame

RECENT_FEED_DAYS = 14  # "how much is fed lately": the last 14 days on which any feed was logged


def window(today):
    """(start, end) of the days the model looks at: the last WINDOW_DAYS full days."""
    end = today - timedelta(days=1)
    return end - timedelta(days=WINDOW_DAYS - 1), end


def recent_kg_per_day(feed_kg, days=RECENT_FEED_DAYS):
    """Kg per day the herd was fed lately, per feed.

    Averages over the last `days` days on which any feed was logged, so a day nobody
    logged doesn't read as 'fed nothing' and pull the amount down.
    """
    if feed_kg.empty:
        return {}
    logged = feed_kg[feed_kg.sum(axis=1) > 0]
    if logged.empty:
        return {}
    return {name: float(v) for name, v in logged.tail(days).mean().items()}


def assess_rows(
    yield_rows, feed_rows, herd_rows, milk_price, catalogue_rows, logged_cost_per_kg, start, end,
):
    """Run the model and the advice rules on rows already loaded. Pure.

    Returns a dict: window, usable_days, effects (models.feed_effects output), costs,
    recent_kg, and decision (suggestions.decide output: kind, advice, nudges, feeds).
    """
    daily, feed_kg = daily_frame(yield_rows, feed_rows, start, end)
    cows = cows_series(herd_rows, daily.index)
    price = float(milk_price) if milk_price is not None else None
    costs = current_cost_per_kg(catalogue_rows, logged_cost_per_kg)
    recent = recent_kg_per_day(feed_kg)

    effects = feed_effects(daily, feed_kg, cows, cost_per_kg=costs, price=price)
    # The most days any one feed could use. With no feed logged at all this is 0, and the
    # nudge says how many days are needed.
    usable = max((e["n_days"] for e in effects), default=0)

    catalogue = {
        c["name"]: {"unit": c["unit"], "kg_per_unit": float(c["kg_per_unit"])} for c in catalogue_rows
    }
    decision = decide(
        effects,
        milk_price=price,
        cost_per_kg=costs,
        recent_kg=recent,
        usable_days=usable,
        cows_known=bool(cows.notna().any()),
        catalogue=catalogue,
    )
    return {
        "window": (start, end),
        "usable_days": usable,
        "effects": effects,
        "costs": costs,
        "recent_kg": recent,
        "decision": decision,
    }


def assess_farmer(farmer_id, today=None):
    """Load one farmer's data from Postgres and assess it as of `today`."""
    today = today or date.today()
    start, end = window(today)
    return assess_rows(
        db.daily_yield(farmer_id, start, end),
        db.daily_feed(farmer_id, start, end),
        db.herd_history(farmer_id),
        db.get_milk_price(farmer_id),
        db.list_catalogue(farmer_id),
        db.feed_cost_per_kg(farmer_id, start, end),
        start,
        end,
    )


def describe(result):
    """Plain-text summary of an assessment, for running by hand."""
    start, end = result["window"]
    d = result["decision"]
    lines = [f"Window {start} to {end}; {result['usable_days']} usable day(s).", f"Decision: {d['kind']}"]
    if d["advice"]:
        a = d["advice"]
        size = f"{a['step_units']:g} {a['unit']}" if a.get("step_units") else f"{a['step_kg']:.1f} kg"
        lines.append(
            f"  {a['verdict']} {a['feed']} by about {size} a day (10% of {a['recent_kg']:.1f} kg), "
            f"worth at least KES {a['gain_per_day_at_least']:.0f} a day"
        )
    for n in d["nudges"]:
        lines.append(f"  nudge: {n['text']}")
    for a in d["feeds"]:
        lines.append(f"  - {a['feed']}: {a['verdict']}" + (f" ({a['reason']})" if a["reason"] else ""))
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        sys.exit("usage: python -m src.loader FARMER_ID")
    print(describe(assess_farmer(int(sys.argv[1]))))
