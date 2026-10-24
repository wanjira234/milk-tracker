"""Admin: did each vet attend the day's tickets?"""
from datetime import date

import streamlit as st

from src.messages import ICON

from src import accounts, services
from src.auth import require_login

st.set_page_config(page_title="Attendance", page_icon=ICON, layout="centered")
user = require_login(roles=("admin",))

st.title("Vet attendance")
day = st.date_input("Day", value=date.today(), key="att_day")
view = services.attendance(day, accounts.admin_scope(user))


def line(q):
    return (f"{q['farm_name'] or q['farmer_name']} · {services.KINDS[q['kind']]}"
            + (f" · {q['cow_tag']}" if q["cow_tag"] else "") + f" · due {q['scheduled_for'] or q['preferred_date']}")


if not view["vets"] and not view["unattended"]:
    st.info("No requests yet.")
if view["vets"]:
    st.dataframe(
        [{"Vet": v["vet"], "Booked today": v["booked_today"], "Done": v["done_today"],
          "Still to do today": len(v["to_do_today"]), "Late": len(v["late"]), "Waiting for a day": v["waiting"]} for v in view["vets"]],
        hide_index=True, use_container_width=True,
    )
for v in view["vets"]:
    if v["to_do_today"] or v["late"]:
        st.subheader(v["vet"])
        for q in v["to_do_today"]:
            st.write(f"- To do today: {line(q)}")
        for q in v["late"]:
            st.write(f"- **Late**: {line(q)}")
if view["unattended"]:
    st.subheader("Nobody is answering these")
    st.caption("These farms have no route or their route has no vet. Fix it on the admin page.")
    for q in view["unattended"]:
        st.write(f"- {line(q)}")
