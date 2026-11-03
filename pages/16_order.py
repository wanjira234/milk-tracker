"""Farmer: pre-order from the agrovets you buy from, so the goods are ready when you arrive (or delivered)."""
from datetime import date, timedelta

import streamlit as st

from src.messages import ICON

from src import db, orders
from src.auth import require_login
from src.ui import cap, md

st.set_page_config(page_title="Order", page_icon=ICON, layout="centered")
user = require_login(roles=("farmer",))
farmer_id = user["farmer_id"]
today = date.today()

st.title("Order from an agrovet")

low = orders.suggested_lines(farmer_id, today)
if low:
    st.warning("Running low: " + ", ".join(f"**{md(name)}**" + (f" (about {int(d)} days left)" if d is not None else "")
                                           for _, name, d in low) + ". Order it below.")

shops = db.farm_agrovets(farmer_id)
if shops:
    names = {a["id"]: a["name"] for a in shops}
    shop_id = st.selectbox("Agrovet", list(names), format_func=names.get, key="order_shop")
    products = db.list_products(shop_id)
    feeds = db.list_catalogue(farmer_id)
    feed_names = {None: "(not one of my feeds)"} | {i["id"]: f"my {i['name']} (per {i['unit']})" for i in feeds}
    low_ids = {fid for fid, _, _ in low}
    if not products:
        st.info("This agrovet has not listed any products yet.")
    else:
        with st.form("order", clear_on_submit=True):
            st.caption("How many of each. Tie a product to one of your feeds and, once collected, Feed stock updates itself. "
                       "One product unit = one unit of your feed, so tie a bag to a feed counted in bags.")
            picks = []
            for p in products:
                c1, c2 = st.columns([2, 3])
                qty = c1.number_input(f"{p['name']} · {p['unit']} · KES {float(p['price_kes']):,.0f}", min_value=0.0, max_value=1000.0,
                                      step=1.0, value=0.0, key=f"qty_{p['id']}")
                guess = next((i["id"] for i in feeds if i["name"].lower() in p["name"].lower()), None)
                ids = list(feed_names)
                feed = c2.selectbox("For", ids, index=ids.index(guess) if guess in ids else 0, format_func=feed_names.get,
                                    key=f"feed_{p['id']}")
                if guess in low_ids and feed == guess:
                    c2.caption("Running low")
                picks.append((p["id"], qty, feed))
            c1, c2 = st.columns(2)
            when = c1.date_input("Wanted by", value=today + timedelta(days=1), min_value=today,
                                 max_value=today + timedelta(days=orders.HORIZON_DAYS), key="order_day")
            how = c2.radio("How", list(orders.FULFILMENT), format_func=orders.FULFILMENT.get, key="order_how")
            note = st.text_input("Note for the agrovet (optional)", max_chars=orders.MAX_NOTE, key="order_note")
            if st.form_submit_button("Send order", type="primary"):
                try:
                    orders.place_order(user, farmer_id, shop_id, [(pid, q if q else "", f) for pid, q, f in picks], when, how, note)
                except ValueError as e:
                    st.error(cap(e))
                else:
                    st.success("Sent. You'll see here when the agrovet confirms it.")
                    st.rerun()
else:
    st.info("Add the agrovet you buy from below. Then you can order ahead and skip the queue.")

st.header("My orders")
mine = db.orders_for_farm(farmer_id)
if not mine:
    st.caption("No orders yet.")
for o in mine:
    lines = db.order_lines(o["id"])
    with st.container(border=True):
        when = o["ready_on"] or o["wanted_on"]
        st.markdown(f"**{md(o['agrovet_name'])}** · {orders.STATUS_WORDS[o['status']]}"
                    + (f" · ready {when}" if o["status"] == "confirmed" else f" · wanted {o['wanted_on']}" if o["status"] == "requested" else "")
                    + f" · {orders.FULFILMENT[o['fulfilment']].lower()}")
        for ln in lines:
            price = f" · KES {float(ln['qty']) * float(ln['unit_price_kes']):,.0f}" if ln["unit_price_kes"] is not None else ""
            st.write(f"- {float(ln['qty']):g} × {md(ln['product_name'])} ({md(ln['unit'])}){price}")
        if o["status"] in ("confirmed", "collected"):
            st.caption(f"Total KES {float(orders.order_total(lines)):,.0f}")
        if o["agrovet_note"]:
            st.caption(f"From the agrovet: {md(o['agrovet_note'])}")
        if o["status"] in ("requested", "confirmed") and st.button("Cancel order", key=f"cancel_order_{o['id']}"):
            try:
                orders.cancel_order(user, o["id"])
            except ValueError as e:
                st.error(cap(e))
            else:
                st.rerun()

st.header("My agrovets")
for a in shops:
    c1, c2 = st.columns([4, 1])
    c1.write(md(a["name"]))
    if c2.button("Remove", key=f"drop_shop_{a['id']}"):
        db.remove_farm_agrovet(farmer_id, a["id"])
        st.rerun()
with st.form("add_shop", clear_on_submit=True):
    phone = st.text_input("Agrovet's phone number", placeholder="0712 345 678", key="shop_phone",
                          help="They need a Maziwa Plus agrovet login. They see only the orders you send them.")
    if st.form_submit_button("Add agrovet"):
        try:
            orders.add_own_agrovet(farmer_id, phone)
        except ValueError as e:
            st.error(cap(e))
        else:
            st.success("Added. You can now order from this agrovet.")
            st.rerun()
