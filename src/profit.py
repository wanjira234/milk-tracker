"""Profit in plain words: milk income minus feed cost. Pure, no Streamlit or database.

This is FEED margin, not full profit: labour, vet, water, and rent are not recorded, and
the app says so wherever it shows the number. Only complete days (all milkings recorded)
count, for income AND for feed cost, so the two cover the same days and a missed entry
doesn't make a day look like a loss or a win.
"""


def profit_summary(daily, milk_price, uncosted=0):
    """`daily` is trends.daily_frame's first table. Returns a dict, or None with no complete days.

    uncosted = feed entries with no price: their cost is missing from the total, so the
    profit shown is an upper limit, and the page says so.
    """
    if milk_price is None:
        return None
    done = daily[daily["complete"]]
    days = len(done)
    if days == 0:
        return None
    litres = float(done["litres"].sum())
    income = litres * float(milk_price)
    feed_cost = float(done["cost_kes"].sum())
    profit = income - feed_cost
    return {
        "days": days,
        "litres": litres,
        "income": income,
        "feed_cost": feed_cost,
        "profit": profit,
        "profit_per_day": profit / days,
        "profit_per_litre": profit / litres if litres else None,
        "feed_per_100": feed_cost / income * 100 if income else None,  # KES of feed per KES 100 of milk
        "uncosted": int(uncosted),
    }
