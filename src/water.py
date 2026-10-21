"""Water summary for the dashboard. Pure."""


def water_summary(rows, cows=None):
    """rows = [{log_date, litres}] from db.daily_water. Returns None with no rows.

    Average is over the days water was RECORDED, so a day nobody wrote down doesn't read as 'no water'.
    per_cow is litres per cow in milk per day, or None when the herd size is unknown.
    """
    if not rows:
        return None
    litres = [float(r["litres"]) for r in rows]
    avg = sum(litres) / len(litres)
    return {"days": len(litres), "avg_per_day": avg, "per_cow": avg / cows if cows else None}
