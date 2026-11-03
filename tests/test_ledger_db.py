"""Choosing a vet, billing visits and the money ledger, against real Postgres. Need TEST_DATABASE_URL."""
import os
import threading
from datetime import date, timedelta
from decimal import Decimal

import psycopg2
import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import accounts, db, ledger, services  # noqa: E402
from src.ingestion import manual_entry as me  # noqa: E402

TODAY = date(2026, 11, 3)


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE charge_payments, charges, farm_vets, sms_log, feed_logs, yield_logs, farmers, users, routes "
              "RESTART IDENTITY CASCADE")


@pytest.fixture
def world():
    """Route 4A with Dr Kibet (the buyer's route vet); Dr Wanjiku, an independent vet; farms A and B on 4A."""
    route = accounts.record_route("4A")
    kibet = accounts.create_account("vet", "Dr Kibet", phone="0712345678")
    wanjiku = accounts.create_account("vet", "Dr Wanjiku", phone="0733333333")
    accounts.allocate_vet(route, kibet)
    farm_a, farm_b = db.add_farmer("Mama A", "+254700000001", "A Farm"), db.add_farmer("Mama B", "+254700000002", "B Farm")
    accounts.assign_route(farm_a, route)
    accounts.assign_route(farm_b, route)
    user_a = accounts.create_account("farmer", "Mama A", phone="0700000001", farmer_id=farm_a)
    user_b = accounts.create_account("farmer", "Mama B", phone="0700000002", farmer_id=farm_b)
    cow = me.record_cow(farm_a, "Njeri")["id"]
    as_user = lambda uid: accounts.session_user(db.get_user(uid))  # noqa: E731
    return dict(kibet=as_user(kibet), wanjiku=as_user(wanjiku), farm_a=farm_a, farm_b=farm_b,
                user_a=as_user(user_a), user_b=as_user(user_b), cow=cow)


def sick_visit(w, vet_id=None):
    return services.request_service(w["farm_a"], "sick", TODAY, cow_id=w["cow"], today=TODAY, vet_id=vet_id)


# --- choosing a vet ------------------------------------------------------------------------------


def test_a_farmer_adds_an_independent_vet_by_phone_and_sends_them_a_request(world):
    assert services.add_own_vet(world["farm_a"], "0733 333 333") == world["wanjiku"]["id"]
    assert services.vets_for_farm(world["farm_a"]) == [(None, "Route vet: Dr Kibet"), (world["wanjiku"]["id"], "Dr Wanjiku")]
    rid = sick_visit(world, world["wanjiku"]["id"])
    q = db.get_request(rid)
    assert q["vet_user_id"] == world["wanjiku"]["id"] and q["vet_name"] == "Dr Wanjiku"
    assert [r["id"] for r in services.inbox(world["wanjiku"])] == [rid]
    assert services.inbox(world["kibet"]) == []  # the route vet doesn't see it
    assert services.attendance(TODAY)["vets"] == []  # nor does the buyer's admin
    with pytest.raises(ValueError, match="not on your routes"):
        services.schedule_request(rid, world["kibet"], TODAY, today=TODAY)
    services.schedule_request(rid, world["wanjiku"], TODAY, today=TODAY)


def test_route_requests_still_go_to_the_route_vet(world):
    rid = sick_visit(world)
    assert db.get_request(rid)["vet_user_id"] == world["kibet"]["id"]
    assert [r["id"] for r in services.inbox(world["kibet"])] == [rid]


def test_who_can_be_added_as_a_vet(world):
    with pytest.raises(ValueError, match="no vet with that number"):
        services.add_own_vet(world["farm_a"], "0799999999")
    with pytest.raises(ValueError, match="no vet with that number"):
        services.add_own_vet(world["farm_a"], "0700000002")  # a farmer, not a vet
    with pytest.raises(ValueError, match="already your route vet"):
        services.add_own_vet(world["farm_a"], "0712345678")
    pending = accounts.create_account("vet", "Dr Pending", phone="0744444444")
    db.update_user(pending, pending=True)
    with pytest.raises(ValueError, match="no vet with that number"):
        services.add_own_vet(world["farm_a"], "0744444444")
    for i in range(5):
        accounts.create_account("vet", f"Dr {i}", phone=f"075000000{i}")
        services.add_own_vet(world["farm_a"], f"075000000{i}")
    accounts.create_account("vet", "Dr Six", phone="0760000000")
    with pytest.raises(ValueError, match="at most 5"):
        services.add_own_vet(world["farm_a"], "0760000000")


def test_a_request_can_only_go_to_a_vet_the_farm_added(world):
    with pytest.raises(ValueError, match="one of your vets"):
        sick_visit(world, world["wanjiku"]["id"])
    services.add_own_vet(world["farm_a"], "0733333333")
    db.remove_farm_vet(world["farm_a"], world["wanjiku"]["id"])
    with pytest.raises(ValueError, match="one of your vets"):
        sick_visit(world, world["wanjiku"]["id"])


def test_ai_semen_must_come_from_the_chosen_vets_list(world):
    services.add_own_vet(world["farm_a"], "0733333333")
    kibet_semen = services.record_vet_semen(world["kibet"], "Friesian - Kamau", 1500)
    wanjiku_semen = services.record_vet_semen(world["wanjiku"], "Ayrshire - Baraka", 1200)
    with pytest.raises(ValueError, match="your vet's list"):
        services.request_service(world["farm_a"], "ai", TODAY, cow_id=world["cow"], semen_id=kibet_semen, today=TODAY,
                                 vet_id=world["wanjiku"]["id"])
    rid = services.request_service(world["farm_a"], "ai", TODAY, cow_id=world["cow"], semen_id=wanjiku_semen, today=TODAY,
                                   vet_id=world["wanjiku"]["id"])
    assert float(db.get_request(rid)["semen_price_kes"]) == 1200


# --- billing a visit -----------------------------------------------------------------------------


def test_a_route_vets_ai_visit_bills_the_semen_to_the_milk_payment_by_default(world):
    semen = services.record_vet_semen(world["kibet"], "Friesian - Kamau", 1500)
    rid = services.request_service(world["farm_a"], "ai", TODAY, cow_id=world["cow"], semen_id=semen, today=TODAY)
    services.complete_request(rid, world["kibet"], today=TODAY, lines=[("vet_visit", "500", "call-out")])
    rows = db.charges_for_request(rid)
    assert sorted((r["category"], float(r["amount_kes"]), r["terms"]) for r in rows) == [
        ("semen", 1500.0, "milk_deduction"), ("vet_visit", 500.0, "milk_deduction")]
    assert all(r["provider_user_id"] == world["kibet"]["id"] and r["provider_name"] == "Dr Kibet" for r in rows)
    assert db.semen_cost(world["farm_a"], TODAY, TODAY) == (1500.0, 1)  # the dashboard's semen figure is unchanged


def test_an_independent_vets_visit_goes_on_credit_by_default_and_cannot_use_the_milk_payment(world):
    services.add_own_vet(world["farm_a"], "0733333333")
    rid = sick_visit(world, world["wanjiku"]["id"])
    with pytest.raises(ValueError, match="route vet"):
        services.complete_request(rid, world["wanjiku"], today=TODAY, lines=[("vet_visit", "800", "")], terms="milk_deduction")
    assert db.get_request(rid)["status"] == "open"  # nothing half-saved
    services.complete_request(rid, world["wanjiku"], today=TODAY, lines=[("vet_visit", "800", ""), ("drugs", "1,200", "antibiotics")])
    rows = db.charges_for_request(rid)
    assert {r["terms"] for r in rows} == {"credit"} and {r["due_on"] for r in rows} == {TODAY + timedelta(days=30)}


def test_a_visit_paid_on_the_spot_records_the_payment(world):
    rid = sick_visit(world)
    services.complete_request(rid, world["kibet"], today=TODAY, lines=[("vet_visit", "800", "")], terms="paid",
                              method="mpesa", reference="SK3ABC12XY")
    c = db.charges_for_request(rid)[0]
    assert float(c["paid_kes"]) == 800 and ledger.owed(c) == 0
    assert db.payments_for_charge(c["id"])[0]["reference"] == "SK3ABC12XY"


def test_a_bad_bill_leaves_the_visit_open(world):
    rid = sick_visit(world)
    with pytest.raises(ValueError, match="shillings"):
        services.complete_request(rid, world["kibet"], today=TODAY, lines=[("vet_visit", "abc", "")])
    assert db.get_request(rid)["status"] == "open" and db.charges_for_request(rid) == []


def test_a_visit_with_nothing_to_bill_leaves_no_charge(world):
    rid = sick_visit(world)
    services.complete_request(rid, world["kibet"], today=TODAY)
    assert db.get_request(rid)["status"] == "done" and db.charges_for_request(rid) == []


# --- payments ------------------------------------------------------------------------------------


def credit_visit(world, amount="1000"):
    services.add_own_vet(world["farm_a"], "0733333333")
    rid = sick_visit(world, world["wanjiku"]["id"])
    services.complete_request(rid, world["wanjiku"], today=TODAY, lines=[("vet_visit", amount, "")])
    return db.charges_for_request(rid)[0]["id"]


def test_part_payments_reduce_the_balance_and_overpaying_is_refused(world):
    cid = credit_visit(world)
    ledger.record_payment(world["wanjiku"], cid, "400", "cash", today=TODAY)
    assert ledger.owed(db.get_charge(cid)) == 600
    with pytest.raises(ValueError, match="only KES 600 is still owed"):
        ledger.record_payment(world["wanjiku"], cid, "601", "mpesa", today=TODAY)
    ledger.record_payment(world["wanjiku"], cid, "600", "mpesa", reference="SK3ABC12XY", today=TODAY)
    assert ledger.owed(db.get_charge(cid)) == 0
    assert ledger.debtors(db.charges_for_provider(world["wanjiku"]["id"], credit_only=True), TODAY) == []


def test_two_payments_at_once_cannot_both_pay_off_the_same_balance(world):
    cid = credit_visit(world)
    results = []

    def pay():
        try:
            db.add_payment(cid, Decimal("600"), TODAY, "cash")
            results.append("ok")
        except ValueError:
            results.append("refused")

    threads = [threading.Thread(target=pay) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ok", "refused"] and ledger.owed(db.get_charge(cid)) == 400


def test_only_the_vet_who_billed_takes_payments_on_their_charge(world):
    cid = credit_visit(world)
    for who in (world["kibet"], world["user_a"], world["user_b"]):
        with pytest.raises(ValueError, match="only the one who raised"):
            ledger.record_payment(who, cid, "100", "cash", today=TODAY)


def test_payment_dates_and_terms(world):
    cid = credit_visit(world)
    with pytest.raises(ValueError, match="future"):
        ledger.record_payment(world["wanjiku"], cid, "100", "cash", paid_on=TODAY + timedelta(days=1), today=TODAY)
    with pytest.raises(ValueError, match="before the charge"):
        ledger.record_payment(world["wanjiku"], cid, "100", "cash", paid_on=TODAY - timedelta(days=1), today=TODAY)
    paid = ledger.record_farm_cost(world["user_a"], world["farm_a"], "Mboga Center", "agrovet", "500", TODAY, "paid",
                                   method="cash", today=TODAY)
    with pytest.raises(ValueError, match="only a charge on credit"):
        ledger.record_payment(world["user_a"], paid, "100", "cash", today=TODAY)


# --- the farmer's own costs ----------------------------------------------------------------------


def test_a_farmer_records_costs_from_suppliers_without_a_login(world):
    u, f = world["user_a"], world["farm_a"]
    ledger.record_farm_cost(u, f, "Mboga Center", "agrovet", "2,000", TODAY, "paid", method="mpesa", today=TODAY)
    store = ledger.record_farm_cost(u, f, "Fresha store", "agrovet", "1500", TODAY, "milk_deduction", today=TODAY)
    credit = ledger.record_farm_cost(u, f, "Mboga Center", "feed", "3000", TODAY, "credit",
                                     due_on=TODAY + timedelta(days=14), description="2 bags dairy meal", today=TODAY)
    rows = db.charges_for_farm(f, TODAY, TODAY)
    assert len(rows) == 3 and {r["provider_user_id"] for r in rows} == {None}
    assert db.get_charge(store)["terms"] == "milk_deduction"
    ledger.record_payment(u, credit, "1000", "mpesa", today=TODAY)  # the farmer settles their own record
    assert [float(c["amount_kes"]) - float(c["paid_kes"]) for c in db.open_credit_for_farm(f)] == [2000.0]


def test_a_farmer_can_only_record_for_their_own_farm(world):
    with pytest.raises(ValueError, match="your own farm"):
        ledger.record_farm_cost(world["user_b"], world["farm_a"], "Mboga Center", "agrovet", "500", TODAY, "credit", today=TODAY)
    with pytest.raises(ValueError, match="your own farm"):
        ledger.record_farm_cost(world["kibet"], world["farm_a"], "Mboga Center", "agrovet", "500", TODAY, "credit", today=TODAY)
    cid = ledger.record_farm_cost(world["user_a"], world["farm_a"], "Mboga Center", "agrovet", "500", TODAY, "credit", today=TODAY)
    with pytest.raises(ValueError, match="only the farm that recorded"):
        ledger.record_payment(world["user_b"], cid, "100", "cash", today=TODAY)


def test_farm_cost_validation(world):
    u, f = world["user_a"], world["farm_a"]
    for kw, why in ((dict(supplier=""), "who it was from"), (dict(category="semen"), "what it was for"),
                    (dict(charged_on=TODAY + timedelta(days=1)), "future"), (dict(charged_on=TODAY - timedelta(days=400)), "last year"),
                    (dict(terms="paid"), "how it was paid"), (dict(supplier="x" * 81), "too long")):
        args = {"supplier": "Mboga Center", "category": "agrovet", "amount": "500", "charged_on": TODAY, "terms": "credit", **kw}
        with pytest.raises(ValueError, match=why):
            ledger.record_farm_cost(u, f, args["supplier"], args["category"], args["amount"], args["charged_on"], args["terms"], today=TODAY)


# --- corrections ---------------------------------------------------------------------------------


def test_a_wrong_charge_is_voided_with_a_reason_and_kept(world):
    cid = credit_visit(world)
    with pytest.raises(ValueError, match="only the one who raised"):
        ledger.void_charge(world["user_a"], cid, "not mine")
    with pytest.raises(ValueError, match="say why"):
        ledger.void_charge(world["wanjiku"], cid, " ")
    ledger.void_charge(world["wanjiku"], cid, "entered twice")
    c = db.get_charge(cid)
    assert c["voided_at"] is not None and c["void_reason"] == "entered twice" and c["voided_by_user_id"] == world["wanjiku"]["id"]
    assert db.charges_for_farm(world["farm_a"]) == [] and len(db.charges_for_farm(world["farm_a"], include_voided=True)) == 1
    with pytest.raises(ValueError, match="already cancelled"):
        ledger.void_charge(world["wanjiku"], cid, "again")
    with pytest.raises(ValueError, match="cancelled"):
        ledger.record_payment(world["wanjiku"], cid, "100", "cash", today=TODAY)


def test_a_credit_charge_with_payments_cannot_be_voided(world):
    cid = credit_visit(world)
    ledger.record_payment(world["wanjiku"], cid, "100", "cash", today=TODAY)
    with pytest.raises(ValueError, match="payments on it"):
        ledger.void_charge(world["wanjiku"], cid, "oops")


def test_a_mistyped_paid_now_cost_can_be_cancelled(world):
    cid = ledger.record_farm_cost(world["user_a"], world["farm_a"], "Mboga Center", "agrovet", "5000", TODAY, "paid",
                                  method="cash", today=TODAY)
    ledger.void_charge(world["user_a"], cid, "it was 500, not 5000")
    assert db.charges_for_farm(world["farm_a"]) == [] and len(db.payments_for_charge(cid)) == 1  # the payment stays on record


def test_the_database_refuses_a_charge_for_another_farms_visit(world):
    rid = sick_visit(world)  # farm A's visit
    bad = {"farmer_id": world["farm_b"], "provider_user_id": world["kibet"]["id"], "provider_name": "Dr Kibet",
           "category": "vet_visit", "description": None, "amount_kes": Decimal("100"), "charged_on": TODAY, "terms": "paid",
           "due_on": None, "request_id": rid, "created_by_user_id": world["kibet"]["id"]}
    with pytest.raises(psycopg2.IntegrityError):
        db.add_charges([bad])


def test_the_statement_from_the_database(world):
    u, f = world["user_a"], world["farm_a"]
    db.set_milk_price(f, 50)
    for session in ("morning", "afternoon", "evening"):
        db.upsert_yield(f, TODAY, session, 20)
    semen = services.record_vet_semen(world["kibet"], "Friesian - Kamau", 1500)
    rid = services.request_service(f, "ai", TODAY, cow_id=world["cow"], semen_id=semen, today=TODAY)
    services.complete_request(rid, world["kibet"], today=TODAY)
    ledger.record_farm_cost(u, f, "Mboga Center", "agrovet", "2000", TODAY, "credit", today=TODAY)
    start = TODAY.replace(day=1)
    s = ledger.statement(db.month_litres(f, start, TODAY), db.get_milk_price(f), 0, db.charges_for_farm(f, start, TODAY),
                         db.open_credit_for_farm(f), TODAY)
    assert s["income"] == 3000 and s["deductions"] == 1500 and s["expected_payout"] == 1500 and s["owed_total"] == 2000
