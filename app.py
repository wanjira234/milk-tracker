"""Milk Tracker: Streamlit entry point (home page)."""
from datetime import date, timedelta

import streamlit as st

from src import db
from src.ingestion.manual_entry import normalize_phone
from src.ui import cap, farmer_selector

st.set_page_config(page_title="Milk Tracker", page_icon="🥛", layout="centered")

st.title("Milk Tracker")
st.caption("Yield and feed tracking for smallholder dairy farms.")

with st.expander("Add a farmer", expanded=not db.list_farmers()):
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

farmers = db.list_farmers()
if farmers:
    farmer_id = farmer_selector()
    today = date.today()
    week = db.daily_yield(farmer_id, today - timedelta(days=6), today)
    todays = next((r for r in week if r["log_date"] == today), None)

    c1, c2 = st.columns(2)
    c1.metric("Milk today (litres)", f"{float(todays['litres']):.1f}" if todays else "no entry")
    c2.metric("Last 7 days (litres)", f"{sum(float(r['litres']) for r in week):.1f}")
    st.write("Use **feed log** in the sidebar to record milkings and feed.")
