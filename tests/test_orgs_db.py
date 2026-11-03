"""Organisations: an organisation's admin sees and acts only on its own routes, farms, vets, logins and sign-ups;
the platform owner sees everything. Need TEST_DATABASE_URL."""
import os
from datetime import date

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import accounts, db, notifications, orgs, services  # noqa: E402
from src.auth import OWNER_USER  # noqa: E402
from src.ingestion import manual_entry as me  # noqa: E402

TODAY = date(2026, 11, 3)


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, farmers, users, routes, orgs RESTART IDENTITY CASCADE")


@pytest.fixture
def world():
    owner = dict(OWNER_USER)
    fresha, coop = orgs.create_org(owner, "Fresha"), orgs.create_org(owner, "Limuru Co-op")
    as_user = lambda uid: accounts.session_user(db.get_user(uid))  # noqa: E731
    fa = as_user(accounts.create_account("admin", "Fresha Admin", email="fa@x.co", temp_password="long-password-1"))
    ca = as_user(accounts.create_account("admin", "Coop Admin", email="ca@x.co", temp_password="long-password-1"))
    db.set_user_org(fa["id"], fresha)
    db.set_user_org(ca["id"], coop)
    fa, ca = as_user(fa["id"]), as_user(ca["id"])
    r_f, r_c = orgs.add_route(fa, "4A"), orgs.add_route(ca, "9C")
    vet_f = as_user(accounts.create_account("vet", "Dr F", phone="0711111111"))
    vet_c = as_user(accounts.create_account("vet", "Dr C", phone="0712222222"))
    orgs.allocate_vet(fa, r_f, vet_f["id"])
    orgs.allocate_vet(ca, r_c, vet_c["id"])
    farm_f, farm_c = db.add_farmer("Mama F", "+254700000001", "F Farm"), db.add_farmer("Mama C", "+254700000002", "C Farm")
    orgs.assign_route(owner, farm_f, r_f)
    orgs.assign_route(owner, farm_c, r_c)
    cow_f = me.record_cow(farm_f, "Njeri")["id"]
    cow_c = me.record_cow(farm_c, "Zawadi")["id"]
    return dict(owner=owner, fresha=fresha, coop=coop, fa=fa, ca=ca, r_f=r_f, r_c=r_c, vet_f=vet_f, vet_c=vet_c,
                farm_f=farm_f, farm_c=farm_c, cow_f=cow_f, cow_c=cow_c)


def test_each_admin_sees_only_their_organisation(world):
    fa, owner = world["fa"], world["owner"]
    assert [r["code"] for r in orgs.routes_for(fa)] == ["4A"] and len(orgs.routes_for(owner)) == 2
    assert [f["id"] for f in accounts.visible_farmers(fa)] == [world["farm_f"]]
    names = {u["name"] for u in orgs.users_for(fa)}
    assert names == {"Fresha Admin", "Dr F"} and "Coop Admin" not in names and "Dr C" not in names
    assert len(orgs.users_for(owner)) == 4


def test_an_admin_cannot_act_on_another_organisations_things(world):
    fa = world["fa"]
    with pytest.raises(ValueError, match="not one of yours"):
        orgs.allocate_vet(fa, world["r_c"], world["vet_f"]["id"])
    with pytest.raises(ValueError, match="not on your routes"):
        orgs.assign_route(fa, world["farm_c"], world["r_f"])
    with pytest.raises(ValueError, match="not one of yours"):
        orgs.assign_route(fa, world["farm_f"], world["r_c"])
    with pytest.raises(ValueError, match="not one of yours"):
        orgs.set_active(fa, world["vet_c"]["id"], False)
    with pytest.raises(ValueError, match="not on your routes"):
        orgs.delete_farm(fa, world["farm_c"], "DELETE")
    with pytest.raises(ValueError, match="not one of yours"):
        orgs.delete_route(fa, world["r_c"], "DELETE")
    with pytest.raises(ValueError, match="another organisation"):
        orgs.add_route(fa, "9c")
    for fn, args in ((orgs.create_org, ("X",)), (orgs.move_route, (world["r_c"], world["fresha"])),
                     (orgs.set_login_org, (world["ca"]["id"], world["fresha"]))):
        with pytest.raises(ValueError, match="platform owner"):
            fn(fa, *args)


def test_attendance_alerts_and_the_bell_follow_the_organisation(world):
    services.request_service(world["farm_f"], "sick", TODAY, cow_id=world["cow_f"], today=TODAY)
    services.request_service(world["farm_c"], "sick", TODAY, cow_id=world["cow_c"], today=TODAY)
    view = services.attendance(TODAY, accounts.admin_scope(world["fa"]))
    assert [v["vet"] for v in view["vets"]] == ["Dr F"]
    assert accounts.admin_scope(world["fa"]) == {world["r_f"]} and accounts.admin_scope(world["owner"]) is None
    accounts.signup("farmer", "New C", "nc@x.co", "long-password-1", phone="0700000009", buyer="limuru co-op")
    assert not any("signup" in t for t, _ in notifications._admin(world["fa"], TODAY))  # the co-op's sign-up isn't Fresha's
    assert any("1 signup" in t for t, _ in notifications._admin(world["ca"], TODAY))


def test_sign_ups_go_to_the_buyer_the_farmer_named(world):
    uid = accounts.signup("farmer", "New F", "nf@x.co", "long-password-1", phone="0700000009", buyer=" fresha ")
    other = accounts.signup("farmer", "New C", "nc@x.co", "long-password-1", phone="0700000010", buyer="Limuru Co-op")
    lost = accounts.signup("farmer", "No Buyer", "nb@x.co", "long-password-1", phone="0700000011", buyer="somebody else")
    assert [u["id"] for u in orgs.pending_for(world["fa"])] == [uid]
    assert {u["id"] for u in orgs.pending_for(world["owner"])} == {uid, other, lost}
    with pytest.raises(ValueError, match="not for your organisation"):
        orgs.approve(world["fa"], other)
    orgs.approve(world["fa"], uid)
    farm = db.get_user(uid)["farmer_id"]
    orgs.assign_route(world["fa"], farm, world["r_f"])  # a new farm that chose Fresha can be put on its route
    assert db.get_farmer(farm)["route_id"] == world["r_f"]


def test_an_organisation_admin_creates_its_own_logins_and_store(world):
    fa = world["fa"]
    store = orgs.create_login(fa, "agrovet", "Fresha store", phone="0723333333")
    assert db.get_user(store)["org_id"] == world["fresha"] and orgs.buyer_store_for(world["farm_f"], store)
    assert not orgs.buyer_store_for(world["farm_c"], store)
    with pytest.raises(ValueError, match="vets sign up"):
        orgs.create_login(fa, "vet", "Dr X", phone="0724444444")
    with pytest.raises(ValueError, match="not on your routes"):
        orgs.create_login(fa, "farmer", "Mama C login", phone="0700000002", farmer_id=world["farm_c"])
    ra = orgs.create_login(fa, "admin", "Fresha route admin", email="ra@x.co", temp_password="long-password-1", route_ids=[world["r_f"]])
    db.update_user(ra, route_admin=True)
    ra_user = accounts.session_user(db.get_user(ra))
    assert accounts.admin_scope(ra_user) == {world["r_f"]}
    with pytest.raises(ValueError, match="not one of yours"):
        orgs.set_route_admin_routes(fa, ra, [world["r_c"]])


def test_the_platform_owner_moves_routes_and_logins_between_organisations(world):
    orgs.move_route(world["owner"], world["r_c"], world["fresha"])
    assert {r["code"] for r in orgs.routes_for(world["fa"])} == {"4A", "9C"} and orgs.routes_for(world["ca"]) == []
    orgs.set_login_org(world["owner"], world["ca"]["id"], world["fresha"])
    assert db.get_user(world["ca"]["id"])["org_id"] == world["fresha"]
    with pytest.raises(ValueError, match="admin or an agrovet"):
        orgs.set_login_org(world["owner"], world["vet_f"]["id"], world["fresha"])
