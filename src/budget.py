"""Pure budget maths. No Streamlit, no database."""
import calendar
from datetime import date

MIN_DAYS_FOR_PROJECTION = 7  # earlier in the month, one big feed purchase swings the projection wildly


def days_in_month(d):
    return calendar.monthrange(d.year, d.month)[1]


def next_month_start(d):
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def prev_month_start(d):
    return date(d.year - (d.month == 1), (d.month - 2) % 12 + 1, 1)


def project_month_spend(spent, today):
    """Project month-end feed spend from the pace so far.

    `spent` is feed cost logged from the 1st up to and including `today`.
    `reliable` is False in the first week, when the pace says little.
    """
    elapsed = today.day
    total = days_in_month(today)
    rate = spent / elapsed
    return {
        "projected": rate * total,
        "daily_rate": rate,
        "days_elapsed": elapsed,
        "days_left": total - elapsed,
        "reliable": elapsed >= MIN_DAYS_FOR_PROJECTION,
    }


def budget_status(budget, spent, projection):
    """Compare spend and projection with a budget. Returns None when no budget is set.

    status: 'over'      already past the budget
            'watch'     on pace to pass it (only once the projection is reliable)
            'on_track'  otherwise
    """
    if budget is None:
        return None
    remaining = budget - spent
    if spent > budget:
        status = "over"
    elif projection["reliable"] and projection["projected"] > budget:
        status = "watch"
    else:
        status = "on_track"
    days_left = projection["days_left"]
    return {
        "status": status,
        "remaining": remaining,
        "pct_used": (spent / budget) if budget > 0 else None,
        "projected_overrun": max(0.0, projection["projected"] - budget) if projection["reliable"] else 0.0,
        "daily_allowance": (remaining / days_left) if days_left > 0 and remaining > 0 else None,
    }


def next_month_estimate(today, spent_this_month, prev_month_spend):
    """Estimate next month's feed spend. Returns (amount, source) or None.

    Uses this month's pace once it is reliable, otherwise last month's actual daily
    rate. Returns None when there is nothing to base an estimate on.
    """
    nxt_days = days_in_month(next_month_start(today))
    if today.day >= MIN_DAYS_FOR_PROJECTION and spent_this_month > 0:
        return spent_this_month / today.day * nxt_days, "this month's pace"
    if prev_month_spend:
        prev_days = days_in_month(prev_month_start(today))
        return prev_month_spend / prev_days * nxt_days, "last month's spend"
    return None
