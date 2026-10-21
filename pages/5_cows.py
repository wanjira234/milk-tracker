"""Cows: milking and dry cows, heifers, calves and their mothers; breeding, deworming, semen."""
from datetime import date

import streamlit as st

from src import db
from src.auth import require_login
from src.breeding import DEWORM_EVERY_DAYS, KINDS, STAGES, age_text, cow_status, deworm_status
from src.herd import cows_in_milk_on, lactation_on
from src.ingestion.manual_entry import (
    record_breeding_event,
    record_calving,
    record_cow,
    record_deworming,
    record_semen,
    record_wean,
)
from src.ui import cap, farmer_selector

st.set_page_config(page_title="Cows", page_icon="🥛", layout="centered")
require_login()
st.title("Cows")
st.caption(
    "Keep each animal's heat, service, calving and deworming. Dates shown as 'about' are "
    "typical figures for cattle: your vet's word comes first."
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

all_cows = db.list_cows(farmer_id, active_only=False)
cows = [c for c in all_cows if c["active"]]
by_id = {c["id"]: c for c in all_cows}
semen = db.list_semen(farmer_id)
events = db.breeding_events(farmer_id)
worming = db.dewormings(farmer_id)
herd_last = max((w["given_on"] for w in worming if w["cow_id"] is None), default=None)


def my_events(cow_id):
    return [e for e in events if e["cow_id"] == cow_id]


def deworm_for(cow_id):
    mine = [w["given_on"] for w in worming if w["cow_id"] == cow_id]
    return deworm_status(max([*mine, *([herd_last] if herd_last else [])], default=None), today)


def card(cow, lines, button=None, notes=()):
    with st.container(border=True):
        st.markdown(f"**{cow['tag']}**")
        for line in lines:
            if line:
                st.write(line)
        for note in notes:
            if note:
                st.caption(note)
        if button:
            return st.button(button[0], key=button[1])
    return False


# --- cows in milk ----------------------------------------------------------------
records_on = db.cows_in_milk_from_records(farmer_id)
preview = cows_in_milk_on(all_cows, events, today)
with st.container(border=True):
    if records_on:
        st.markdown(f"**{preview or 0} {'cow' if preview == 1 else 'cows'} milking today**, worked out from the cow records below.")
        st.caption(
            "This number feeds the feed advice. To change it, record that a cow calved, started milking or was dried off. "
            "The 'Cows in milk' box on the farm setup page is not used while this is on."
        )
        if st.button("Go back to typing the number in", key="herd_off"):
            db.set_cows_in_milk_from_records(farmer_id, False)
            flash("Cows in milk is typed in on the farm setup page again.")
    else:
        typed = db.cows_in_milk_on(farmer_id, today)
        st.markdown("**Cows in milk:** " + (f"{typed} (typed in on the farm setup page)" if typed is not None else "not set yet"))
        if preview:
            st.caption(
                f"The cow records say {preview} {'cow is' if preview == 1 else 'cows are'} milking today. If that is right, let the app work "
                "it out from now on, so a calving or drying off updates it by itself."
            )
            if st.button("Use my cow records for cows in milk", key="herd_on"):
                db.set_cows_in_milk_from_records(farmer_id, True)
                flash("Cows in milk is now worked out from the cow records.")
        else:
            st.caption(
                "To let the app work this out, add each cow below as milking (or dry) and it will keep the "
                "count up to date when cows calve or dry off."
            )

# --- the animals -----------------------------------------------------------------
if not cows:
    st.info("Add your animals below to start. Use the name or ear-tag number you already call each one.")

adults = [c for c in cows if c["life_stage"] == "cow"]
heifers = [c for c in cows if c["life_stage"] == "heifer"]
calves = [c for c in cows if c["life_stage"] == "calf"]
bulls = [c for c in cows if c["life_stage"] == "bull"]


def mother_line(c):
    m = by_id.get(c["mother_id"])
    return f"Mother: {m['tag']}" if m else None


def age_line(c):
    a = age_text(c["birth_date"], today)
    return f"Age: {a}" if a else None


if adults:
    st.subheader("Cows")
    overdue = []
    for c in adults:
        evs = my_events(c["id"])
        status = cow_status(evs, today)
        lact = lactation_on(evs, today)
        lact_line = {"milking": "Milking", "dry": "Dry (not milking)", None: "Milking status not recorded"}[lact]
        kids = [k for k in all_cows if k["mother_id"] == c["id"] and k["active"]]
        kids_line = "Calves: " + ", ".join(
            f"{k['tag']}" + (f" (born {k['birth_date']:%d %b %Y})" if k["birth_date"] else "") for k in kids
        ) if kids else None
        worm = deworm_for(c["id"])
        if worm["state"] == "overdue":
            overdue.append(c["tag"])
        card(c, [f"{lact_line}. {status['label']}", kids_line], notes=[status["next"], f"Deworming: {worm['text']}"])
    if overdue:
        st.warning("Deworming is overdue for: " + ", ".join(overdue) + ".")

if heifers:
    st.subheader("Heifers")
    for c in heifers:
        status = cow_status(my_events(c["id"]), today, life_stage="heifer")
        card(c, [age_line(c), mother_line(c), status["label"]], notes=[status["next"], f"Deworming: {deworm_for(c['id'])['text']}"])

if calves:
    st.subheader("Calves on milk")
    for c in calves:
        pressed = card(
            c, [f"{'Female' if c['sex'] == 'female' else 'Male'} calf", age_line(c), mother_line(c)],
            ("Weaned today (stopped drinking milk)", f"wean_{c['id']}"),
        )
        if pressed:
            try:
                record_wean(farmer_id, c["id"], today)
                flash(f"{c['tag']} is weaned and is now a {'heifer' if c['sex'] == 'female' else 'young bull'}.")
            except ValueError as e:
                st.error(cap(e))

if bulls:
    st.subheader("Young bulls")
    for c in bulls:
        card(c, [age_line(c), mother_line(c)])

# --- what happened ---------------------------------------------------------------
st.divider()
st.subheader("Record what happened")
breedable = adults + heifers
if not breedable:
    st.caption("Add a cow or heifer first.")
else:
    names = {c["id"]: c["tag"] for c in breedable}
    cow_id = st.selectbox("Cow", list(names), format_func=names.get, key="ev_cow")
    kind = st.selectbox("What happened", list(KINDS), format_func=KINDS.get, key="ev_kind")
    semen_id = None
    if kind == "served":
        if semen:
            options = {s["id"]: s["name"] for s in semen}
            semen_id = st.selectbox("Semen used", list(options), format_func=options.get, key="ev_semen")
        else:
            st.caption("Add the semen you can choose from in the list below, then pick it here.")
    calf_tag, calf_sex = "", "female"
    if kind == "calved":
        calf_tag = st.text_input("Name or tag of the calf (optional)", key="ev_calf_tag")
        calf_sex = st.radio("The calf is", ["female", "male"], horizontal=True, key="ev_calf_sex")
    ev_date = st.date_input("Date", value=today, max_value=today, key="ev_date")
    if st.button("Save", type="primary", key="ev_save"):
        try:
            if kind == "calved":
                record_calving(farmer_id, cow_id, ev_date, calf_tag, calf_sex)
            else:
                record_breeding_event(farmer_id, cow_id, ev_date, kind, semen_id)
            note = ""
            if kind in ("calved", "milking", "dried_off") and records_on:
                note = " Cows in milk has been updated."
            elif kind in ("calved", "milking", "dried_off", "aborted"):
                note = " Remember to update how many cows are in milk on the farm setup page, or let the app work it out above."
            flash(f"Saved: {names[cow_id]}, {KINDS[kind].lower()}, {ev_date}.{note}")
        except ValueError as e:
            st.error(cap(e))

    with st.expander("History and fixing a mistake"):
        mine = my_events(cow_id)
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
st.caption(f"Cattle are usually dewormed about every {DEWORM_EVERY_DAYS // 30} months. Record it for the whole herd, or for one animal.")
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

# --- add an animal ------------------------------------------------------------------
st.divider()
st.subheader("Add an animal")
STAGE_CHOICES = {"cow": "Cow", "heifer": "Heifer (waiting for first heat)", "calf": "Calf (still drinking milk)", "bull": "Young bull"}
a_tag = st.text_input("Name or tag number", key="new_cow", placeholder="Wanjiku, or 014")
a_stage = st.selectbox("What is she?", list(STAGE_CHOICES), format_func=STAGE_CHOICES.get, key="new_stage")
a_sex = "male" if a_stage == "bull" else "female"
if a_stage == "calf":
    a_sex = st.radio("The calf is", ["female", "male"], horizontal=True, key="new_sex")
a_birth = None
if a_stage in ("calf", "heifer"):
    if st.checkbox("I know the birth date", key="new_know_birth"):
        a_birth = st.date_input("Birth date", value=today, max_value=today, key="new_birth")
a_mother = None
if a_stage in ("calf", "heifer", "bull"):
    mothers = {c["id"]: c["tag"] for c in all_cows if c["sex"] == "female" and c["life_stage"] in ("cow", "heifer")}
    a_mother = st.selectbox("Her mother, if she is on the farm", list(mothers), format_func=mothers.get, index=None, key="new_mother") if mothers else None
a_lact, a_since = None, None
if a_stage == "cow":
    choice = st.radio("Right now she is", ["Milking", "Dry (not milking)", "Not sure"], horizontal=True, key="new_lact")
    a_lact = {"Milking": "milking", "Dry (not milking)": "dry"}.get(choice)
    if a_lact:
        a_since = st.date_input(
            "Since about when?", value=today, max_value=today, key="new_since",
            help="The day she last calved, or the day she was dried off. A rough date is fine.",
        )
if st.button("Add", type="primary", key="add_cow"):
    try:
        saved = record_cow(
            farmer_id, a_tag, sex=a_sex, life_stage=a_stage, birth_date=a_birth,
            mother_id=a_mother, lactation=a_lact, since=a_since,
        )
        flash(f"Added {saved['tag']}.")
    except ValueError as e:
        st.error(cap(e))

if cows:
    r1, r2 = st.columns([3, 1], vertical_alignment="bottom")
    gone = r1.selectbox("Sold or died", [c["id"] for c in cows], format_func={c["id"]: c["tag"] for c in cows}.get, index=None, placeholder="Choose an animal")
    if r2.button("Remove", key="rm_cow", disabled=gone is None):
        db.retire_cow(farmer_id, gone)
        flash("Removed. Her history is kept, and she no longer counts as milking.")
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
