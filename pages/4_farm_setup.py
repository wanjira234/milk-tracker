"""Farm setup: milk price, the farm's feeds (in its own units), and cows in milk."""
from datetime import date

import pandas as pd
import streamlit as st

from src import db
from src.calculator import breakdown, load_buckets, money, total_kg
from src.ingestion.manual_entry import (
    record_catalogue_item,
    record_cows_in_milk,
    record_milk_price,
)
from src.ui import cap, farmer_selector
from src.auth import require_login

st.set_page_config(page_title="Farm setup", page_icon="🥛", layout="centered")
require_login(roles=("farmer",))
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

LOAD = "A load I feed out in buckets"
with st.expander("Feed calculator: a truck load, bales or bags", expanded=not catalogue):
    st.caption(
        "Bought a truck load, or cut feed from your own farm, that you shred and feed in buckets? Say what it cost and how long it lasted, "
        "and this works out what one bucket costs. An estimate is fine."
    )
    calc_name = st.text_input("Which feed?", placeholder="napier", key="calc_name")
    source = st.radio("Where does it come from?", ["I buy it", "I grow or harvest it on my farm"], horizontal=True, key="calc_source")
    if source == "I buy it":
        calc_price = st.number_input("What did you pay for it? (KES)", min_value=0.0, step=500.0, format="%.0f", key="calc_price")
    else:
        calc_price = st.number_input(
            "What did it cost you to grow, if you know? (KES, 0 if not)", min_value=0.0, step=500.0, format="%.0f", key="calc_price",
            help="Seed, fertiliser or casual labour you paid for. Leave 0 to count it as free. Your own land and time are not counted.",
        )
        st.caption("For feed from your own farm, say how much you cut, and how long it lasted.")
    how = st.radio(
        "How do you know how much you got?", [LOAD, "I counted it in measures", "I know the kg"],
        key="calc_how",
    )
    bucket_kg = None
    if how == LOAD:
        c1, c2 = st.columns(2)
        days = c1.number_input("It lasted about (days)", min_value=0.0, step=1.0, format="%.0f", key="calc_days")
        per_day = c2.number_input("Buckets fed a day", min_value=0.0, step=1.0, format="%.0f", key="calc_perday")
        bucket_kg = st.number_input(
            "Kg in one full bucket (weigh one once)", min_value=0.0, step=1.0, format="%.1f", key="calc_bucket",
            help="A full 20 L bucket of fresh shredded napier weighs far more than a bucket of dry hay, so weigh one "
                 "full bucket of this feed once, on any scale.",
        )
        calc_kg_total = None
        try:
            buckets = load_buckets(days, per_day) if days and per_day else None
        except ValueError as e:
            st.error(cap(e))
            buckets = None
        if buckets and calc_price >= 0 and bucket_kg:
            calc_kg_total = buckets * bucket_kg
        elif buckets:
            st.markdown(f"**About {buckets:,.0f} buckets: {money(calc_price / buckets)} a bucket.**")
            st.caption("Weigh one full bucket and enter its kg above, to save this feed and to see the price per kg.")
    elif how == "I know the kg":
        calc_kg_total = st.number_input("Total kg", min_value=0.0, step=100.0, format="%.0f", key="calc_kg")
    else:
        c1, c2 = st.columns(2)
        counted_in = c1.selectbox(
            "Counted in", ["big mtungi (about 20 kg)", "1 kg tilly", "2 kg tilly", "50 kg bag", "20 L bucket", "something else"],
            key="calc_counted",
        )
        calc_count = c2.number_input("How many", min_value=0.0, step=10.0, format="%.0f", key="calc_count")
        each = {"big mtungi (about 20 kg)": 20.0, "1 kg tilly": 1.0, "2 kg tilly": 2.0, "50 kg bag": 50.0}.get(counted_in)
        if each is None:
            each = st.number_input(
                "Kg in one" + (" full bucket (weigh one once)" if counted_in == "20 L bucket" else ""),
                min_value=0.0, step=1.0, format="%.1f", key="calc_each",
            )
        calc_kg_total = None
        try:
            calc_kg_total = total_kg(calc_count, each) if calc_count and each else None
        except ValueError as e:
            st.error(cap(e))
        if counted_in == "20 L bucket" and each:
            bucket_kg = each
    if calc_kg_total:
        try:
            rows = breakdown(calc_price, calc_kg_total, bucket_kg or None)
        except ValueError as e:
            st.error(cap(e))
            rows = []
        if rows:
            if how == LOAD:
                row_bucket = next(r for r in rows if r["unit"] == "bucket")
                st.markdown(f"**One bucket of {calc_name or 'this feed'} costs about {money(row_bucket['kes'])}** "
                            f"({money(calc_price / calc_kg_total)} per kg).")
                rows = [row_bucket]
            else:
                st.markdown(f"**About {calc_kg_total:,.0f} kg for KES {calc_price:,.0f}: {money(calc_price / calc_kg_total)} per kg**")
                st.dataframe(
                    pd.DataFrame({
                        "Measure": [r["measure"] for r in rows],
                        "Kg": [r["kg"] for r in rows],
                        "Price": [money(r["kes"]) for r in rows],
                    }),
                    hide_index=True, width="stretch",
                )
            pick = rows[0]["measure"] if len(rows) == 1 else st.selectbox(
                "Save to my feeds as", [r["measure"] for r in rows], key="calc_pick")
            if st.button("Save this feed", type="primary", key="calc_save"):
                row = next(r for r in rows if r["measure"] == pick)
                try:
                    saved = record_catalogue_item(farmer_id, calc_name, row["unit"], row["kg"], round(row["kes"], 2))
                    st.success(f"Saved {saved['name']}: 1 {saved['unit']} = {saved['kg_per_unit']:g} kg, {money(saved['kes_per_unit'])}.")
                except ValueError as e:
                    st.error(cap(e))
    elif how != LOAD:
        st.caption("Fill in the price and how much you got to see the result.")

with st.form("add_feed_item", clear_on_submit=True):
    st.markdown("**Already know the price of one unit? Add or update a feed**")
    name = st.text_input("Feed", placeholder="banana trunks")
    unit = st.text_input("Unit", placeholder="trunk, wheelbarrow, bag...")
    kg_per_unit = st.number_input("Kg in one unit", min_value=0.0, step=1.0, format="%.1f")
    kes_per_unit = st.number_input("Price of one unit (KES)", min_value=0.0, step=5.0, format="%.0f")
    st.caption(
        "Grew it yourself? Put 0, or what it cost you. Bought in bulk? Divide it down. A truck load that costs KES 15,000 and holds about 4,000 kg "
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
