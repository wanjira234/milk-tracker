"""Feed budget: this month against budget, projection to month-end, next month."""
from datetime import date

import streamlit as st

from src import db
from src.budget import (
    budget_status,
    next_month_estimate,
    next_month_start,
    prev_month_start,
    project_month_spend,
)
from src.ui import farmer_selector

st.set_page_config(page_title="Budget", page_icon="🥛", layout="centered")
st.title("Feed budget")


def kes(amount):
    return f"-KES {abs(amount):,.0f}" if amount < 0 else f"KES {amount:,.0f}"


farmer_id = farmer_selector()
today = date.today()
this_month = db.month_start(today)
next_month = next_month_start(today)

history = db.monthly_feed_spend(farmer_id, today, months=6)
by_month = {r["month"]: r for r in history}
current = by_month.get(this_month)
spent = float(current["spent"]) if current else 0.0
previous = by_month.get(prev_month_start(today))
prev_spent = float(previous["spent"]) if previous else None

# --- this month -------------------------------------------------------------
st.subheader(this_month.strftime("%B %Y"))

stored = db.get_budget(farmer_id, this_month)
budget = float(stored) if stored is not None else None

with st.form("budget_this_month"):
    value = st.number_input(
        "Feed budget (KES)", min_value=0.0, step=500.0, format="%.0f",
        value=budget or 0.0, key=f"budget_{farmer_id}_{this_month}",
    )
    if st.form_submit_button("Save budget", type="primary"):
        if value > 0:
            db.set_budget(farmer_id, this_month, value)
            st.rerun()
        else:
            st.error("Enter a budget above zero.")

projection = project_month_spend(spent, today)
status = budget_status(budget, spent, projection)

c1, c2 = st.columns(2)
c1.metric("Spent so far", kes(spent))
c2.metric("On pace for month-end", kes(projection["projected"]) if projection["reliable"] else "too early")
if status:
    c3, c4 = st.columns(2)
    c3.metric("Budget", kes(budget))
    c4.metric("Remaining", kes(status["remaining"]))
    if status["pct_used"] is not None:
        st.progress(min(status["pct_used"], 1.0), text=f"{status['pct_used']:.0%} of budget used")

    if status["status"] == "over":
        st.error(f"Over budget by {kes(-status['remaining'])}.")
    elif status["status"] == "watch":
        msg = f"On pace to overspend by about {kes(status['projected_overrun'])}."
        if status["daily_allowance"] is not None:
            msg += f" Keeping to {kes(status['daily_allowance'])} a day for the rest of the month stays within budget."
        st.warning(msg)
    else:
        st.success("On track for this month's budget.")
else:
    st.info("Set a budget above to see how this month is going.")

if not projection["reliable"]:
    st.caption("Month-end projections start from day 7, when there's enough spending to judge the pace.")
if current and current["uncosted"]:
    n = current["uncosted"]
    who = "1 feed entry this month has" if n == 1 else f"{n} feed entries this month have"
    st.warning(f"{who} no cost, so spend is understated. Add costs on the feed log page.")

# --- next month -------------------------------------------------------------
st.divider()
st.subheader(next_month.strftime("%B %Y") + " (next month)")

estimate = next_month_estimate(today, spent, prev_spent)
stored_next = db.get_budget(farmer_id, next_month)
if estimate:
    amount, source = estimate
    st.write(f"Estimated feed spend: **{kes(amount)}**, based on {source}.")
else:
    st.caption("No estimate yet: it needs a week of spending this month, or a full previous month.")

suggested = float(stored_next) if stored_next is not None else (round(estimate[0] / 100) * 100 if estimate else 0.0)
with st.form("budget_next_month"):
    value = st.number_input(
        "Feed budget (KES)", min_value=0.0, step=500.0, format="%.0f",
        value=float(suggested), key=f"budget_{farmer_id}_{next_month}",
    )
    if st.form_submit_button("Save next month's budget"):
        if value > 0:
            db.set_budget(farmer_id, next_month, value)
            st.rerun()
        else:
            st.error("Enter a budget above zero.")

# --- history ----------------------------------------------------------------
if history:
    st.divider()
    st.subheader("Recent months")
    rows = [
        {
            "Month": r["month"].strftime("%B %Y"),
            "Feed spend (KES)": float(r["spent"]),
            "Entries": r["entries"],
            "Without cost": r["uncosted"],
        }
        for r in history
    ]
    st.dataframe(rows, hide_index=True, width="stretch")
