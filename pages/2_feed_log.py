"""Record milk yield and feed, and review recent entries."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src import db
from src.ingestion.manual_entry import SESSIONS, record_feed, record_yield
from src.ui import cap, farmer_selector

st.set_page_config(page_title="Feed log", page_icon="🥛", layout="centered")
st.title("Feed log")

farmer_id = farmer_selector()
today = date.today()

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
    with st.form("feed_form"):
        f_date = st.date_input("Date", value=today, max_value=today, key="f_date")
        f_type = st.text_input("Feed", placeholder="dairy meal, napier, hay...")
        f_kg = st.number_input("Kilograms", min_value=0.0, step=0.5, format="%.1f")
        f_cost = st.number_input("Cost (KES, optional)", min_value=0.0, step=10.0, format="%.0f")
        if st.form_submit_button("Save feed", type="primary"):
            try:
                saved = record_feed(farmer_id, f_date, f_type, f_kg, f_cost or None)
                st.success(f"Saved {saved['kg']} kg {saved['feed_type']} on {saved['log_date']}.")
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
