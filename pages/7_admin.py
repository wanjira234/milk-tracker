"""Admin: sign-ups, routes, vets, farms on routes and logins, for this admin's organisation.
The platform owner also creates organisations and decides which routes belong to which."""
import streamlit as st

from src.messages import ICON

from src import accounts, db, orgs
from src.auth import require_login
from src.ui import cap, md

st.set_page_config(page_title="Admin", page_icon=ICON, layout="centered")
admin_login = require_login(roles=("admin",))
if not accounts.is_head_admin(admin_login):
    st.error("Only a head admin (an organisation's admin or the platform owner) can open this page.")
    st.stop()

owner = orgs.is_platform_owner(admin_login)
org = db.get_org(admin_login["org_id"]) if admin_login.get("org_id") else None
st.title("Admin")
st.caption("Platform owner: every organisation, route and login." if owner
           else f"{md(org['name'] if org else 'Your organisation')}: only your routes, their farms and vets, and your logins.")


def attempt(action, done):
    """Run `action`; show `done` on success, the reason on a refusal."""
    try:
        action()
    except ValueError as e:
        st.error(cap(e))
        return False
    st.success(done)
    return True


routes = orgs.routes_for(admin_login)
vets = [v for v in db.list_users("vet") if v["active"]]
farmers = orgs.farms_to_place(admin_login)
users = orgs.users_for(admin_login)
all_orgs = db.list_orgs()

t_signups, t_routes, t_logins, t_orgs, t_delete = st.tabs(
    ["Sign-ups", "Routes & farms", "Logins", "Organisations" if owner else "About", "Delete"])

with t_signups:
    pending = orgs.pending_for(admin_login)
    st.subheader(f"Waiting for approval ({len(pending)})")
    if not pending:
        st.caption("Nobody is waiting." + ("" if owner else " Farmers who choose your organisation at sign-up appear here."))
    for u in pending:
        c1, c2, c3 = st.columns([4, 1, 1])
        c1.write(f"**{md(u['name'])}** · {u['role']} · {u['phone'] or ''} {md(u['email'] or '')}"
                 + (f" · {md(u['farm_name'])}" if u["farm_name"] else ""))
        if c2.button("Approve", key=f"approve_{u['id']}"):
            if attempt(lambda uid=u["id"]: orgs.approve(admin_login, uid), f"Approved {u['name']}. Put their farm on a route next."):
                st.rerun()
        if c3.button("Reject", key=f"reject_{u['id']}"):
            if attempt(lambda uid=u["id"]: orgs.reject(admin_login, uid), "Rejected."):
                st.rerun()

with t_routes:
    st.subheader("Routes")
    if routes:
        st.dataframe(
            [{"Route": r["code"], "Name": r["name"] or "", "Vet": r["vet_name"] or "none yet", "Farms": r["farms"]}
             | ({"Organisation": r["org_name"] or "none"} if owner else {}) for r in routes],
            hide_index=True, use_container_width=True,
        )
    else:
        st.info("No routes yet. Add the real ones below, or start with examples and rename them later.")
        if st.button("Add example routes (4A, 4B, 5A)", key="example_routes"):
            for code in ("4A", "4B", "5A"):
                orgs.add_route(admin_login, code)
            st.rerun()
    with st.form("add_route", clear_on_submit=True):
        c1, c2 = st.columns(2)
        code = c1.text_input("Route code", placeholder="4A", key="route_code")
        rname = c2.text_input("Name (optional)", placeholder="Tigoni north", key="route_name")
        if st.form_submit_button("Save route"):
            if attempt(lambda: orgs.add_route(admin_login, code, rname or None), f"Saved route {code.strip().upper()}."):
                st.rerun()

    if routes:
        st.subheader("Vet for a route")
        vet_ids = [None] + [v["id"] for v in vets]
        vet_names = {None: "no vet"} | {v["id"]: v["name"] for v in vets}
        with st.form("allocate_vet"):
            route_id = st.selectbox("Route", [r["id"] for r in routes], format_func={r["id"]: r["code"] for r in routes}.get, key="alloc_route")
            vet_id = st.selectbox("Vet", vet_ids, format_func=vet_names.get, key="alloc_vet")
            if st.form_submit_button("Allocate"):
                if attempt(lambda: orgs.allocate_vet(admin_login, route_id, vet_id), "Vet allocated."):
                    st.rerun()
        if not vets:
            st.caption("No vets yet. Vets sign up themselves, or the platform owner adds them.")

    if farmers and routes:
        st.subheader("Farm on a route")
        route_label = {None: "no route"} | {r["id"]: r["code"] for r in routes}
        all_route_label = {r["id"]: r["code"] for r in db.list_routes()}
        with st.form("assign_route"):
            farm_id = st.selectbox(
                "Farm", [f["id"] for f in farmers], key="assign_farm",
                format_func={f["id"]: f"{f['name']} ({all_route_label.get(f.get('route_id'), 'no route')})" for f in farmers}.get,
            )
            rid = st.selectbox("Route", list(route_label), format_func=route_label.get, key="assign_route")
            if st.form_submit_button("Assign"):
                if attempt(lambda: orgs.assign_route(admin_login, farm_id, rid), "Route set."):
                    st.rerun()

with t_logins:
    if users:
        st.dataframe(
            [{"Name": u["name"], "Role": u["role"] + (" (store)" if u["role"] == "agrovet" and u.get("org_id") else ""),
              "Phone": u["phone"] or "", "Email": u["email"] or "", "Active": u["active"], "Locked": bool(u["locked_until"])}
             for u in users],
            hide_index=True, use_container_width=True,
        )
    st.subheader("Create a login")
    st.caption("Give a phone number for SMS-code login, and/or an email with a temporary password "
               "(they must choose their own at first login). Tell them the temporary password in person or by call.")
    roles = (["farmer", "vet", "agrovet", "admin", "route admin"] if owner
             else ["farmer", "agrovet", "admin", "route admin"])
    role_help = "A route admin sees only the routes you give them." + ("" if owner else " An agrovet you create is your organisation's own store, "
                                                                        "the only shop your farmers can pay through their milk money.")
    with st.form("create_account", clear_on_submit=True):
        role = st.selectbox("Role", roles, key="new_role", help=role_help)
        nm = st.text_input("Name", key="new_name")
        ph = st.text_input("Phone", placeholder="0712 345 678", key="new_phone")
        em = st.text_input("Email (for password login)", key="new_email")
        tp = st.text_input("Temporary password", type="password", key="new_temp")
        farm_choices = [None] + [f["id"] for f in farmers]
        farm_names = {None: "(not a farmer: none)"} | {f["id"]: f"{f['name']} ({f['farm_name'] or f['phone']})" for f in farmers}
        farm = st.selectbox("Farm (farmers only)", farm_choices, format_func=farm_names.get, key="new_farm")
        route_names = {r["id"]: r["code"] for r in routes}
        new_routes = st.multiselect("Routes (route admins only)", list(route_names), format_func=route_names.get, key="new_routes")
        if st.form_submit_button("Create login", type="primary"):
            attempt(
                lambda: orgs.create_login(admin_login, "admin" if role == "route admin" else role, nm, ph or None, em or None, tp or None,
                                          farm, route_ids=new_routes if role == "route admin" else None),
                f"Created the {role} login for {nm.strip()}.",
            )

    route_admins = [u for u in users if u["role"] == "admin" and u["route_admin"]]
    if route_admins:
        st.subheader("Routes for a route admin")
        with st.form("route_admin_routes"):
            ra = st.selectbox("Route admin", [u["id"] for u in route_admins], format_func={u["id"]: u["name"] for u in route_admins}.get, key="ra_user")
            picked = st.multiselect("Routes they look after", [r["id"] for r in routes],
                                    default=sorted(db.admin_route_ids(route_admins[0]["id"]) & {r["id"] for r in routes}),
                                    format_func={r["id"]: r["code"] for r in routes}.get, key="ra_routes")
            if st.form_submit_button("Save routes"):
                if attempt(lambda: orgs.set_route_admin_routes(admin_login, ra, picked), "Saved."):
                    st.rerun()

    if users:
        st.subheader("Switch a login off or on")
        with st.form("toggle_user"):
            uid = st.selectbox("Login", [u["id"] for u in users], format_func={u["id"]: f"{u['name']} ({u['role']})" for u in users}.get, key="toggle_user_id")
            on = st.radio("Status", ["Active", "Switched off"], horizontal=True, key="toggle_status")
            if st.form_submit_button("Save"):
                if attempt(lambda: orgs.set_active(admin_login, uid, on == "Active"), "Saved."):
                    st.rerun()
        with st.expander("Someone lost their phone? Reset their two-factor login"):
            with st.form("reset_totp"):
                rid = st.selectbox("Login", [u["id"] for u in users], format_func={u["id"]: f"{u['name']} ({u['role']})" for u in users}.get, key="reset_totp_id")
                if st.form_submit_button("Switch off their two-factor"):
                    attempt(lambda: orgs.reset_two_factor(admin_login, rid),
                            "Done. They can log in with their password and set it up again.")

with t_orgs:
    if not owner:
        st.write(f"You are an admin of **{md(org['name'] if org else 'your organisation')}**. You see only its routes, the farms on them, "
                 "the vets allocated to them, and its own logins. Other organisations can't see yours.")
    else:
        st.caption("Each milk buyer or co-op is an organisation. Its admins see only its routes; you see everything.")
        if all_orgs:
            st.dataframe([{"Organisation": o["name"], "Routes": o["routes"]} for o in all_orgs], hide_index=True, use_container_width=True)
        with st.form("add_org", clear_on_submit=True):
            oname = st.text_input("New organisation", placeholder="Fresha (Githunguri Dairy)", key="org_name")
            if st.form_submit_button("Add organisation"):
                if attempt(lambda: orgs.create_org(admin_login, oname), "Added."):
                    st.rerun()
        if all_orgs:
            org_names = {None: "none"} | {o["id"]: o["name"] for o in all_orgs}
            if routes:
                with st.form("route_org"):
                    c1, c2 = st.columns(2)
                    r_id = c1.selectbox("Route", [r["id"] for r in routes], key="ro_route",
                                        format_func={r["id"]: f"{r['code']} (now: {r['org_name'] or 'none'})" for r in routes}.get)
                    o_id = c2.selectbox("Belongs to", list(org_names), format_func=org_names.get, key="ro_org")
                    if st.form_submit_button("Save"):
                        if attempt(lambda: orgs.move_route(admin_login, r_id, o_id), "Saved."):
                            st.rerun()
            staff = [u for u in users if u["role"] in ("admin", "agrovet") and u["id"] != admin_login.get("id")]
            if staff:
                st.caption("Make an admin login an organisation's admin, or an agrovet its own store.")
                with st.form("login_org"):
                    c1, c2 = st.columns(2)
                    s_id = c1.selectbox("Login", [u["id"] for u in staff], key="lo_user",
                                        format_func={u["id"]: f"{u['name']} ({u['role']}, now: {org_names.get(u.get('org_id'), 'none')})"
                                                     for u in staff}.get)
                    o_id = c2.selectbox("Organisation", list(org_names), format_func=org_names.get, key="lo_org")
                    if st.form_submit_button("Save"):
                        if attempt(lambda: orgs.set_login_org(admin_login, s_id, o_id), "Saved."):
                            st.rerun()
        st.subheader("Messages from the Contact us form")
        msgs = db.list_contact_messages(30)
        if not msgs:
            st.caption("No messages.")
        for m in msgs:
            with st.container(border=True):
                st.markdown(f"**{md(m['name'])}** · {md(m['contact'])}" + (" · handled" if m["handled"] else ""))
                st.text(m["message"])  # shown as plain text, whatever the visitor typed
                c1, c2 = st.columns(2)
                if c1.button("Mark handled" if not m["handled"] else "Mark not handled", key=f"msg_h_{m['id']}"):
                    db.set_message_handled(m["id"], not m["handled"])
                    st.rerun()
                if c2.button("Delete", key=f"msg_d_{m['id']}"):
                    db.delete_contact_message(m["id"])
                    st.rerun()

with t_delete:
    st.caption("Deleting cannot be undone. Each one asks you to type DELETE.")
    with st.expander("Delete a login"):
        st.caption("Removes the login only. A farmer's farm and records stay; use 'Delete a farm' to remove those as well.")
        if users:
            with st.form("delete_login"):
                did = st.selectbox("Login", [u["id"] for u in users], format_func={u["id"]: f"{u['name']} ({u['role']})" for u in users}.get,
                                   key="del_login_id")
                conf = st.text_input("Type DELETE to confirm", key="del_login_confirm")
                if st.form_submit_button("Delete login") and attempt(lambda: orgs.delete_login(admin_login, did, conf), "Login deleted."):
                    st.rerun()
    with st.expander("Delete a farm and all its records"):
        if not farmers:
            st.caption("No farms.")
        else:
            with st.form("delete_farm"):
                fid = st.selectbox("Farm", [f["id"] for f in farmers],
                                   format_func={f["id"]: f"{f['name']} ({f['farm_name'] or f['phone']})" for f in farmers}.get, key="del_farm_id")
                conf = st.text_input("Type DELETE to confirm", key="del_farm_confirm")
                if st.form_submit_button("Delete farm and records") and attempt(lambda: orgs.delete_farm(admin_login, fid, conf), "Farm deleted."):
                    st.rerun()
    with st.expander("Delete a route"):
        st.caption("Its farms stay, without a route. Alerts and vaccination days posted for that route are deleted.")
        if not routes:
            st.caption("No routes.")
        else:
            with st.form("delete_route"):
                rid = st.selectbox("Route", [r["id"] for r in routes], format_func={r["id"]: r["code"] for r in routes}.get, key="del_route_id")
                conf = st.text_input("Type DELETE to confirm", key="del_route_confirm")
                if st.form_submit_button("Delete route") and attempt(lambda: orgs.delete_route(admin_login, rid, conf), "Route deleted."):
                    st.rerun()
