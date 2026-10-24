"""Vaccination days: admins and vets post them, farmers book their animals."""
from datetime import date, timedelta

import streamlit as st

from src import db, services, vaccinations
from src.auth import require_login
from src.ui import cap, farmer_selector

st.set_page_config(page_title="Vaccination", page_icon="🥛", layout="centered")
user = require_login()
is_farmer = user["role"] == "farmer"
farmer_id = farmer_selector() if is_farmer else None

st.title("Vaccination days")


def attempt(action, done):
    try:
        result = action()
    except ValueError as e:
        st.error(cap(e))
        return None
    st.success(done)
    return result if result is not None else True


if not is_farmer:
    routes = db.list_routes() if user["role"] == "admin" else [r for r in db.list_routes() if r["vet_user_id"] == user["id"]]
    if user["role"] == "vet" and not routes:
        st.info("You have no route yet, so you can't post vaccination days. Ask the admin.")
    else:
        choices = ([None] if user["role"] == "admin" else []) + [r["id"] for r in routes]
        labels = {None: "All routes"} | {r["id"]: f"Route {r['code']}" for r in routes}
        with st.expander("Post a vaccination day"):
            with st.form("post_day", clear_on_submit=True):
                vaccine = st.text_input("Vaccine", max_chars=vaccinations.MAX_VACCINE, placeholder="Foot and mouth", key="vac_name")
                when = st.date_input("Day", value=date.today() + timedelta(days=7), key="vac_day")
                route_id = st.selectbox("Route", choices, format_func=labels.get, key="vac_route")
                place = st.text_input("Place (optional)", max_chars=vaccinations.MAX_PLACE, placeholder="Tigoni market", key="vac_place")
                notes = st.text_input("Note (optional)", max_chars=vaccinations.MAX_NOTES, key="vac_notes")
                announce = st.checkbox("Also post a notice to the route's farmers (you can text it from the Alerts page)", value=True, key="vac_announce")
                if st.form_submit_button("Post", type="primary"):
                    if attempt(lambda: vaccinations.post_day(user, vaccine, when, route_id, place, notes, announce), "Posted."):
                        st.rerun()

days = vaccinations.days_for(user)
if not days:
    st.info("No vaccination days coming up.")
for d in days:
    with st.container(border=True):
        where = f"Route {d['route_code']}" if d["route_code"] else "All routes"
        st.markdown(f"**{d['vaccine']}** · {d['day']:%A %d %b}")
        st.caption(where + (f" · {d['place']}" if d["place"] else "") + (f" · {d['notes']}" if d["notes"] else ""))
        if is_farmer:
            mine = vaccinations.my_booking(farmer_id, d["id"])
            if mine:
                st.success(f"You booked {mine['animals']} animal{'s' if mine['animals'] != 1 else ''}.")
                if st.button("Cancel my booking", key=f"unbook_{d['id']}"):
                    if attempt(lambda m=mine: services.cancel_request(m["id"], farmer_id), "Cancelled."):
                        st.rerun()
            else:
                with st.form(f"book_{d['id']}"):
                    n = st.number_input("How many animals", min_value=1, max_value=vaccinations.MAX_ANIMALS, value=1, step=1, key=f"animals_{d['id']}")
                    if st.form_submit_button("Book", type="primary"):
                        if attempt(lambda d=d, n=n: vaccinations.book(farmer_id, d["id"], int(n)), "Booked. Your vet will see it."):
                            st.rerun()
        else:
            st.write(f"{d['bookings']} farm(s) booked · {d['animals']} animal(s)")
            rows = db.bookings_for_day(d["id"])
            if rows:
                st.dataframe([{"Farm": r["farm_name"] or r["farmer_name"], "Animals": r["animals"]} for r in rows], hide_index=True, use_container_width=True)
            if st.button("Cancel this day", key=f"cancel_day_{d['id']}"):
                if attempt(lambda d=d: vaccinations.cancel_day(user, d["id"]), "Cancelled. Booked farms will see it as cancelled."):
                    st.rerun()
