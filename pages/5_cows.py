"""Cows: breeding (heat, service, in calf, calving), the semen the farm can choose from, and deworming."""
from datetime import date

import streamlit as st

from src import db
from src.auth import require_login
from src.breeding import DEWORM_EVERY_DAYS, KINDS, cow_status, deworm_status
from src.ingestion.manual_entry import record_breeding_event, record_cow, record_deworming, record_semen
from src.ui import cap, farmer_selector

st.set_page_config(page_title="Cows", page_icon="🥛", layout="centered")
require_login()
st.title("Cows")
st.caption(
    "Keep each cow's heat, service and calving, and when she was last dewormed. Dates shown as 'about' are "
    "typical figures for cattle: your vet's word comes first."
)

farmer_id = farmer_selector()
today = date.today()


def flash(message, level="success"):
    """Show a message after the page reloads, so the tables above reflect what was just saved."""
    st.session_state["flash"] = (level, message)
    st.rerun()


if "flash" in st.session_state:
    level, message = st.session_state.pop("flash")
    getattr(st, level)(message)

cows = db.list_cows(farmer_id)
semen = db.list_semen(farmer_id)
events = db.breeding_events(farmer_id)
worming = db.dewormings(farmer_id)

# --- overview -------------------------------------------------------------------
if not cows:
    st.info("Add your cows below to start. Use the name or ear-tag number you already call each one.")
else:
    herd_last = max((w["given_on"] for w in worming if w["cow_id"] is None), default=None)
    rows = []
    for c in cows:
        status = cow_status([e for e in events if e["cow_id"] == c["id"]], today)
        mine = [w["given_on"] for w in worming if w["cow_id"] == c["id"]]
        last = max([*mine, *([herd_last] if herd_last else [])], default=None)
        worm = deworm_status(last, today)
        rows.append({"Cow": c["tag"], "Status": status["label"], "Next": status["next"] or "", "Deworming": worm["text"]})
    for r in rows:  # one card per cow: a table is cut off on a phone
        with st.container(border=True):
            st.markdown(f"**{r['Cow']}**")
            st.write(r["Status"])
            if r["Next"]:
                st.caption(r["Next"])
            st.caption(f"Deworming: {r['Deworming']}")
    overdue = [r["Cow"] for r in rows if r["Deworming"].startswith("Overdue")]
    if overdue:
        st.warning("Deworming is overdue for: " + ", ".join(overdue) + ".")

# --- what happened ---------------------------------------------------------------
st.divider()
st.subheader("Record what happened")
if not cows:
    st.caption("Add a cow first.")
else:
    names = {c["id"]: c["tag"] for c in cows}
    cow_id = st.selectbox("Cow", list(names), format_func=names.get, key="ev_cow")
    kind = st.selectbox("What happened", list(KINDS), format_func=KINDS.get, key="ev_kind")
    semen_id = None
    if kind == "served":
        if semen:
            options = {s["id"]: s["name"] for s in semen}
            semen_id = st.selectbox("Semen used", list(options), format_func=options.get, key="ev_semen")
        else:
            st.caption("Add the semen you can choose from in the list below, then pick it here.")
    ev_date = st.date_input("Date", value=today, max_value=today, key="ev_date")
    if st.button("Save", type="primary", key="ev_save"):
        try:
            record_breeding_event(farmer_id, cow_id, ev_date, kind, semen_id)
            note = " Remember to update how many cows are in milk on the farm setup page." if kind in ("calved", "aborted") else ""
            flash(f"Saved: {names[cow_id]}, {KINDS[kind].lower()}, {ev_date}.{note}")
        except ValueError as e:
            st.error(cap(e))

    with st.expander("History and fixing a mistake"):
        mine = [e for e in events if e["cow_id"] == cow_id]
        if not mine:
            st.caption("Nothing recorded for this cow yet.")
        for e in reversed(mine):
            c1, c2 = st.columns([4, 1], vertical_alignment="center")
            c1.write(f"{e['event_date']}: {KINDS[e['kind']]}" + (f" with {e['semen']}" if e["semen"] else ""))
            if c2.button("Delete", key=f"del_{e['id']}"):
                db.delete_breeding_event(farmer_id, e["id"])
                st.rerun()

# --- deworming --------------------------------------------------------------------
st.divider()
st.subheader("Deworming")
st.caption(f"Cattle are usually dewormed about every {DEWORM_EVERY_DAYS // 30} months. Record it for the whole herd, or for one cow.")
who_options = {None: "Whole herd", **{c["id"]: c["tag"] for c in cows}}
w_who = st.selectbox("Who", list(who_options), format_func=who_options.get, key="dw_who")
w1, w2 = st.columns(2)
w_date = w1.date_input("Date given", value=today, max_value=today, key="dw_date")
w_product = w2.text_input("Medicine (optional)", key="dw_product")
if st.button("Save deworming", type="primary", key="dw_save"):
    try:
        record_deworming(farmer_id, w_date, w_who, w_product)
        flash(f"Saved: {who_options[w_who]} dewormed on {w_date}.")
    except ValueError as e:
        st.error(cap(e))

# --- cows and semen lists ----------------------------------------------------------
st.divider()
st.subheader("Your cows")
c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
new_cow = c1.text_input("Name or tag number", key="new_cow", placeholder="Wanjiku, or 014")
if c2.button("Add cow", key="add_cow"):
    try:
        saved = record_cow(farmer_id, new_cow)
        flash(f"Added {saved['tag']}.")
    except ValueError as e:
        st.error(cap(e))
if cows:
    r1, r2 = st.columns([3, 1], vertical_alignment="bottom")
    gone = r1.selectbox("Sold or died", [c["id"] for c in cows], format_func={c["id"]: c["tag"] for c in cows}.get, index=None, placeholder="Choose a cow")
    if r2.button("Remove", key="rm_cow", disabled=gone is None):
        db.retire_cow(farmer_id, gone)
        st.rerun()
    st.caption("Removing hides her from the lists. Her history is kept.")

st.divider()
st.subheader("Semen you can choose from")
st.caption("The bulls or breeds your AI service offers. Name them the way you would say them, for example 'Friesian - Kamau'.")
s1, s2 = st.columns([3, 1], vertical_alignment="bottom")
new_semen = s1.text_input("Bull name or breed", key="new_semen")
if s2.button("Add", key="add_semen"):
    try:
        saved = record_semen(farmer_id, new_semen)
        flash(f"Added {saved['name']}.")
    except ValueError as e:
        st.error(cap(e))
if semen:
    st.write(", ".join(s["name"] for s in semen))
    t1, t2 = st.columns([3, 1], vertical_alignment="bottom")
    drop = t1.selectbox("Stop offering", [s["id"] for s in semen], format_func={s["id"]: s["name"] for s in semen}.get, index=None, placeholder="Choose semen")
    if t2.button("Remove", key="rm_semen", disabled=drop is None):
        db.retire_semen(farmer_id, drop)
        st.rerun()
