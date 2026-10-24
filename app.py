"""Milk Tracker: Streamlit entry point (home page)."""
from datetime import date, timedelta

import streamlit as st

from src import accounts, db, services
from src.onboarding import checklist, next_step
from src.ingestion.manual_entry import normalize_phone
from src.ui import cap, farmer_selector
from src.auth import require_login

st.set_page_config(page_title="Milk Tracker", page_icon="🥛", layout="centered")
user = require_login()

first_name = (user.get("name") or "").split()[0] if (user.get("name") or "").split() else ""
st.title(f"Hello, {first_name}" if first_name and user["id"] is not None else "Welcome")
st.caption({"farmer": "Your farm today.", "vet": "Your visits today.", "admin": "The milk route at a glance."}.get(user["role"], ""))


def add_farmer_form():
    with st.form("add_farmer", clear_on_submit=True):
        name = st.text_input("Name")
        phone = st.text_input("Phone", placeholder="0712 345 678")
        farm_name = st.text_input("Farm name (optional)")
        herd_size = st.number_input("Cows in milk (optional)", min_value=0, step=1, value=0)
        if st.form_submit_button("Save farmer", type="primary"):
            try:
                if not name.strip():
                    raise ValueError("name is required")
                db.add_farmer(
                    name.strip(),
                    normalize_phone(phone),
                    farm_name.strip() or None,
                    int(herd_size) or None,
                )
                st.success(f"Saved {name.strip()}.")
                st.rerun()
            except ValueError as e:
                st.error(cap(e))

farmers = accounts.visible_farmers(user)
if user["role"] == "admin":
    # The admin's home is a business overview, not a farm's: farm pages belong to the farmer's own login.
    routes = db.list_routes()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Farmers", len(farmers))
    c2.metric("Routes", len(routes))
    c3.metric("Vets", len(db.list_users("vet")))
    c4.metric("Signups waiting", len(db.list_pending_users()))
    st.write("Use **Admin** for routes, vets and sign-ups, **Attendance** for today's visits, "
             "and **Alerts** or **Vaccination** to notify farmers.")
    with st.expander("Add a farmer without a login", expanded=not farmers):
        add_farmer_form()
    st.stop()
if user["role"] == "vet":
    sheet = services.day_sheet(user, date.today())
    c1, c2, c3 = st.columns(3)
    c1.metric("Visits today", sheet["total"])
    c2.metric("Done", sheet["done"])
    c3.metric("Waiting for a day", len(services.inbox(user)))
    st.write("Open **My day** for today's farms, what to carry and your semen list.")
    st.stop()
if not farmers:
    st.info("No farm is linked to your login yet. Ask your admin.")
if farmers:
    farmer_id = farmer_selector()
    today = date.today()
    week = db.daily_yield(farmer_id, today - timedelta(days=6), today)
    todays = next((r for r in week if r["log_date"] == today), None)

    steps = checklist(
        db.get_milk_price(farmer_id),
        db.list_cows(farmer_id),
        db.cows_in_milk_on(farmer_id, today),
        db.list_catalogue(farmer_id),
        db.daily_yield(farmer_id, today - timedelta(days=365), today),
    )
    upcoming = next_step(steps)
    if upcoming:
        finished = sum(1 for item in steps if item[4])
        with st.container(border=True):
            st.subheader("Get started")
            st.caption(f"{finished} of {len(steps)} steps done. Each takes about a minute, and you can do them in any order.")
            st.progress(finished / len(steps))
            for key, label, why, page, ok in steps:
                mark = "✅" if ok else ("👉" if key == upcoming[0] else "⬜")
                st.markdown(f"{mark} **{label}**" + ("" if ok else f" — {why}"))
            st.page_link(upcoming[3], label=f"Next: {upcoming[1]}", icon="➡️")

    c1, c2 = st.columns(2)
    c1.metric("Milk today (litres)", f"{float(todays['litres']):.1f}" if todays else "no entry")
    c2.metric("Last 7 days (litres)", f"{sum(float(r['litres']) for r in week):.1f}")
    if not upcoming:
        st.write("Use **Feed log** in the menu each day to record milkings and feed.")
