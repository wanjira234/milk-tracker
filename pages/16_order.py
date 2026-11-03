"""Farmer: order ahead from an agrovet, see when it's confirmed and what it costs, pay, and collect."""
from datetime import date, timedelta

import streamlit as st

from src.messages import ICON

from src import bridges, db, hours, orders
from src.auth import require_login
from src.ui import cap, md

st.set_page_config(page_title="Order", page_icon=ICON, layout="centered")
user = require_login(roles=("farmer",))
farmer_id = user["farmer_id"]
today = date.today()


def attempt(action, done):
    try:
        action()
    except ValueError as e:
        st.error(cap(e))
        return False
    st.success(done)
    return True


def kes(x):
    return f"KES {float(x):,.0f}"


st.title("Order from an agrovet")
st.caption("Order ahead and your goods are ready when you arrive, or delivered to the farm.")

low = orders.suggested_feeds(farmer_id, today)
if low:
    st.warning("Running low: " + ", ".join(f"**{md(name)}**" + (f" (about {int(d)} days left)" if d is not None else "")
                                           for _, name, d in low))

new_order, my_orders = st.tabs(["New order", "My orders"])

with new_order:
    farm = db.get_farmer(farmer_id)
    shops = orders.shops_for(farmer_id)
    if not farm.get("town"):
        with st.form("my_town"):
            town = st.text_input("Your town or area", placeholder="Limuru", key="farm_town",
                                 help="So the agrovets nearest you are listed first.")
            if st.form_submit_button("Save"):
                db.set_farm_town(farmer_id, " ".join(town.split())[:60] or None)
                st.rerun()
    if not shops:
        st.info("No agrovet has listed its products yet. Once one does, it appears here.")
    else:
        def shop_label(s):
            near = farm.get("town") and (s["town"] or "").lower() == farm["town"].lower()
            return f"{s['name']} · {s['town'] or 'town not given'}" + (" · near you" if near else "")

        by_id = {s["id"]: s for s in shops}
        shop_id = st.selectbox("Agrovet", list(by_id), format_func=lambda i: shop_label(by_id[i]), key="order_shop")
        shop = by_id[shop_id]
        shop_hours = db.shop_hours(shop_id)
        minutes = hours.slot_minutes(shop)
        source = bridges.title(shop.get("bridge_kind"))
        st.caption(f"Open {hours.summary(shop_hours)}" + (f" · prices and stock from {md(source)}" if source else ""))
        products = db.list_products(shop_id)
        promos = db.promotions_for(shop_id, today)
        feeds = db.list_catalogue(farmer_id)
        low_names = {name.lower() for _, name, _ in low}

        def rank(p):  # in stock first, then what's running low, then the farm's own feeds, then the rest
            feed, _ = orders.match_feed(p, feeds)
            return (not p["in_stock"], not (feed and feed["name"].lower() in low_names), feed is None, p["name"])

        # when: outside the form, so the times follow the day and pickup/delivery as the farmer changes them
        how = st.radio("Collection", list(orders.FULFILMENT), format_func=orders.FULFILMENT.get, horizontal=True, key="order_how")
        choices = orders.available(shop, how, today)
        when = when_time = None
        if not choices:
            st.warning("This shop has no delivery days set. Choose pickup, or ask the shop." if how == "delivery"
                       else "This shop has no open days in the next two weeks.")
        elif not shop_hours:
            when = st.date_input("Wanted on", value=today + timedelta(days=1), min_value=today,
                                 max_value=today + timedelta(days=hours.HORIZON_DAYS), key="order_day")
            st.caption("This shop hasn't set its hours yet: it will tell you the time when it confirms.")
        else:
            by_day = dict(choices)
            c1, c2 = st.columns(2)
            when = c1.selectbox("Day", list(by_day), format_func=lambda d: "Today" if d == today else
                                ("Tomorrow" if d == today + timedelta(days=1) else f"{d:%a %d %b}"), key="order_day")
            when_time = c2.selectbox("Time", by_day[when], format_func=lambda t: hours.label(t, minutes), key="order_time")

        with st.form("order", clear_on_submit=True):
            st.markdown("**How many of each?**")
            picks = []
            for p in sorted(products, key=rank):
                price, promo = orders.price_today(p, promos, today)
                feed, _ = orders.match_feed(p, feeds)
                c1, c2 = st.columns([3, 1])
                text = md(f"{p['name']} · {p['unit']} · ") + (f"~~{kes(p['price_kes'])}~~ **{kes(price)}** "
                                                               f"({promo['percent_off']}% off until {promo['ends_on']:%d %b})"
                                                               if promo else kes(price))
                if not p["in_stock"]:
                    c1.markdown(f":gray[{text} · out of stock]")
                    continue
                c1.markdown(text + (f"  \n:green[Adds to your {md(feed['name'])} stock]" if feed else ""))
                qty = c2.number_input("How many", min_value=0, max_value=1000, step=1, value=0, key=f"qty_{p['id']}",
                                      label_visibility="collapsed")
                picks.append((p["id"], qty))
            options = orders.payment_options(farmer_id, shop)
            pay = st.radio("How you'll pay", options, format_func=orders.PAYMENT.get, horizontal=True, key="order_pay")
            if "mpesa" not in options:
                st.caption("This shop hasn't added its M-Pesa number yet, so pay in cash when you collect.")
            note = st.text_input("Note for the agrovet (optional)", max_chars=orders.MAX_NOTE, key="order_note")
            if st.form_submit_button("Send order", type="primary", disabled=when is None):
                if attempt(lambda: orders.place_order(user, farmer_id, shop_id, picks, when, how, pay, note, wanted_time=when_time),
                           "Sent to the shop. It will confirm the order and the total; see My orders."):
                    st.rerun()

with my_orders:
    mine = db.orders_for_farm(farmer_id)
    if not mine:
        st.caption("No orders yet.")
    for o in mine:
        lines = db.order_lines(o["id"])
        total = orders.order_total(lines)
        shop = db.shop(o["agrovet_user_id"]) if o["agrovet_user_id"] else None
        with st.container(border=True):
            st.markdown(f"**{md(o['agrovet_name'])}** · {orders.STATUS_WORDS[o['status']]}")
            for ln in lines:
                price = f" · {kes(float(ln['qty']) * float(ln['unit_price_kes']))}" if ln["unit_price_kes"] is not None else ""
                st.write(f"- {float(ln['qty']):g} × {md(ln['product_name'])} ({md(ln['unit'])}){price}")
            facts = [orders.FULFILMENT[o["fulfilment"]], orders.PAYMENT[o["payment_method"]]]
            if o["status"] == "requested":
                facts.append(f"asked for {o['wanted_on']:%a %d %b}" + (f" {o['wanted_time']:%H:%M}" if o["wanted_time"] else ""))
            if o["status"] == "confirmed":
                facts.append(f"ready {o['ready_on']:%a %d %b}" + (f" {o['ready_time']:%H:%M}" if o["ready_time"] else ""))
            st.caption(" · ".join(facts))
            if o["agrovet_note"]:
                st.caption(f"From the agrovet: {md(o['agrovet_note'])}")
            if o["status"] == "confirmed":
                st.markdown(f"**Total {kes(total)}**")
                if o["payment_method"] == "mpesa":
                    if o["payment_status"] == "received":
                        st.success(f"Paid. The shop confirmed your M-Pesa payment ({o['mpesa_code']}).")
                    elif o["payment_status"] == "reported":
                        st.info(f"You sent code {o['mpesa_code']}. Waiting for the shop to confirm it arrived.")
                    else:
                        where = orders.where_to_pay(shop)
                        st.info(f"Pay **{kes(total)}** by M-Pesa to **{where}** ({md(o['agrovet_name'])}), then enter the code "
                                "from your confirmation SMS." if where else "Ask the shop where to pay by M-Pesa.")
                        with st.form(f"paid_{o['id']}"):
                            code = st.text_input("M-Pesa code", placeholder="SK3ABC12XY", key=f"code_{o['id']}")
                            if st.form_submit_button("I've paid"):
                                if attempt(lambda o=o, c=code: orders.report_payment(user, o["id"], c), "Sent to the shop."):
                                    st.rerun()
                elif o["payment_method"] == "cash":
                    st.caption("Pay in cash when you collect.")
                else:
                    st.caption("Comes off your milk payment at the end of the month.")
            if o["status"] == "collected":
                st.caption(f"Collected {o['collected_on']:%d %b} · {kes(total)}. It's on your Money page.")
            if o["status"] in ("requested", "confirmed") and o["payment_status"] == "unpaid" \
                    and st.button("Cancel order", key=f"cancel_order_{o['id']}"):
                if attempt(lambda o=o: orders.cancel_order(user, o["id"]), "Cancelled."):
                    st.rerun()
