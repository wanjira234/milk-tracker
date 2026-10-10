"""Turn model output into a decision. Pure functions: no Streamlit, no database, no SMS.

Rules agreed with the owner (CONTEXT.md, 2026-10-09):
  - Not enough data: a data nudge saying what is missing. Never feed advice, never generic tips.
  - One suggestion changes one feed by at most MAX_STEP (10%).
  - Advice optimises feed margin: milk price x extra litres, minus feed cost.
  - Strict evidence bar: enforced upstream, by models.feed_effects (status == "clear").

A feed is only recommended when even the pessimistic end of its estimate pays, so a lucky
reading never produces advice. At most one feed is recommended at a time, which also keeps
the next round of data attributable to that one change.
"""
import math

from src.models import MIN_COMPLETE_DAYS

MAX_STEP = 0.10


def current_cost_per_kg(catalogue_rows=(), logged_cost_per_kg=None):
    """KES per kg for each feed. Today's catalogue price wins over the average of past entries,
    because advice is about what the next kilogram costs, not what the last one did."""
    costs = {}
    for name, value in (logged_cost_per_kg or {}).items():
        if value is not None:
            costs[name] = float(value)
    for item in catalogue_rows:
        kg = float(item["kg_per_unit"])
        if kg > 0:
            costs[item["name"]] = float(item["kes_per_unit"]) / kg
    return costs


def _nudges(usable_days, cows_known, milk_price, assessed):
    """What is missing, most important first. Each is one thing the farmer can fix."""
    out = []
    if not cows_known:
        out.append({"code": "no_cows", "text": "tell the app how many cows are in milk"})
    if milk_price is None:
        out.append({"code": "no_price", "text": "set the milk price per litre"})
    if usable_days < MIN_COMPLETE_DAYS:
        need = MIN_COMPLETE_DAYS - usable_days
        out.append({
            "code": "few_days", "days_needed": need,
            "text": f"{need} more day(s) with all 3 milkings and the feed logged",
        })
    for a in assessed:
        if a["verdict"] == "needs_cost":
            out.append({"code": "no_cost", "feed": a["feed"], "text": f"add the price of {a['feed']}"})
    return out


def _step_units(step_kg, item):
    """The step in the farm's own units, to the nearest half unit; None if it would round to zero."""
    if not item or not item.get("kg_per_unit"):
        return None
    units = round(step_kg / float(item["kg_per_unit"]) * 2) / 2
    return units if units > 0 else None


def decide(effects, *, milk_price, cost_per_kg, recent_kg, usable_days, cows_known, catalogue=None):
    """Decide what, if anything, to tell the farmer.

    effects     models.feed_effects output
    milk_price  KES per litre, or None
    cost_per_kg {feed: KES per kg} (see current_cost_per_kg)
    recent_kg   {feed: kg per day fed to the herd, recently}
    usable_days days with all milkings, a known herd and feed logged (what the model could use)
    cows_known  whether any cows-in-milk entry exists
    catalogue   {feed: {"unit": ..., "kg_per_unit": ...}}, to express the step in farm units

    Returns {"kind": "advice" | "nudge" | "none", "advice", "nudges", "feeds"}.
    `feeds` lists every feed with its verdict and reason, for the dashboard.
    """
    catalogue = catalogue or {}
    assessed = []
    for e in effects:
        a = {"feed": e["feed"], "status": e["status"], "verdict": None, "reason": None}
        assessed.append(a)
        if e["status"] != "clear":
            a["verdict"] = "no_evidence"
            a["reason"] = {
                "too_few_days": "not enough days yet",
                "too_few_amounts": "the amount hardly changed, so there is nothing to learn from",
                "moves_with": f"always changes together with {e.get('moves_with')}, so the two can't be told apart",
                "unclear": "an effect on milk can't be ruled out as zero",
            }.get(e["status"], e["status"])
            continue
        cost = cost_per_kg.get(e["feed"])
        if milk_price is None or cost is None:
            a["verdict"], a["reason"] = "needs_cost", "price needed to judge whether it pays"
            continue
        # slope is litres per cow per kg per cow, which equals herd litres per herd kg
        low = e["ci_low"] * milk_price - cost      # KES per extra kg, pessimistic
        high = e["ci_high"] * milk_price - cost    # KES per extra kg, optimistic
        a.update(slope=e["slope"], margin_low=low, margin_high=high)
        recent = recent_kg.get(e["feed"], 0.0)
        if low > 0:
            a["verdict"] = "increase"
        elif high < 0:
            a["verdict"] = "decrease"
        else:
            a["verdict"], a["reason"] = "hold", "it affects milk, but it isn't clear that it pays"
        if a["verdict"] in ("increase", "decrease"):
            if not recent or recent <= 0:
                a["verdict"], a["reason"] = "hold", "not fed recently, so there is no amount to change by 10%"
                continue
            step_kg = recent * MAX_STEP
            sign = 1 if a["verdict"] == "increase" else -1
            # margin change per day = sign x step x margin per kg; report the worst case of the range
            worst = min(sign * step_kg * low, sign * step_kg * high)
            a.update(
                step_kg=step_kg, recent_kg=recent,
                step_units=_step_units(step_kg, catalogue.get(e["feed"])),
                unit=(catalogue.get(e["feed"]) or {}).get("unit"),
                gain_per_day_at_least=worst,
            )

    candidates = [a for a in assessed if a["verdict"] in ("increase", "decrease")]
    nudges = _nudges(usable_days, cows_known, milk_price, assessed)
    if candidates and not any(n["code"] in ("no_cows", "no_price") for n in nudges):
        best = max(candidates, key=lambda a: a["gain_per_day_at_least"])
        return {"kind": "advice", "advice": best, "nudges": nudges, "feeds": assessed}
    if nudges:
        return {"kind": "nudge", "advice": None, "nudges": nudges, "feeds": assessed}
    return {"kind": "none", "advice": None, "nudges": [], "feeds": assessed}
