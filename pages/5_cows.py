"""Cows: calves, heifers and cows; breeding (heat, service, in calf, calving, dry period);
mothers and calves; the semen the route vet offers; and deworming."""
from datetime import date

import streamlit as st

from src import db
from src.auth import require_login
from src.breeding import DEWORM_EVERY_DAYS, KINDS, deworm_status
from src.herd import animal_card, milking_summary
from src.ingestion.manual_entry import (
    record_breeding_event,
    record_calving,
    record_cow,
    record_cows_in_milk,
    record_deworming,
    record_weaning,
)
from src.ui import cap, farmer_selector

st.set_page_config(page_title="Cows", page_icon="🥛", layout="centered")
require_login(roles=("farmer",))
st.title("Cows")
st.caption(
    "Keep each animal's heat, service, calving and dry period, who her mother is, and when she was last dewormed. "
    "Dates shown as 'about' are typical figures for cattle: your vet's word comes first."
)

farmer_id = farmer_selector()
today = date.today()


def flash(message, level="success"):
    """Show a message after the page reloads, so the cards above reflect what was just saved."""
    st.session_state["flash"] = (level, message)
    st.rerun()


if "flash" in st.session_state:
    level, message = st.session_state.pop("flash")
    getattr(st, level)(message)

animals = db.list_cows(farmer_id)
vet_id = db.route_vet_id(farmer_id)
vet_semen = db.list_vet_semen(vet_id) if vet_id else []  # the farmer picks from the route vet's list, never their own
events = db.breeding_events(farmer_id)
worming = db.dewormings(farmer_id)
events_by_cow = {}
for e in events:
    events_by_cow.setdefault(e["cow_id"], []).append(e)
tags = {a["id"]: a["tag"] for a in animals}
grown = [a for a in animals if a["kind"] == "cow"]
breedable = [a for a in animals if a["kind"] in ("cow", "heifer")]

# --- cows in milk: what the cow records say ---------------------------------------
if grown:
    milking, dry = milking_summary(animals, events_by_cow, today)
    recorded = db.cows_in_milk_on(farmer_id, today)
    st.info(f"Your records show **{milking}** cow(s) milking and **{dry}** dry. A cow with no breeding records counts as milking.")
    if recorded != milking:
        left, right = st.columns([3, 2], vertical_alignment="center")
        left.caption(
            "The herd record on the farm setup page says "
            + (f"{recorded} in milk." if recorded is not None else "nothing yet.")
            + " The model uses that record."
        )
        if right.button(f"Update cows in milk to {milking}", key="sync_milking"):
            try:
                record_cows_in_milk(farmer_id, today, milking)
                flash(f"Cows in milk is now {milking}.")
            except ValueError as e:
                st.error(cap(e))

# --- the herd, as cards -------------------------------------------------------------
if not animals:
    st.info("Add your animals below to start. Use the name or ear-tag number you already call each one.")
herd_last = max((w["given_on"] for w in worming if w["cow_id"] is None), default=None)
overdue = []
for stage, label in (("cow", "Cows"), ("heifer", "Heifers"), ("calf", "Calves")):
    group = [a for a in animals if a["kind"] == stage]
    if not group:
        continue
    st.subheader(label)
    for a in group:
        calves = [{"tag": c["tag"], "born_on": c["born_on"]} for c in animals if c["dam_id"] == a["id"]]
        card = animal_card(a, events_by_cow.get(a["id"], []), tags.get(a["dam_id"]), calves, today)
        mine = [w["given_on"] for w in worming if w["cow_id"] == a["id"]]
        worm = deworm_status(max([*mine, *([herd_last] if herd_last else [])], default=None), today)
        if worm["state"] == "overdue":
            overdue.append(a["tag"])
        with st.container(border=True):
            st.markdown(f"**{a['tag']}**" + (f"  ·  {card['milk']}" if card["milk"] else ""))
            st.write(card["status"])
            if card["next"]:
                st.caption(card["next"])
            for line in card["family"]:
                st.caption(line)
            st.caption(f"Deworming: {worm['text']}")
if overdue:
    st.warning("Deworming is overdue for: " + ", ".join(overdue) + ".")

# --- what happened --------------------------------------------------------------------
st.divider()
st.subheader("Record what happened")
if not breedable:
    st.caption("Add a cow or heifer first.")
else:
    names = {a["id"]: a["tag"] for a in breedable}
    cow_id = st.selectbox("Cow or heifer", list(names), format_func=names.get, key="ev_cow")
    kind = st.selectbox("What happened", list(KINDS), format_func=KINDS.get, key="ev_kind")
    semen_id = calf_tag = None
    calf_sex = "female"
    if kind == "served":
        if vet_semen:
            options = {v["id"]: f"{v['name']} (KES {float(v['price_kes']):,.0f})" for v in vet_semen}
            semen_id = st.selectbox("Semen used", list(options), format_func=options.get, key="ev_semen")
        else:
            st.caption("Your route vet has not listed any semen yet, so this is saved without one.")
    if kind == "calved":
        calf_tag = st.text_input("Name or tag of the calf (optional)", key="ev_calf_tag")
        calf_sex = st.radio("The calf is", ["female", "male"], horizontal=True, key="ev_calf_sex")
    ev_date = st.date_input("Date", value=today, max_value=today, key="ev_date")
    if st.button("Save", type="primary", key="ev_save"):
        try:
            if kind == "calved":
                done = record_calving(farmer_id, cow_id, ev_date, calf_tag, calf_sex)
                extra = f" Calf {done['calf']['tag']} added, with {names[cow_id]} as her mother." if done["calf"] else ""
                flash(f"Saved: {names[cow_id]} calved on {ev_date}.{extra} Update cows in milk if it changed.")
            else:
                if semen_id is not None:  # the vet's semen becomes the farm's own record under the same name
                    semen_id = db.add_semen(farmer_id, next(v["name"] for v in vet_semen if v["id"] == semen_id))
                record_breeding_event(farmer_id, cow_id, ev_date, kind, semen_id)
                flash(f"Saved: {names[cow_id]}, {KINDS[kind].lower()}, {ev_date}.")
        except ValueError as e:
            st.error(cap(e))

    with st.expander("History and fixing a mistake"):
        mine = [e for e in events if e["cow_id"] == cow_id]
        if not mine:
            st.caption("Nothing recorded for this animal yet.")
        for e in reversed(mine):
            c1, c2 = st.columns([4, 1], vertical_alignment="center")
            c1.write(f"{e['event_date']}: {KINDS[e['kind']]}" + (f" with {e['semen']}" if e["semen"] else ""))
            if c2.button("Delete", key=f"del_{e['id']}"):
                db.delete_breeding_event(farmer_id, e["id"])
                st.rerun()

# --- weaning ----------------------------------------------------------------------------
suckling = [a for a in animals if a["kind"] == "calf" and not a["weaned_on"]]
if suckling:
    st.divider()
    st.subheader("Weaning")
    st.caption("When a calf stops taking milk. A female calf then becomes a heifer, waiting for her first heat.")
    calf_names = {a["id"]: a["tag"] for a in suckling}
    wc1, wc2 = st.columns(2)
    wean_id = wc1.selectbox("Calf", list(calf_names), format_func=calf_names.get, key="wean_calf")
    wean_date = wc2.date_input("Date weaned", value=today, max_value=today, key="wean_date")
    if st.button("Save weaning", type="primary", key="wean_save"):
        try:
            done = record_weaning(farmer_id, wean_id, wean_date)
            flash(f"Saved: {calf_names[wean_id]} weaned on {wean_date}." + (" She is now a heifer." if done["became"] == "heifer" else ""))
        except ValueError as e:
            st.error(cap(e))

# --- deworming --------------------------------------------------------------------------
st.divider()
st.subheader("Deworming")
st.caption(f"Cattle are usually dewormed about every {DEWORM_EVERY_DAYS // 30} months. Record it for the whole herd, or for one animal.")
who_options = {None: "Whole herd", **{a["id"]: a["tag"] for a in animals}}
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

# --- add an animal; remove one; semen ------------------------------------------------------
st.divider()
st.subheader("Add an animal")
a_kind = st.radio("She is a", ["cow", "heifer", "calf"], horizontal=True, key="add_kind",
                  format_func={"cow": "Cow", "heifer": "Heifer (not yet calved)", "calf": "Calf"}.get)
a_tag = st.text_input("Name or tag number", key="new_cow", placeholder="Wanjiku, or 014")
a_sex, a_born, a_dam = "female", None, None
if a_kind == "calf":
    a_sex = st.radio("The calf is", ["female", "male"], horizontal=True, key="add_sex")
if a_kind in ("calf", "heifer"):
    if st.checkbox("I know the birth date", value=a_kind == "calf", key="add_known_born"):
        a_born = st.date_input("Born on", value=today, max_value=today, key="add_born")
    mothers = {a["id"]: a["tag"] for a in grown}
    if mothers:
        a_dam = st.selectbox("Mother (optional)", list(mothers), format_func=mothers.get, index=None,
                             placeholder="Choose the mother", key="add_dam")
if st.button("Add", key="add_cow"):
    try:
        saved = record_cow(farmer_id, a_tag, a_kind, a_sex, a_dam, a_born)
        flash(f"Added {saved['tag']}.")
    except ValueError as e:
        st.error(cap(e))
if animals:
    r1, r2 = st.columns([3, 1], vertical_alignment="bottom")
    gone = r1.selectbox("Sold or died", [a["id"] for a in animals], format_func=tags.get, index=None, placeholder="Choose an animal", key="rm_pick")
    if r2.button("Remove", key="rm_cow", disabled=gone is None):
        db.retire_cow(farmer_id, gone)
        st.rerun()
    st.caption("Removing hides her from the lists. Her history is kept.")

st.divider()
st.subheader("Semen your vet offers")
if not vet_id:
    st.caption("You are not on a route with a vet yet. Ask your admin.")
elif not vet_semen:
    st.caption("Your route vet has not listed any semen yet.")
else:
    st.caption("Set by your route vet. Pick from this list when you record a service or ask for AI.")
    for v in vet_semen:
        st.write(f"- {v['name']}: KES {float(v['price_kes']):,.0f}")
