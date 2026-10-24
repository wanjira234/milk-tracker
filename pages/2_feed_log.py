"""Record milk yield and feed, and review recent entries."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src import db
from src.ingestion.manual_entry import BUCKET_LITRES, SESSIONS, record_feed, record_feed_units, record_water, record_yield
from src.ui import cap, farmer_selector
from src.auth import require_login

st.set_page_config(page_title="Feed log", page_icon="🥛", layout="centered")
require_login(roles=("farmer",))
st.title("Feed log")

farmer_id = farmer_selector()
today = date.today()

cows = db.cows_in_milk_on(farmer_id, today)
if cows is None:
    st.info("Set how many cows are in milk on the farm setup page. Without it, the model can't tell feed from a cow drying off.")
else:
    st.caption(f"{cows} cows in milk. Update this on the farm setup page when it changes.")

left, right = st.columns(2)

with left:
    st.subheader("Milk yield")
    with st.form("yield_form"):
        y_date = st.date_input("Date", value=today, max_value=today, key="y_date")
        y_session = st.selectbox("Milking", SESSIONS)
        y_litres = st.number_input("Litres", min_value=0.0, step=0.5, format="%.1f")
        if st.form_submit_button("Save yield", type="primary"):
            try:
                saved = record_yield(farmer_id, y_date, y_session, y_litres)
                st.success(f"Saved {saved['litres']} L, {saved['session']} on {saved['log_date']}.")
            except ValueError as e:
                st.error(cap(e))

with right:
    st.subheader("Feed")
    OTHER = "Other (enter kg)"
    items = {c["name"]: c for c in db.list_catalogue(farmer_id)}
    # Outside the form so the fields below change as soon as another feed is picked.
    choice = st.selectbox("Feed", [*items, OTHER]) if items else OTHER
    if not items:
        st.caption("Add your feeds on the farm setup page to log them in trunks, wheelbarrows or bags.")
    with st.form("feed_form"):
        f_date = st.date_input("Date", value=today, max_value=today, key="f_date")
        if choice == OTHER:
            f_type = st.text_input("Feed name", placeholder="dairy meal, napier, hay...")
            f_kg = st.number_input("Kilograms", min_value=0.0, step=0.5, format="%.1f")
            f_cost = st.number_input("Cost (KES, optional)", min_value=0.0, step=10.0, format="%.0f")
        else:
            item = items[choice]
            f_units = st.number_input(f"How many ({item['unit']})", min_value=0.0, step=0.5, format="%.1f")
            st.caption(f"1 {item['unit']} = {float(item['kg_per_unit']):g} kg, KES {float(item['kes_per_unit']):,.0f}")
        if st.form_submit_button("Save feed", type="primary"):
            try:
                if choice == OTHER:
                    saved = record_feed(farmer_id, f_date, f_type, f_kg, f_cost or None)
                    st.success(f"Saved {saved['kg']} kg {saved['feed_type']} on {saved['log_date']}.")
                else:
                    saved = record_feed_units(farmer_id, f_date, item, f_units)
                    st.success(
                        f"Saved {saved['feed_type']}: {saved['units']:g} × {saved['unit']} on {saved['log_date']} "
                        f"({saved['kg']:g} kg, KES {saved['cost_kes']:,.0f})."
                    )
            except ValueError as e:
                st.error(cap(e))

st.divider()
st.subheader("Water")
st.caption("The total the herd drank today. Count 20 L buckets or enter litres. Saving the same day again replaces it.")
with st.form("water_form"):
    w1, w2, w3 = st.columns([2, 2, 3], vertical_alignment="bottom")
    w_date = w1.date_input("Date", value=today, max_value=today, key="w_date")
    w_amount = w2.number_input("How many", min_value=0.0, step=1.0, format="%.1f", key="w_amount")
    w_unit = w3.radio("Counted in", [f"{BUCKET_LITRES:g} L buckets", "litres"], horizontal=True, key="w_unit")
    if st.form_submit_button("Save water", type="primary"):
        try:
            saved = record_water(farmer_id, w_date, w_amount, bucket=w_unit != "litres")
            st.success(f"Saved {saved['litres']:g} L of water on {saved['log_date']}.")
        except ValueError as e:
            st.error(cap(e))

st.divider()
start = today - timedelta(days=13)

st.subheader("Last 14 days")
yields = db.daily_yield(farmer_id, start, today)
feeds = db.daily_feed(farmer_id, start, today)

if yields:
    df = pd.DataFrame(yields).rename(columns={"log_date": "Date", "litres": "Litres", "sessions": "Milkings"})
    df["Litres"] = df["Litres"].astype(float)
    st.dataframe(df.sort_values("Date", ascending=False), hide_index=True, width="stretch")
else:
    st.caption("No yield recorded in the last 14 days.")

if feeds:
    df = pd.DataFrame(feeds).rename(columns={"log_date": "Date", "feed_type": "Feed", "kg": "Kg", "cost_kes": "Cost (KES)"})
    df[["Kg", "Cost (KES)"]] = df[["Kg", "Cost (KES)"]].astype(float)
    st.dataframe(df.sort_values("Date", ascending=False), hide_index=True, width="stretch")
else:
    st.caption("No feed recorded in the last 14 days.")

water = db.daily_water(farmer_id, start, today)
if water:
    df = pd.DataFrame(water).rename(columns={"log_date": "Date", "litres": "Water (L)"})
    df["Water (L)"] = df["Water (L)"].astype(float)
    st.dataframe(df.sort_values("Date", ascending=False), hide_index=True, width="stretch")
else:
    st.caption("No water recorded in the last 14 days.")
