"""Admin: routes, vets, which farm is on which route, and creating logins."""
import streamlit as st

from src import accounts, db
from src.auth import require_login
from src.ui import cap

st.set_page_config(page_title="Admin", page_icon="🥛", layout="centered")
admin_login = require_login(roles=("admin",))
if not accounts.is_head_admin(admin_login):
    st.error("Only the head admin can open this page.")
    st.stop()

st.title("Admin")
st.caption("Routes group farms; each route has one vet. Vets see only the farms on their routes.")


def attempt(action, done):
    """Run `action`; show `done` on success, the reason on a refusal."""
    try:
        action()
    except ValueError as e:
        st.error(cap(e))
        return False
    st.success(done)
    return True


routes = db.list_routes()
vets = db.list_users("vet")
farmers = db.list_farmers()

pending = db.list_pending_users()
st.header(f"Signups waiting ({len(pending)})")
if not pending:
    st.caption("Nobody is waiting.")
for u in pending:
    c1, c2, c3 = st.columns([4, 1, 1])
    c1.write(f"**{u['name']}** · {u['role']} · {u['phone'] or ''} {u['email'] or ''}" + (f" · {u['farm_name']}" if u["farm_name"] else ""))
    if c2.button("Approve", key=f"approve_{u['id']}"):
        if attempt(lambda uid=u["id"]: accounts.approve_signup(uid), f"Approved {u['name']}."):
            st.rerun()
    if c3.button("Reject", key=f"reject_{u['id']}"):
        accounts.reject_signup(u["id"])
        st.rerun()

st.header("Routes")
if routes:
    st.dataframe(
        [{"Route": r["code"], "Name": r["name"] or "", "Vet": r["vet_name"] or "none yet", "Farms": r["farms"]} for r in routes],
        hide_index=True, use_container_width=True,
    )
else:
    st.info("No routes yet. Add the real ones, or start with examples and rename them later.")
    if st.button("Add example routes (4A, 4B, 5A)", key="example_routes"):
        for code in ("4A", "4B", "5A"):
            accounts.record_route(code)
        st.rerun()

with st.form("add_route", clear_on_submit=True):
    c1, c2 = st.columns(2)
    code = c1.text_input("Route code", placeholder="4A", key="route_code")
    rname = c2.text_input("Name (optional)", placeholder="Tigoni north", key="route_name")
    if st.form_submit_button("Save route"):
        if attempt(lambda: accounts.record_route(code, rname or None), f"Saved route {code.strip().upper()}."):
            st.rerun()

if routes:
    st.subheader("Vet for a route")
    vet_ids = [None] + [v["id"] for v in vets]
    vet_names = {None: "no vet"} | {v["id"]: v["name"] for v in vets}
    with st.form("allocate_vet"):
        route_id = st.selectbox("Route", [r["id"] for r in routes], format_func={r["id"]: r["code"] for r in routes}.get, key="alloc_route")
        vet_id = st.selectbox("Vet", vet_ids, format_func=vet_names.get, key="alloc_vet")
        if st.form_submit_button("Allocate"):
            if attempt(lambda: accounts.allocate_vet(route_id, vet_id), "Vet allocated."):
                st.rerun()
    if not vets:
        st.caption("No vets yet: create a vet login below first.")

if farmers and routes:
    st.subheader("Farm on a route")
    route_label = {None: "no route"} | {r["id"]: r["code"] for r in routes}
    with st.form("assign_route"):
        farm_id = st.selectbox(
            "Farm", [f["id"] for f in farmers], key="assign_farm",
            format_func={f["id"]: f"{f['name']} ({route_label.get(f.get('route_id'), 'no route')})" for f in farmers}.get,
        )
        rid = st.selectbox("Route", list(route_label), format_func=route_label.get, key="assign_route")
        if st.form_submit_button("Assign"):
            if attempt(lambda: accounts.assign_route(farm_id, rid), "Route set."):
                st.rerun()

st.header("Logins")
users = db.list_users()
if users:
    st.dataframe(
        [{"Name": u["name"], "Role": u["role"], "Phone": u["phone"] or "", "Email": u["email"] or "",
          "Active": u["active"], "Locked": bool(u["locked_until"])} for u in users],
        hide_index=True, use_container_width=True,
    )

st.subheader("Create a login")
st.caption(
    "Give a phone number for SMS-code login, and/or an email with a temporary password "
    "(they must choose their own at first login). Tell them the temporary password in person or by call, never in this app."
)
with st.form("create_account", clear_on_submit=True):
    role = st.selectbox("Role", ["farmer", "vet", "admin", "route admin"], key="new_role",
                        help="A route admin sees and notifies only the routes you give them.")
    nm = st.text_input("Name", key="new_name")
    ph = st.text_input("Phone", placeholder="0712 345 678", key="new_phone")
    em = st.text_input("Email (for password login)", key="new_email")
    tp = st.text_input("Temporary password", type="password", key="new_temp")
    farm_choices = [None] + [f["id"] for f in farmers]
    farm_names = {None: "(vets and admins: none)"} | {f["id"]: f"{f['name']} ({f['farm_name'] or f['phone']})" for f in farmers}
    farm = st.selectbox("Farm (farmers only)", farm_choices, format_func=farm_names.get, key="new_farm")
    route_names = {r["id"]: r["code"] for r in routes}
    new_routes = st.multiselect("Routes (route admins only)", list(route_names), format_func=route_names.get, key="new_routes")
    if st.form_submit_button("Create login", type="primary"):
        attempt(
            lambda: accounts.create_account("admin" if role == "route admin" else role, nm, ph or None, em or None, tp or None, farm,
                                            route_ids=new_routes if role == "route admin" else None),
            f"Created the {role} login for {nm.strip()}.",
        )

route_admins = [u for u in users if u["role"] == "admin" and u["route_admin"]]
if route_admins:
    st.subheader("Routes for a route admin")
    with st.form("route_admin_routes"):
        ra = st.selectbox("Route admin", [u["id"] for u in route_admins], format_func={u["id"]: u["name"] for u in route_admins}.get, key="ra_user")
        picked = st.multiselect("Routes they look after", [r["id"] for r in routes], default=sorted(db.admin_route_ids(route_admins[0]["id"])),
                                format_func={r["id"]: r["code"] for r in routes}.get, key="ra_routes")
        if st.form_submit_button("Save routes"):
            if attempt(lambda: accounts.set_route_admin_routes(admin_login, ra, picked), "Saved."):
                st.rerun()

st.subheader("Switch a login off or on")
if users:
    with st.form("toggle_user"):
        uid = st.selectbox("Login", [u["id"] for u in users], format_func={u["id"]: f"{u['name']} ({u['role']})" for u in users}.get, key="toggle_user_id")
        on = st.radio("Status", ["Active", "Switched off"], horizontal=True, key="toggle_status")
        if st.form_submit_button("Save"):
            db.update_user(uid, active=(on == "Active"))
            st.success("Saved.")
            st.rerun()


st.header("Delete")
st.caption("Deleting cannot be undone. Each one asks you to type DELETE.")
admin_user = st.session_state["user"]

with st.expander("Delete a login"):
    st.caption("Removes the login only. A farmer's farm and records stay; use 'Delete a farm' to remove those as well.")
    users_now = db.list_users()
    with st.form("delete_login"):
        did = st.selectbox("Login", [u["id"] for u in users_now],
                           format_func={u["id"]: f"{u['name']} ({u['role']})" for u in users_now}.get, key="del_login_id")
        conf = st.text_input("Type DELETE to confirm", key="del_login_confirm")
        if st.form_submit_button("Delete login") and attempt(lambda: accounts.admin_delete_login(admin_user, did, conf), "Login deleted."):
            st.rerun()

with st.expander("Delete a farm and all its records"):
    farms_now = db.list_farmers(active_only=False)
    if not farms_now:
        st.caption("No farms.")
    else:
        with st.form("delete_farm"):
            fid = st.selectbox("Farm", [f["id"] for f in farms_now],
                               format_func={f["id"]: f"{f['name']} ({f['farm_name'] or f['phone']})" for f in farms_now}.get, key="del_farm_id")
            conf = st.text_input("Type DELETE to confirm", key="del_farm_confirm")
            if st.form_submit_button("Delete farm and records") and attempt(lambda: accounts.admin_delete_farm(admin_user, fid, conf), "Farm deleted."):
                st.rerun()

with st.expander("Delete a route"):
    st.caption("Its farms stay, without a route. Alerts and vaccination days posted for that route are deleted.")
    routes_now = db.list_routes()
    if not routes_now:
        st.caption("No routes.")
    else:
        with st.form("delete_route"):
            rid = st.selectbox("Route", [r["id"] for r in routes_now], format_func={r["id"]: r["code"] for r in routes_now}.get, key="del_route_id")
            conf = st.text_input("Type DELETE to confirm", key="del_route_confirm")
            if st.form_submit_button("Delete route") and attempt(lambda: accounts.admin_delete_route(admin_user, rid, conf), "Route deleted."):
                st.rerun()


st.header("Messages from the Contact us form")
msgs = db.list_contact_messages(30)
if not msgs:
    st.caption("No messages.")
for m in msgs:
    with st.container(border=True):
        st.markdown(f"**{m['name']}** · {m['contact']}" + (" · handled" if m["handled"] else ""))
        st.text(m["message"])  # shown as plain text, whatever the visitor typed
        c1, c2 = st.columns(2)
        if c1.button("Mark handled" if not m["handled"] else "Mark not handled", key=f"msg_h_{m['id']}"):
            db.set_message_handled(m["id"], not m["handled"])
            st.rerun()
        if c2.button("Delete", key=f"msg_d_{m['id']}"):
            db.delete_contact_message(m["id"])
            st.rerun()
