"""Agrovet: farmers' orders arriving from Maziwa (what, when, pickup or delivery, how they pay), hand-overs, the
catalogue farmers see (synced from the shop's own system, uploaded, or typed), opening hours, offers and the shop details."""
from datetime import date, time, timedelta, timezone

import streamlit as st

from src.messages import ICON

from src import bridges, catalogue, db, hours, orders
from src.auth import require_login
from src.ui import cap, md

st.set_page_config(page_title="Orders", page_icon=ICON, layout="centered")
user = require_login(roles=("agrovet",))
today = date.today()
NAIROBI = timezone(timedelta(hours=3))
me = db.shop(user["id"]) or {}
my_hours = db.shop_hours(user["id"])
minutes = hours.slot_minutes(me)


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


def show_lines(lines, priced):
    for ln in lines:
        price = f" · {kes(float(ln['qty']) * float(ln['unit_price_kes']))}" if priced and ln["unit_price_kes"] is not None else ""
        st.write(f"- {float(ln['qty']):g} × {md(ln['product_name'])} ({md(ln['unit'])}){price}")


def farm_title(o):
    return (f"**{md(o['farm_name'] or o['farmer_name'])}**" + (f" · route {md(o['route_code'])}" if o["route_code"] else "")
            + f" · {orders.FULFILMENT_SHOP[o['fulfilment']]} · {orders.PAYMENT_SHOP[o['payment_method']]}")


def when(day, t):
    return f"{day:%a %d %b}" + (f", {hours.label(t, minutes)}" if t else "")


st.title("Orders")
waiting = db.orders_for_agrovet(user["id"], ("requested",))
confirmed = db.orders_for_agrovet(user["id"], ("confirmed",))
to_check = [o for o in confirmed if o["payment_status"] == "reported"]
c1, c2, c3 = st.columns(3)
c1.metric("New orders", len(waiting))
c2.metric("Payments to check", len(to_check))
c3.metric("Ready today", sum(1 for o in confirmed if o["ready_on"] == today))
if not me.get("town") or not me.get("pay_number"):
    st.warning("Finish **My shop** (last tab): your town so nearby farmers find you, and your till so they can pay by M-Pesa.")
if not my_hours:
    st.info("Set your **Hours** so farmers can choose a pickup or delivery time you can serve.")

t_new, t_ready, t_products, t_hours, t_sales, t_shop = st.tabs(["New orders", "To hand over", "Catalogue & offers", "Hours",
                                                                "Sales", "My shop"])

with t_new:
    if not waiting:
        st.caption("No new orders.")
    for o in waiting:
        lines = db.order_lines(o["id"])
        with st.container(border=True):
            st.markdown(farm_title(o))
            st.markdown(f"Wants it **{when(o['wanted_on'], o['wanted_time'])}**")
            if o["farmer_phone"]:
                st.caption(o["farmer_phone"])
            show_lines(lines, priced=False)
            if o["notes"]:
                st.caption(f"Note: {md(o['notes'])}")
            with st.form(f"confirm_{o['id']}"):
                c1, c2 = st.columns(2)
                ready = c1.date_input("Ready on", value=max(o["wanted_on"], today), min_value=today,
                                      max_value=today + timedelta(days=orders.HORIZON_DAYS), key=f"ready_{o['id']}")
                at = c2.time_input("Time", value=o["wanted_time"], step=minutes * 60, key=f"rtime_{o['id']}")
                note = st.text_input("Note to the farmer (optional)", key=f"cnote_{o['id']}")
                if st.form_submit_button("Confirm at today's prices", type="primary"):
                    if attempt(lambda o=o, r=ready, t=at, n=note: orders.confirm_order(user, o["id"], r, n, ready_time=t),
                               "Confirmed. The farmer now sees the total" + (" and where to pay." if o["payment_method"] == "mpesa" else ".")):
                        st.rerun()
            with st.expander("Can't do it?"):
                with st.form(f"decline_{o['id']}"):
                    why = st.text_input("Why (the farmer sees this)", placeholder="Out of stock until Monday", key=f"why_{o['id']}")
                    if st.form_submit_button("Decline order"):
                        if attempt(lambda o=o, w=why: orders.decline_order(user, o["id"], w), "Declined."):
                            st.rerun()

with t_ready:
    day = st.date_input("Ready on", value=today, key="round_day")
    r = orders.rounds(user, day)
    later = [o for o in confirmed if o["ready_on"] != day]

    def hand_over_card(o):
        lines = db.order_lines(o["id"])
        total = orders.order_total(lines)
        with st.container(border=True):
            st.markdown(farm_title(o) + (f" · **{hours.label(o['ready_time'], minutes)}**" if o["ready_time"] else ""))
            if o["farmer_phone"]:
                st.caption(o["farmer_phone"])
            show_lines(lines, priced=True)
            st.markdown(f"**Total {kes(total)}**")
            if o["payment_method"] == "mpesa":
                if o["payment_status"] == "received":
                    st.success(f"M-Pesa received ({o['mpesa_code']}).")
                else:
                    if o["payment_status"] == "reported":
                        st.info(f"The farmer says they paid. Code **{o['mpesa_code']}**: check it in your M-Pesa messages.")
                    else:
                        st.caption("Not paid yet. If the farmer paid without entering the code, enter it from your messages.")
                    with st.form(f"recv_{o['id']}"):
                        code = "" if o["payment_status"] == "reported" else st.text_input("M-Pesa code", key=f"rcode_{o['id']}")
                        if st.form_submit_button("Payment received", type="primary"):
                            if attempt(lambda o=o, c=code: orders.confirm_payment(user, o["id"], c), "Payment confirmed."):
                                st.rerun()
                    st.caption("Hand the goods over once the payment is confirmed.")
                    return
            with st.form(f"hand_{o['id']}"):
                cash = st.checkbox(f"I received {kes(total)} in cash", key=f"cash_{o['id']}") if o["payment_method"] == "cash" else False
                if o["payment_method"] == "milk_deduction":
                    st.caption("Comes off the farm's milk payment.")
                if st.form_submit_button("Handed over", type="primary"):
                    if attempt(lambda o=o, c=cash: orders.hand_over(user, o["id"], cash_received=c), "Done. It's on Money and in Sales."):
                        st.rerun()

    if not r["deliveries"] and not r["pickups"]:
        st.caption("Nothing ready on this day.")
    for route, group in r["deliveries"].items():
        st.subheader(f"Deliveries · {md(route)} ({len(group)})")
        for o in group:
            hand_over_card(o)
    if r["pickups"]:
        st.subheader(f"Pickups ({len(r['pickups'])})")
        for o in r["pickups"]:
            hand_over_card(o)
    if later:
        st.caption("Also confirmed: " + ", ".join(f"{md(o['farm_name'] or o['farmer_name'])} ({o['ready_on']:%a %d %b})" for o in later))

with t_products:
    st.caption("This is what farmers see on their order page, read-only. Keep it in step with your own system: "
               "connect it, upload your price list, or type products in.")
    source = bridges.title(me.get("bridge_kind"))
    synced = (f", last updated {me['catalogue_synced_at'].astimezone(NAIROBI):%d %b %H:%M}" if me.get("catalogue_synced_at") else "")
    if source:
        c1, c2 = st.columns([3, 1])
        c1.success(f"Connected to **{md(source)}**{synced}. Prices and stock come from there.")
        if c2.button("Sync now", key="sync_catalogue"):
            try:
                n, off, problems = bridges.sync(user)
                st.success(f"{n} products updated" + (f", {off} taken off" if off else "") + ".")
                for msg in problems:
                    st.caption(cap(msg))
            except ValueError as e:
                st.error(cap(e))
    if not source:
        with st.expander("Upload your price list (CSV or Excel)", expanded=not db.list_products(user["id"])):
            st.caption("Export it from your POS or stock system. Columns: product and price (needed), unit, quantity in stock "
                       "and item code (optional). Out-of-stock items show to farmers as out of stock.")
            with st.form("upload_list", clear_on_submit=True):
                f = st.file_uploader("Price list", type=["csv", "xlsx"], key="price_file")
                replace = st.checkbox("Replace my list (take off anything not in this file)", value=True, key="price_replace")
                if st.form_submit_button("Import") and f is not None:
                    try:
                        n, off, problems = catalogue.upload(user, f.name, f.getvalue(), replace)
                        st.success(f"{n} products imported" + (f", {off} taken off" if off else "") + ".")
                        for msg in problems:
                            st.caption(cap(msg))
                    except ValueError as e:
                        st.error(cap(e))
        with st.expander("Add or change one product by hand"):
            with st.form("product", clear_on_submit=True):
                c1, c2, c3 = st.columns([3, 2, 2])
                name = c1.text_input("Product", placeholder="Dairy meal", key="p_name")
                unit = c2.text_input("Sold per", placeholder="70 kg bag", key="p_unit",
                                     help="Include the kg when you can (70 kg bag): the farmer's feed stock then updates exactly.")
                price = c3.text_input("Price (KES)", key="p_price")
                if st.form_submit_button("Add or update"):
                    if attempt(lambda: orders.record_product(user, name, unit, price), "Saved."):
                        st.rerun()
    mine = db.list_products(user["id"])
    rows = [{"Product": p["name"], "Sold per": p["unit"], "Price (KES)": float(p["price_kes"]), "In stock": p["in_stock"]} for p in mine]
    if mine and source:
        st.dataframe(rows, hide_index=True, use_container_width=True)
        st.caption("Change prices and stock in your own system, then Sync now.")
    elif mine:
        with st.form("stock"):
            edited = st.data_editor(rows, hide_index=True, use_container_width=True, disabled=["Product", "Sold per", "Price (KES)"],
                                    key="stock_table")
            if st.form_submit_button("Save stock"):
                for p, row in zip(mine, edited):
                    if bool(row["In stock"]) != p["in_stock"]:
                        orders.set_in_stock(user, p["id"], row["In stock"])
                st.rerun()
        with st.expander("Stop selling a product"):
            with st.form("retire_product"):
                drop = st.selectbox("Product", [p["id"] for p in mine], format_func={p["id"]: p["name"] for p in mine}.get,
                                    index=None, placeholder="Choose a product", key="p_drop")
                if st.form_submit_button("Remove") and drop is not None:
                    db.retire_product(user["id"], drop)
                    st.rerun()
    if mine:
        st.subheader("Offers")
        st.caption("A percentage off one product for a few days. Farmers see it on their order page.")
        with st.form("promo", clear_on_submit=True):
            c1, c2 = st.columns([3, 1])
            pid = c1.selectbox("Product", [p["id"] for p in mine], format_func={p["id"]: p["name"] for p in mine}.get, key="promo_p")
            pct = c2.number_input("% off", min_value=1, max_value=orders.MAX_PERCENT, value=10, step=1, key="promo_pct")
            c1, c2 = st.columns(2)
            start = c1.date_input("From", value=today, min_value=today, key="promo_from")
            end = c2.date_input("Until", value=today + timedelta(days=7), min_value=today, key="promo_to")
            if st.form_submit_button("Start offer"):
                if attempt(lambda: orders.add_promotion(user, pid, pct, start, end), "Offer saved."):
                    st.rerun()
        for pr in db.promotions_for(user["id"], today):
            c1, c2 = st.columns([4, 1])
            c1.write(f"{md(pr['product_name'])}: {pr['percent_off']}% off, {pr['starts_on']:%d %b} to {pr['ends_on']:%d %b}")
            if c2.button("End", key=f"end_promo_{pr['id']}"):
                orders.end_promotion(user, pr["id"])
                st.rerun()
    else:
        st.info("Upload your price list or add a product above. Farmers can order once you have one.")
    if source:
        sent = [m for m in db.outbox_for(user["id"]) if m["channel"] == "pos"]
        if sent:
            st.subheader("Sent to your system")
            st.dataframe([{"When": f"{m['created_at'].astimezone(NAIROBI):%d %b %H:%M}", "Order": m["order_id"], "Event": m["event"],
                           "Your ref": m["external_ref"] or "-", "Status": m["status"]} for m in sent],
                         hide_index=True, use_container_width=True)

with t_hours:
    st.caption("Farmers choose a pickup or delivery time from these. Delivery days are when your rounds go out.")
    rows = [{"weekday": wd, "Day": hours.DAYS[wd], "Open": wd in my_hours if my_hours else wd < 6,
             "Opens": my_hours[wd]["opens"] if wd in my_hours else time(8, 0),
             "Closes": my_hours[wd]["closes"] if wd in my_hours else time(18, 0),
             "Delivers": my_hours[wd]["delivers"] if wd in my_hours else False} for wd in range(7)]
    with st.form("hours"):
        edited = st.data_editor(rows, hide_index=True, use_container_width=True, disabled=["Day"], key="hours_table",
                                column_order=["Day", "Open", "Opens", "Closes", "Delivers"],
                                column_config={"Opens": st.column_config.TimeColumn(format="HH:mm", step=1800),
                                               "Closes": st.column_config.TimeColumn(format="HH:mm", step=1800)})
        slot = st.radio("Pickup slots", hours.SLOT_CHOICES, index=hours.SLOT_CHOICES.index(minutes), horizontal=True,
                        format_func=lambda m: f"every {m} minutes" if m < 60 else f"every {m // 60} hour" + ("s" if m > 60 else ""),
                        key="slot_minutes")
        if st.form_submit_button("Save hours", type="primary"):
            data = [{"weekday": r["weekday"], "open": r["Open"], "opens": r["Opens"], "closes": r["Closes"], "delivers": r["Delivers"]}
                    for r in edited]
            if attempt(lambda: orders.set_hours(user, data, slot), "Saved."):
                st.rerun()
    if my_hours:
        st.caption(f"Farmers see: open {hours.summary(my_hours)}")

with t_sales:
    s = orders.sales(user, today)
    c1, c2, c3 = st.columns(3)
    c1.metric("Sold, last 30 days", kes(s["kes"]))
    c2.metric("Customers", len(s["customers"]))
    c3.metric("Came back 2+ times", s["repeat"])
    st.subheader("Best sellers")
    if s["products"]:
        st.dataframe([{"Product": r["product_name"], "Sold": f"{float(r['qty']):g} {r['unit']}", "KES": round(float(r["kes"])),
                       "Orders": r["orders"]} for r in s["products"]], hide_index=True, use_container_width=True)
    else:
        st.caption("Nothing collected in the last 30 days yet.")
    if s["slow"]:
        st.subheader("Not selling")
        st.write(", ".join(md(p["name"]) for p in s["slow"]))
        st.caption("No orders in 30 days. An offer on the Products & offers tab can move them.")
    st.subheader("Best customers")
    if s["customers"]:
        st.dataframe([{"Farm": c["farm"], "Orders collected": c["orders"], "Spent (KES)": round(float(c["billed_kes"])),
                       "Last collected": c["last_collected"] or "-"} for c in s["customers"]], hide_index=True, use_container_width=True)
        st.caption("Your regulars are at the top: a good list to thank with an offer.")
    else:
        st.caption("Farms appear here once they order from you.")

with t_shop:
    st.caption("Farmers see your town and pay you directly by M-Pesa. Maziwa Plus never holds the money.")
    with st.form("shop"):
        town = st.text_input("Town or area", value=me.get("town") or "", placeholder="Limuru", key="shop_town")
        kinds = list(orders.PAY_KINDS)
        kind = st.radio("M-Pesa", kinds, index=kinds.index(me["pay_kind"]) if me.get("pay_kind") in kinds else 0,
                        format_func=orders.PAY_KINDS.get, horizontal=True, key="shop_kind")
        c1, c2 = st.columns(2)
        number = c1.text_input("Till or paybill number", value=me.get("pay_number") or "", key="shop_number")
        account = c2.text_input("Paybill account (if paybill)", value=me.get("pay_account") or "", key="shop_account",
                                help="Leave blank and farmers use their farm name as the account.")
        if st.form_submit_button("Save", type="primary"):
            if attempt(lambda: orders.set_shop(user, town, kind, number, account), "Saved."):
                st.rerun()
