"""Alerts: outbreaks and notices for farmers, sent by admins and vets, with the SMS outbox underneath."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from src import accounts, alerts, db, sms
from src.auth import require_login
from src.ui import cap

st.set_page_config(page_title="Alerts", page_icon="🥛", layout="centered")
user = require_login()
TZ = ZoneInfo("Africa/Nairobi")
can_post = user["role"] in ("admin", "vet")

st.title("Alerts")


def attempt(action, done):
    try:
        result = action()
    except ValueError as e:
        st.error(cap(e))
        return None
    st.success(done)
    return result if result is not None else True


if can_post:
    scope = accounts.admin_scope(user)  # None: every route (head admin); else a route admin's routes
    routes = ([r for r in db.list_routes() if scope is None or r["id"] in scope] if user["role"] == "admin"
              else [r for r in db.list_routes() if r["vet_user_id"] == user["id"]])
    if user["role"] == "vet" and not routes:
        st.info("You have no route yet, so you can't send alerts. Ask the admin.")
    else:
        choices = ([None] if user["role"] == "admin" and scope is None else []) + [r["id"] for r in routes]
        labels = {None: "All routes"} | {r["id"]: f"Route {r['code']}" for r in routes}
        with st.expander("New alert", expanded=False):
            with st.form("new_alert", clear_on_submit=True):
                kind = st.radio("Type", list(alerts.KINDS), format_func=alerts.KINDS.get, horizontal=True, key="alert_kind")
                title = st.text_input("Title", max_chars=alerts.MAX_TITLE, placeholder="Foot and mouth near Tigoni", key="alert_title")
                body = st.text_area("What farmers should know or do", max_chars=alerts.MAX_BODY, key="alert_body")
                route_id = st.selectbox("Who gets it", choices, format_func=labels.get, key="alert_route")
                days = st.number_input("Keep it visible for (days)", min_value=1, max_value=365, value=14, key="alert_days")
                if st.form_submit_button("Post alert", type="primary"):
                    if attempt(lambda: alerts.post_alert(user, kind, title, body, route_id, date.today() + timedelta(days=int(days))),
                               "Posted. Farmers can see it now. You can also text it below."):
                        st.rerun()

shown = alerts.visible_alerts(user)
if not shown:
    st.info("No alerts right now.")
for a in shown:
    with st.container(border=True):
        where = f"Route {a['route_code']}" if a["route_code"] else "All routes"
        st.markdown(f"**{alerts.KINDS[a['kind']]}: {a['title']}**")
        st.write(a["body"])
        st.caption(f"{where} · {a['author'] or 'admin'} · {a['created_at'].astimezone(TZ):%d %b %H:%M}")
        if a["sms_sent_at"]:
            st.caption(f"Texted to {a['sms_ok']} farm(s)" + (f", {a['sms_failed']} failed" if a["sms_failed"] else ""))
        elif alerts.can_send(user, a):
            text = alerts.sms_text(a["kind"], a["title"], a["body"])
            problem = alerts.sms_problem(text)
            farms = len(db.farmers_for_alert(a["route_id"]))
            if problem:
                st.warning(f"This can't be texted: it {problem}.")
            else:
                st.caption(f"SMS preview ({sms.sms_segments(text)} segment(s)): {text}")
                sure = st.checkbox(f"Yes, text this to {farms} farm(s) now", key=f"sure_{a['id']}")
                if st.button("Send SMS", key=f"sms_{a['id']}", disabled=not sure or farms == 0):
                    result = attempt(lambda a=a: alerts.send_alert_sms(a["id"], user), "Sent.")
                    if result:
                        st.rerun()

st.header("Messages sent" if user["role"] != "farmer" else "Texts we sent you")
st.caption("Every SMS the system sends is kept here, so you can see exactly what a farmer received.")
box = alerts.outbox(user)
if not box:
    st.caption("Nothing sent yet.")
for m in box:
    with st.container(border=True):
        who = f"To {m['farmer_name']} · " if user["role"] != "farmer" else ""
        st.caption(f"{who}{m['sent_at'].astimezone(TZ):%d %b %H:%M} · {m['kind']} · {m['status']}")
        st.write(m["body"])
