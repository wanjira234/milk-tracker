"""Farm setup: milk price, the farm's feeds (in its own units), and cows in milk."""
from datetime import date

import pandas as pd
import streamlit as st

from src import db
from src.ingestion.manual_entry import (
    record_catalogue_item,
    record_cows_in_milk,
    record_milk_price,
)
from src.ui import cap, farmer_selector

st.set_page_config(page_title="Farm setup", page_icon="🥛", layout="centered")
st.title("Farm setup")
st.caption("Set these up once, and update them when prices or the herd change.")

farmer_id = farmer_selector()
today = date.today()

# --- milk price ---------------------------------------------------------------
st.subheader("Milk price")
with st.form("milk_price"):
    current_price = db.get_milk_price(farmer_id)
    price = st.number_input(
        "Price paid per litre (KES)", min_value=0.0, step=1.0, format="%.0f",
        value=float(current_price or 0.0), key=f"price_{farmer_id}",
    )
    if st.form_submit_button("Save price", type="primary"):
        try:
            st.success(f"Saved KES {record_milk_price(farmer_id, price):,.0f} per litre.")
        except ValueError as e:
            st.error(cap(e))
if db.get_milk_price(farmer_id) is None:
    st.caption("Without a price the app can't work out feed margin (milk income minus feed cost).")

# --- feeds --------------------------------------------------------------------
st.divider()
st.subheader("Feeds")
st.caption(
    "List each feed the way the farm measures it: a trunk, a wheelbarrow, a bag, a bundle. "
    "Say how many kg one unit weighs and what it costs, and logging becomes 'how many units'. "
    "Use the same plain names every time (for example pineapple waste, machicha, napier, maize stalks, "
    "hay, banana trunks, dairy meal, protein mix) so results can be compared across farms later."
)

catalogue = db.list_catalogue(farmer_id)
if catalogue:
    df = pd.DataFrame(catalogue)[["name", "unit", "kg_per_unit", "kes_per_unit"]].astype(
        {"kg_per_unit": float, "kes_per_unit": float}
    )
    df["KES per kg"] = (df["kes_per_unit"] / df["kg_per_unit"]).round(2)
    df.columns = ["Feed", "Unit", "Kg per unit", "KES per unit", "KES per kg"]
    st.dataframe(df, hide_index=True, width="stretch")
else:
    st.info("No feeds yet. Add the first one below.")

with st.form("add_feed_item", clear_on_submit=True):
    st.markdown("**Add or update a feed**")
    name = st.text_input("Feed", placeholder="banana trunks")
    unit = st.text_input("Unit", placeholder="trunk, wheelbarrow, bag...")
    kg_per_unit = st.number_input("Kg in one unit", min_value=0.0, step=1.0, format="%.1f")
    kes_per_unit = st.number_input("Price of one unit (KES)", min_value=0.0, step=5.0, format="%.0f")
    st.caption(
        "Bought in bulk? Divide it down. A truck load that costs KES 15,000 and holds about 4,000 kg "
        "makes a 40 kg wheelbarrow cost KES 150. Saving a feed that already exists updates its price."
    )
    if st.form_submit_button("Save feed", type="primary"):
        try:
            saved = record_catalogue_item(farmer_id, name, unit, kg_per_unit, kes_per_unit)
            st.success(f"Saved {saved['name']}: 1 {saved['unit']} = {saved['kg_per_unit']} kg, KES {saved['kes_per_unit']:,.0f}.")
        except ValueError as e:
            st.error(cap(e))

if catalogue:
    names = {c["id"]: c["name"] for c in catalogue}
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    to_remove = c1.selectbox("Stop using a feed", list(names), format_func=names.get, index=None, placeholder="Choose a feed")
    if c2.button("Remove", disabled=to_remove is None):
        db.retire_catalogue_item(to_remove)
        st.rerun()
    st.caption("Removing hides a feed from the logging form. Past entries keep their numbers.")

# --- cows in milk -------------------------------------------------------------
st.divider()
st.subheader("Cows in milk")
st.caption(
    "Update this whenever a cow calves or is dried off. Calving and drying off change the milk far more "
    "than most feed changes. If the herd changes on the same day as the feed and the app isn't told, "
    "it can credit or blame the feed for what the cow did."
)

with st.form("cows_form"):
    cows_now = db.cows_in_milk_on(farmer_id, today)
    c1, c2 = st.columns(2)
    eff_date = c1.date_input("From", value=today, max_value=today)
    cows = c2.number_input("Cows in milk", min_value=0, step=1, value=int(cows_now or 0), key=f"cows_{farmer_id}")
    if st.form_submit_button("Save", type="primary"):
        try:
            saved = record_cows_in_milk(farmer_id, eff_date, cows)
            st.success(f"{saved['cows_in_milk']} cows in milk from {saved['effective_date']}.")
        except ValueError as e:
            st.error(cap(e))

history = db.herd_history(farmer_id)
if history:
    df = pd.DataFrame(history).rename(columns={"effective_date": "From", "cows_in_milk": "Cows in milk"})
    st.dataframe(df, hide_index=True, width="stretch")
else:
    st.caption("Nothing recorded yet.")
