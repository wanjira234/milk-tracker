"""Agrovet: farmers' pre-orders (confirm or decline), what's ready today by delivery round, handing over and
billing, the product list, and the customers who order from you."""
from datetime import date, timedelta

import streamlit as st

from src.messages import ICON

from src import db, ledger, orders
from src.auth import require_login
from src.ui import cap, md

st.set_page_config(page_title="Orders", page_icon=ICON, layout="centered")
user = require_login(roles=("agrovet",))
today = date.today()

st.title("Orders")


def attempt(action, done):
    try:
        action()
    except ValueError as e:
        st.error(cap(e))
        return False
    st.success(done)
    return True


def show_lines(lines, priced):
    for ln in lines:
        price = f" · KES {float(ln['qty']) * float(ln['unit_price_kes']):,.0f}" if priced and ln["unit_price_kes"] is not None else ""
        st.write(f"- {float(ln['qty']):g} × {md(ln['product_name'])} ({md(ln['unit'])}){price}")


def farm_title(o):
    return (f"**{md(o['farm_name'] or o['farmer_name'])}**" + (f" · route {md(o['route_code'])}" if o["route_code"] else "")
            + f" · {orders.FULFILMENT[o['fulfilment']].lower()}")


waiting = db.orders_for_agrovet(user["id"], ("requested",))
c1, c2 = st.columns(2)
c1.metric("New orders", len(waiting))
c2.metric("Ready today", sum(1 for o in db.orders_for_agrovet(user["id"], ("confirmed",)) if o["ready_on"] == today))

st.header("New orders")
if not waiting:
    st.caption("No new orders.")
for o in waiting:
    lines = db.order_lines(o["id"])
    with st.container(border=True):
        st.markdown(farm_title(o) + f" · wanted {o['wanted_on']}")
        if o["farmer_phone"]:
            st.caption(o["farmer_phone"])
        show_lines(lines, priced=False)
        if o["notes"]:
            st.caption(f"Note: {md(o['notes'])}")
        with st.form(f"confirm_{o['id']}"):
            c1, c2 = st.columns(2)
            ready = c1.date_input("Ready on", value=max(o["wanted_on"], today), min_value=today,
                                  max_value=today + timedelta(days=orders.HORIZON_DAYS), key=f"ready_{o['id']}")
            note = c2.text_input("Note to the farmer (optional)", key=f"cnote_{o['id']}")
            if st.form_submit_button("Confirm at today's prices", type="primary"):
                if attempt(lambda o=o, r=ready, n=note: orders.confirm_order(user, o["id"], r, n), "Confirmed."):
                    st.rerun()
        if st.toggle("Can't do it?", key=f"declt_{o['id']}"):
            with st.form(f"decline_{o['id']}"):
                why = st.text_input("Why (the farmer sees this)", placeholder="Out of stock until Monday", key=f"why_{o['id']}")
                if st.form_submit_button("Decline"):
                    if attempt(lambda o=o, w=why: orders.decline_order(user, o["id"], w), "Declined."):
                        st.rerun()

st.header("Ready to hand over")
day = st.date_input("Day", value=today, key="round_day")
r = orders.rounds(user, day)


def hand_over_card(o):
    lines = db.order_lines(o["id"])
    with st.container(border=True):
        st.markdown(farm_title(o))
        if o["farmer_phone"]:
            st.caption(o["farmer_phone"])
        show_lines(lines, priced=True)
        st.caption(f"Total KES {float(orders.order_total(lines)):,.0f}")
        with st.form(f"hand_{o['id']}"):
            terms = st.radio("Payment", ["paid", "credit"], format_func=ledger.TERMS.get, horizontal=True, key=f"hterms_{o['id']}")
            c1, c2 = st.columns(2)
            due = c1.date_input("Due by (if on credit)", value=today + timedelta(days=ledger.DEFAULT_CREDIT_DAYS), key=f"hdue_{o['id']}")
            method = c2.selectbox("Paid by (if paid now)", list(ledger.METHODS), format_func=ledger.METHODS.get, key=f"hmethod_{o['id']}")
            ref = st.text_input("M-Pesa code (optional)", key=f"href_{o['id']}")
            if st.form_submit_button("Handed over", type="primary"):
                if attempt(lambda o=o, t=terms, d=due, m=method, rf=ref:
                           orders.hand_over(user, o["id"], t, due_on=d if t == "credit" else None,
                                            method=m if t == "paid" else None, reference=rf if t == "paid" else None),
                           "Done. The bill is on Money."):
                    st.rerun()


if not r["deliveries"] and not r["pickups"]:
    st.caption("Nothing confirmed for this day.")
for route, group in r["deliveries"].items():
    st.subheader(f"Deliveries · {md(route)} ({len(group)})")
    for o in group:
        hand_over_card(o)
if r["pickups"]:
    st.subheader(f"Pickups ({len(r['pickups'])})")
    for o in r["pickups"]:
        hand_over_card(o)

st.header("My products")
st.caption("Farmers who added your shop order from this list and see these prices. A confirmed order keeps the price it was confirmed at.")
with st.form("product", clear_on_submit=True):
    c1, c2, c3 = st.columns([3, 2, 2])
    name = c1.text_input("Product", placeholder="Dairy meal", key="p_name")
    unit = c2.text_input("Sold per", placeholder="70 kg bag", key="p_unit")
    price = c3.text_input("Price (KES)", key="p_price")
    if st.form_submit_button("Add or update"):
        if attempt(lambda: orders.record_product(user, name, unit, price), "Saved."):
            st.rerun()
mine = db.list_products(user["id"])
if mine:
    st.dataframe([{"Product": p["name"], "Sold per": p["unit"], "Price (KES)": float(p["price_kes"])} for p in mine],
                 hide_index=True, use_container_width=True)
    with st.form("retire_product"):
        drop = st.selectbox("Stop selling", [p["id"] for p in mine], format_func={p["id"]: p["name"] for p in mine}.get,
                            index=None, placeholder="Choose a product", key="p_drop")
        if st.form_submit_button("Remove") and drop is not None:
            db.retire_product(user["id"], drop)
            st.rerun()

st.header("My customers")
customers = db.agrovet_customers(user["id"])
if not customers:
    st.caption("Farms appear here once they order from you.")
else:
    st.dataframe([{"Farm": c["farm"], "Orders collected": c["orders"], "Billed (KES)": round(float(c["billed_kes"])),
                   "Last collected": c["last_collected"] or "-"} for c in customers], hide_index=True, use_container_width=True)
    st.caption("Your best customers are at the top: a good list for loyalty discounts.")
