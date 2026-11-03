"""Farmer: feed bought, feed left, and when each feed runs out. Works in the farm's own units (a truck,
a bag): record a load when it arrives and tap "finished" when it's gone, and the app learns how long a load lasts."""
from datetime import date, timedelta

import streamlit as st

from src.messages import ICON

from src import db, ledger, stock
from src.auth import require_login
from src.ui import cap, md

st.set_page_config(page_title="Feed stock", page_icon=ICON, layout="centered")
user = require_login(roles=("farmer",))
farmer_id = user["farmer_id"]
today = date.today()

st.title("Feed stock")
items = db.list_catalogue(farmer_id)
if not items:
    st.info("Add your feeds on **Farm setup** first (what a truck, bag or bucket holds, and its price).")
    st.stop()


def attempt(action, done):
    try:
        action()
    except ValueError as e:
        st.error(cap(e))
        return False
    st.success(done)
    return True


def amount(units, unit):
    """'about 1.5 truck' style wording for an amount in the farm's own unit."""
    if units is None:
        return "-"
    if units < 0.05:
        return "none left"
    return f"about {units:,.1f} {unit}"


rows = stock.farm_stock(farmer_id, today)
low = [r for r in rows if r["low"]]
for r in low:
    when = "today" if r["days_left"] < 1 else f"in about {int(r['days_left'])} day{'s' if int(r['days_left']) != 1 else ''}"
    st.warning(f"**{md(r['name'])}** runs out {when} ({md(amount(r['on_hand_units'], r['unit']))} left). Time to restock.")

st.header("What's left")
table = []
for r in rows:
    table.append({
        "Feed": r["name"],
        "Left": amount(r["on_hand_units"], r["unit"]),
        "Use per day": "-" if r["daily_units"] is None else f"{r['daily_units']:,.2f} {r['unit']}",
        "Runs out": "-" if r["runs_out_on"] is None else r["runs_out_on"].strftime("%a %d %b"),
        "Worked out from": r["rate_from"] or ("record a load" if r["on_hand_kg"] is None else "mark a load finished"),
    })
st.dataframe(table, hide_index=True, use_container_width=True)
st.caption("Estimates. Use per day comes from your feed log when you log that feed, otherwise from how long your last "
           "load lasted. Mark a load finished when it runs out, and the estimate gets better each time.")

labels = {i["id"]: f"{i['name']} (per {i['unit']})" for i in items}

st.header("A load arrived")
with st.form("buy", clear_on_submit=True):
    c1, c2 = st.columns(2)
    item_id = c1.selectbox("Feed", list(labels), format_func=labels.get, key="buy_item")
    units = c2.text_input("How many", value="1", help="In your unit: 1 = a full truck or one bag, 0.5 = half", key="buy_units")
    c1, c2 = st.columns(2)
    on = c1.date_input("Arrived on", value=today, max_value=today, key="buy_day")
    price = c2.text_input("Price (KES)", placeholder="blank = your usual price", help="0 if it cost nothing (own land)", key="buy_price")
    supplier = st.text_input("From", placeholder="Who you bought it from", key="buy_from")
    terms = st.radio("Payment", list(ledger.TERMS), format_func=ledger.TERMS.get, horizontal=True, key="buy_terms")
    c1, c2 = st.columns(2)
    due = c1.date_input("Due by (if on credit)", value=today + timedelta(days=ledger.DEFAULT_CREDIT_DAYS), key="buy_due")
    method = c2.selectbox("Paid by (if paid now)", list(ledger.METHODS), format_func=ledger.METHODS.get, key="buy_method")
    if st.form_submit_button("Save the load", type="primary"):
        if attempt(lambda: stock.record_purchase(user, farmer_id, item_id, units, on, supplier=supplier, price=price, terms=terms,
                                                 due_on=due if terms == "credit" else None,
                                                 method=method if terms == "paid" else None), "Saved. It also shows on Money."):
            st.rerun()

st.header("A load finished, or check what's left")
with st.form("count", clear_on_submit=True):
    c1, c2 = st.columns(2)
    item_id = c1.selectbox("Feed", list(labels), format_func=labels.get, key="count_item")
    on = c2.date_input("On", value=today, max_value=today, key="count_day")
    left = st.text_input("How much is left", value="0", help="0 = finished. In your unit: 0.5 = about half a truck", key="count_left")
    if st.form_submit_button("Save"):
        if attempt(lambda: stock.record_count(user, farmer_id, item_id, on, left), "Saved."):
            st.rerun()

with st.expander("Warn me earlier or later"):
    st.caption("How many days before a feed runs out you want the warning: about the time it takes to restock.")
    lead_item = st.selectbox("Feed", list(labels), format_func=labels.get, key="lead_item")
    current = next(i for i in items if i["id"] == lead_item)["lead_days"]
    with st.form("lead"):
        days = st.number_input("Days before", min_value=0, max_value=60, value=int(current), step=1, key=f"lead_days_{lead_item}")
        if st.form_submit_button("Save"):
            if attempt(lambda: stock.set_warning_days(user, farmer_id, lead_item, days), "Saved."):
                st.rerun()

st.header("Loads this month")
mine = [p for p in db.feed_purchases(farmer_id, today.replace(day=1))]
if not mine:
    st.caption("None recorded this month.")
else:
    st.dataframe([{"Arrived": p["purchased_on"], "Feed": p["feed"], "How many": f"{float(p['units']):g} {p['unit']}",
                   "KES": round(float(p["cost_kes"] or 0))} for p in mine], hide_index=True, use_container_width=True)
