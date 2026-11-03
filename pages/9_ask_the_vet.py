"""Farmer: ask the vet for AI, a sick-cow visit or something else, and follow the request."""
from datetime import date

import streamlit as st

from src.messages import ICON

from src import db, services
from src.auth import require_login
from src.ui import cap, farmer_selector, md

st.set_page_config(page_title="Ask the vet", page_icon=ICON, layout="centered")
user = require_login(roles=("farmer",))
farmer_id = farmer_selector()

st.title("Ask the vet")
route_vet_id = db.route_vet_id(farmer_id)
route_vet = db.get_user(route_vet_id) if route_vet_id else None
choices = services.vets_for_farm(farmer_id)  # [(None = route vet, label), (vet id, name), ...]
chosen = None
if len(choices) > 1:
    labels = dict(choices)
    chosen = st.selectbox("Send to", list(labels), format_func=labels.get, key="req_vet")
if chosen is None:
    if route_vet:
        st.caption(f"Your vet: **{route_vet['name']}**")
    else:
        st.warning("No vet is allocated to your route yet. You can still ask: the request waits until one is.")
answering = chosen if chosen is not None else route_vet_id

kind = st.radio("What do you need?", list(services.FARMER_KINDS), format_func=services.KINDS.get, horizontal=True, key="req_kind")
cows = [c for c in db.list_cows(farmer_id) if not (kind == "ai" and c["kind"] == "calf")]
semen_list = db.list_vet_semen(answering) if answering else []

with st.form("ask_vet", clear_on_submit=True):
    cow_id = semen_id = None
    if kind in ("ai", "sick"):
        if not cows:
            st.caption("Add the cow on the cows page first.")
        cow_id = st.selectbox("Which cow", [c["id"] for c in cows], index=None, placeholder="Choose a cow",
                              format_func={c["id"]: c["tag"] for c in cows}.get, key="req_cow")
    if kind == "ai":
        names = {s["id"]: f"{s['name']} (KES {float(s['price_kes']):,.0f})" for s in semen_list}
        semen_id = st.selectbox("Semen", list(names), index=None, placeholder="Choose, or leave for the vet to advise",
                                format_func=names.get, key="req_semen")
        st.caption("The semen price is taken off your monthly milk payment by your milk buyer, and shows in your profit."
                   if chosen is None else "You pay this vet directly: the bill shows under Money once the visit is done.")
    when = st.date_input("Best day", value=date.today(), key="req_day")
    notes = st.text_area("Notes" + ("" if kind == "other" else " (optional)"), max_chars=300, key="req_notes")
    if st.form_submit_button("Send request", type="primary"):
        try:
            services.request_service(farmer_id, kind, when, cow_id, semen_id, notes, vet_id=chosen)
        except ValueError as e:
            st.error(cap(e))
        else:
            st.success("Sent. You will see it here when the vet books a day.")
            st.rerun()

st.header("My requests")
rows = db.requests_for_farm(farmer_id)
if not rows:
    st.caption("No requests yet.")
for q in rows:
    when = q["scheduled_for"] or q["preferred_date"]
    with st.container(border=True):
        st.markdown(
            f"**{services.KINDS[q['kind']]}**" + (f" · {q['cow_tag']}" if q["cow_tag"] else "")
            + (f" · {md(q['vet_name'])}" if q["chosen_vet_id"] is not None and q["vet_name"] else "")
            + f" · {services.STATUS_WORDS[q['status']]}" + (f" ({when})" if q["status"] in ("open", "scheduled") else "")
        )
        if q["vaccine"]:
            st.caption(f"{q['vaccine']} · {q['animals']} animal{'s' if q['animals'] != 1 else ''}")
        if q["semen_name"]:
            st.caption(f"{q['semen_name']} · KES {float(q['semen_price_kes']):,.0f}")
        if q["status"] == "done" and q["vet_notes"]:
            st.caption(f"Vet's notes: {q['vet_notes']}")
        if q["status"] in ("open", "scheduled") and st.button("Cancel", key=f"cancel_{q['id']}"):
            try:
                services.cancel_request(q["id"], farmer_id)
            except ValueError as e:
                st.error(cap(e))
            else:
                st.rerun()

st.header("My vets")
st.caption("Use a vet who is not your route vet? Add them by their phone number. They need a Maziwa Plus vet login. "
           "Your milk buyer does not see requests you send to your own vets.")
mine = db.farm_vets(farmer_id)
for v in mine:
    c1, c2 = st.columns([4, 1])
    c1.write(md(v["name"]))
    if c2.button("Remove", key=f"drop_vet_{v['id']}"):
        db.remove_farm_vet(farmer_id, v["id"])
        st.rerun()
with st.form("add_vet", clear_on_submit=True):
    phone = st.text_input("Vet's phone number", placeholder="0712 345 678", key="vet_phone")
    if st.form_submit_button("Add vet"):
        try:
            services.add_own_vet(farmer_id, phone)
        except ValueError as e:
            st.error(cap(e))
        else:
            st.success("Added. You can now send requests to this vet.")
            st.rerun()
