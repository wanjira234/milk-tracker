"""Vet: today's visits, what to carry, requests waiting for a day, and my semen list with prices."""
from datetime import date, timedelta

import streamlit as st

from src.messages import ICON

from src import db, ledger, services
from src.auth import require_login
from src.ui import cap

st.set_page_config(page_title="My day", page_icon=ICON, layout="centered")
user = require_login(roles=("vet",))

st.title("My day")


def attempt(action, done):
    try:
        action()
    except ValueError as e:
        st.error(cap(e))
        return False
    st.success(done)
    return True


mine = [r for r in db.list_routes() if r["vet_user_id"] == user["id"]]
if mine:
    st.caption("Your routes: " + ", ".join(f"{r['code']} ({r['farms']} farm{'s' if r['farms'] != 1 else ''})" for r in mine))
else:
    st.info("No route is allocated to you. Farmers who add you as their vet can still send you requests.")

day = st.date_input("Day", value=date.today(), key="day")
sheet = services.day_sheet(user, day)
m1, m2 = st.columns(2)
m1.metric("Visits", sheet["total"])
m2.metric("Done", sheet["done"])
if sheet["carry"]:
    st.subheader("Carry")
    for line in sheet["carry"]:
        st.write(f"- {line}")

my_semen = db.list_vet_semen(user["id"])
for farm in sheet["farms"]:
    st.subheader(f"{farm['farm']}" + (f" · route {farm['route']}" if farm["route"] else ""))
    if farm["phone"]:
        st.caption(farm["phone"])
    for q in farm["visits"]:
        label = services.KINDS[q["kind"]] + (f" · {q['cow_tag']}" if q["cow_tag"] else "")
        with st.container(border=True):
            st.markdown(f"**{label}**" + (" · done" if q["status"] == "done" else ""))
            if q["vaccine"]:
                st.write(f"{q['vaccine']}: {q['animals']} animal{'s' if q['animals'] != 1 else ''}")
            elif q["notes"]:
                st.write(q["notes"])
            if q["semen_name"]:
                st.caption(f"Farmer chose {q['semen_name']} (KES {float(q['semen_price_kes']):,.0f})")
            if q["status"] == "done":
                if q["vet_notes"]:
                    st.caption(f"Your notes: {q['vet_notes']}")
                continue
            with st.form(f"done_{q['id']}"):
                semen_id = None
                if q["kind"] == "ai":
                    names = {s["id"]: f"{s['name']} (KES {float(s['price_kes']):,.0f})" for s in my_semen}
                    ids = list(names)
                    start = ids.index(q["semen_id"]) if q["semen_id"] in ids else None
                    semen_id = st.selectbox("Semen used", ids, index=start, format_func=names.get,
                                            placeholder="Choose semen", key=f"used_{q['id']}")
                notes = st.text_input("Notes (optional)", key=f"notes_{q['id']}")
                st.caption("Bill (optional). Leave blank what you don't charge."
                           + (" The semen is billed at the agreed price." if q["kind"] == "ai" else ""))
                b1, b2 = st.columns(2)
                fee = b1.text_input("Visit fee (KES)", key=f"fee_{q['id']}")
                drugs = b2.text_input("Drugs (KES)", key=f"drugs_{q['id']}")
                drug_note = st.text_input("Drugs given (optional)", key=f"drugnote_{q['id']}")
                options = list(ledger.TERMS) if q["chosen_vet_id"] is None else ["credit", "paid"]
                default = services.default_terms(q)
                terms = st.radio("Payment", options, index=options.index(default), format_func=ledger.TERMS.get,
                                 horizontal=True, key=f"terms_{q['id']}")
                t1, t2 = st.columns(2)
                due = t1.date_input("Due by (if on credit)", value=date.today() + timedelta(days=ledger.DEFAULT_CREDIT_DAYS),
                                    key=f"due_{q['id']}")
                method = t2.selectbox("Paid by (if paid now)", list(ledger.METHODS), format_func=ledger.METHODS.get,
                                      key=f"method_{q['id']}")
                ref = st.text_input("M-Pesa code (optional)", key=f"ref_{q['id']}")
                if st.form_submit_button("Mark done", type="primary"):
                    lines = [("vet_visit", fee, None), ("drugs", drugs, drug_note)]
                    if attempt(lambda q=q, s=semen_id, n=notes, ln=lines, t=terms, d=due, m=method, r=ref:
                               services.complete_request(q["id"], user, n, s, lines=ln, terms=t,
                                                         due_on=d if t == "credit" else None,
                                                         method=m if t == "paid" else None,
                                                         reference=r if t == "paid" else None), "Marked done."):
                        st.rerun()

if not sheet["farms"]:
    st.caption("No visits booked for this day.")

st.header("Waiting for a day")
inbox = services.inbox(user)
if not inbox:
    st.caption("Nothing is waiting.")
for q in inbox:
    with st.container(border=True):
        st.markdown(
            f"**{q['farm_name'] or q['farmer_name']}** · {services.KINDS[q['kind']]}"
            + (f" · {q['cow_tag']}" if q["cow_tag"] else "") + f" · wanted {q['preferred_date']}"
        )
        if q["notes"]:
            st.write(q["notes"])
        c1, c2 = st.columns([3, 1])
        pick = c1.date_input("Visit on", value=max(q["preferred_date"], date.today()), key=f"book_day_{q['id']}")
        if c2.button("Book", key=f"book_{q['id']}"):
            if attempt(lambda q=q, p=pick: services.schedule_request(q["id"], user, p), "Booked."):
                st.rerun()

st.header("My semen list")
st.caption("Farmers choose from this list and see the price. On your routes the milk buyer deducts it from the "
           "monthly milk payment; farmers who chose you themselves pay you directly.")
with st.form("add_semen", clear_on_submit=True):
    c1, c2 = st.columns([3, 1])
    nm = c1.text_input("Bull name or breed", placeholder="Friesian - Kamau", key="semen_name")
    pr = c2.text_input("Price (KES)", key="semen_price")
    if st.form_submit_button("Add or update"):
        if attempt(lambda: services.record_vet_semen(user, nm, pr), "Saved."):
            st.rerun()
if my_semen:
    st.dataframe([{"Semen": s["name"], "Price (KES)": float(s["price_kes"])} for s in my_semen], hide_index=True, use_container_width=True)
    with st.form("retire_semen"):
        drop = st.selectbox("Stop offering", [s["id"] for s in my_semen], format_func={s["id"]: s["name"] for s in my_semen}.get,
                            index=None, placeholder="Choose semen", key="retire_pick")
        if st.form_submit_button("Remove") and drop is not None:
            db.retire_vet_semen(user["id"], drop)
            st.rerun()
