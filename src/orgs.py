"""Organisations: each milk buyer or co-op (Fresha, another co-op) runs its own routes.

  - The platform owner (an admin with no organisation, or the owner-password login) sees and runs everything,
    and is the only one who creates organisations and moves routes between them.
  - An organisation's admin sees and runs only its own routes, the farms on them, the vets allocated to them,
    its own logins (its admins and its store), and sign-ups that chose it. Every action is checked here,
    on the server side, not only by what the page lists.
  - An agrovet that belongs to an organisation is that buyer's own store: the only kind of shop that may take
    payment from a farm's milk money, and only for farms on that buyer's routes.
"""
from src import accounts, db


def org_of(user):
    return (user or {}).get("org_id")


def is_platform_owner(user):
    return bool(user) and user.get("role") == "admin" and not user.get("route_admin") and org_of(user) is None


def _need_owner(actor):
    if not is_platform_owner(actor):
        raise ValueError("only the platform owner can do that")


def create_org(actor, name):
    _need_owner(actor)
    name = " ".join(str(name or "").split())
    if not name or len(name) > 80:
        raise ValueError("enter the organisation's name")
    return db.add_org(name)


def move_route(actor, route_id, org_id):
    """Put a route under an organisation (or none)."""
    _need_owner(actor)
    if route_id not in {r["id"] for r in db.list_routes()}:
        raise ValueError("choose a route")
    if org_id is not None and not db.get_org(org_id):
        raise ValueError("choose an organisation")
    db.set_route_org(route_id, org_id)


def set_login_org(actor, user_id, org_id):
    """Make a login an organisation's admin or its store (or take it out of one)."""
    _need_owner(actor)
    u = db.get_user(user_id)
    if not u or u["role"] not in ("admin", "agrovet"):
        raise ValueError("only an admin or an agrovet login belongs to an organisation")
    if org_id is not None and not db.get_org(org_id):
        raise ValueError("choose an organisation")
    db.set_user_org(user_id, org_id)


# --- what an admin may see and act on -------------------------------------------------------------


def routes_for(actor):
    scope = accounts.admin_scope(actor)
    return [r for r in db.list_routes() if scope is None or r["id"] in scope]


def farms_for(actor):
    return accounts.visible_farmers(actor) if actor.get("role") == "admin" else []


def users_for(actor):
    """Logins this admin may see and manage."""
    everyone = db.list_users()
    if is_platform_owner(actor):
        return everyone
    routes = routes_for(actor)
    route_ids = {r["id"] for r in routes}
    vets = {r["vet_user_id"] for r in routes if r["vet_user_id"]}
    farms = {f["id"] for f in db.farmers_on_routes(route_ids)} if route_ids else set()
    org = org_of(actor)
    return [u for u in everyone
            if (org is not None and u.get("org_id") == org) or u["id"] in vets or (u["farmer_id"] in farms)]


def pending_for(actor):
    pending = db.list_pending_users()
    if is_platform_owner(actor):
        return pending
    return [u for u in pending if org_of(actor) is not None and u.get("org_id") == org_of(actor) and u["role"] == "farmer"]


def _check_route(actor, route_id):
    if route_id is not None and route_id not in {r["id"] for r in routes_for(actor)}:
        raise ValueError("that route is not one of yours")


def _check_farm(actor, farmer_id):
    if farmer_id not in {f["id"] for f in db.list_farmers(active_only=False)}:
        raise ValueError("that farm no longer exists")
    if not is_platform_owner(actor) and farmer_id not in {f["id"] for f in farms_to_place(actor)}:
        raise ValueError("that farm is not on your routes")


def _check_user(actor, user_id):
    if user_id not in {u["id"] for u in users_for(actor)}:
        raise ValueError("that login is not one of yours")


def add_route(actor, code, name=None):
    """Add a route (or rename one of your own). An organisation's admin's new routes belong to it."""
    accounts._need_admin(actor)
    taken = next((r for r in db.list_routes() if r["code"] == str(code or "").strip().upper()), None)
    if taken is not None and not is_platform_owner(actor) and taken["id"] not in {r["id"] for r in routes_for(actor)}:
        raise ValueError("that route code is already used by another organisation: choose another")
    rid = accounts.record_route(code, name)
    if org_of(actor) is not None and taken is None:
        db.set_route_org(rid, org_of(actor))
    return rid


def allocate_vet(actor, route_id, vet_user_id):
    accounts._need_admin(actor)
    _check_route(actor, route_id)
    accounts.allocate_vet(route_id, vet_user_id)


def assign_route(actor, farmer_id, route_id):
    accounts._need_admin(actor)
    _check_farm(actor, farmer_id)
    _check_route(actor, route_id)
    accounts.assign_route(farmer_id, route_id)


def approve(actor, user_id):
    accounts._need_admin(actor)
    if user_id not in {u["id"] for u in pending_for(actor)}:
        raise ValueError("that sign-up is not for your organisation")
    return accounts.approve_signup(user_id)


def reject(actor, user_id):
    accounts._need_admin(actor)
    if user_id not in {u["id"] for u in pending_for(actor)}:
        raise ValueError("that sign-up is not for your organisation")
    accounts.reject_signup(user_id)


def create_login(actor, role, name, phone=None, email=None, temp_password=None, farmer_id=None, route_ids=None):
    """An admin creates a login. An organisation's admin can create its farmers (on its farms), its admins and
    route admins, and its store (an agrovet in the organisation); vets are independent and made by the owner."""
    accounts._need_admin(actor)
    org = org_of(actor)
    if not is_platform_owner(actor):
        if role == "vet":
            raise ValueError("vets sign up themselves or are added by the platform owner; then allocate them to your route")
        if farmer_id is not None:
            _check_farm(actor, farmer_id)
        for rid in route_ids or ():
            _check_route(actor, rid)
    uid = accounts.create_account(role, name, phone, email, temp_password, farmer_id, route_ids=route_ids)
    if org is not None and role in ("admin", "agrovet"):
        db.set_user_org(uid, org)
    return uid


def set_active(actor, user_id, active):
    accounts._need_admin(actor)
    _check_user(actor, user_id)
    if user_id == actor.get("id") and not active:
        raise ValueError("you cannot switch off your own login")
    db.update_user(user_id, active=bool(active))


def delete_login(actor, user_id, confirm):
    _check_user(actor, user_id)
    accounts.admin_delete_login(actor, user_id, confirm)


def delete_farm(actor, farmer_id, confirm):
    _check_farm(actor, farmer_id)
    accounts.admin_delete_farm(actor, farmer_id, confirm)


def delete_route(actor, route_id, confirm):
    _check_route(actor, route_id)
    accounts.admin_delete_route(actor, route_id, confirm)


# --- the buyer's own store ------------------------------------------------------------------------


def buyer_store_for(farmer_id, agrovet_id):
    """True if this agrovet is the store of the organisation that buys this farm's milk."""
    shop = db.get_user(agrovet_id)
    farm_org = db.farm_org_id(farmer_id)
    return bool(shop and shop["role"] == "agrovet" and farm_org is not None and shop.get("org_id") == farm_org)


def farms_to_place(actor):
    """Farms this admin may put on a route: its own farms, plus farms that signed up for its organisation and
    have no route yet."""
    mine = {f["id"]: f for f in farms_for(actor)}
    if is_platform_owner(actor):
        return list(db.list_farmers())
    org = org_of(actor)
    for u in db.list_users("farmer"):
        if org is not None and u.get("org_id") == org and u["farmer_id"]:
            f = db.get_farmer(u["farmer_id"])
            if f and f["route_id"] is None:
                mine[f["id"]] = f
    return list(mine.values())


def set_route_admin_routes(actor, user_id, route_ids):
    _check_user(actor, user_id)
    for rid in route_ids:
        _check_route(actor, rid)
    accounts.set_route_admin_routes(actor, user_id, route_ids)


def reset_two_factor(actor, user_id):
    _check_user(actor, user_id)
    accounts.admin_reset_totp(actor, user_id)
