"""Demo data for the judges: one admin, one vet, one farmer with 40 days of records.

    python -m src.demo_seed          # prints the three logins and a password, once

Safe to run again: existing demo accounts are left alone. The password comes from DEMO_PASSWORD
(set it in the shell, never in the repo) or is generated and printed once. The data is SIMULATED
and the demo phone numbers are fake; nothing here is a real farm.
"""
import os
import random
import secrets
from datetime import date, timedelta

from src import accounts, db
from src.ingestion import manual_entry as me

ADMIN_EMAIL, VET_EMAIL, FARMER_EMAIL = "admin@demo.milk", "vet@demo.milk", "farmer@demo.milk"
DEMO_FARM_PHONE = "+254700000999"


def seed_farm(farmer_id, today=None, days=40, seed=7):
    """40 days of milk and feed. Dairy meal varies, and milk rises a little with it, so the
    model has something real to find."""
    today = today or date.today()
    rng = random.Random(seed)
    me.record_milk_price(farmer_id, 50)
    me.record_catalogue_item(farmer_id, "dairy meal", "bag", 70, 3500)
    me.record_catalogue_item(farmer_id, "napier", "mtungi", 20, 100)
    for tag in ("Njeri", "Wambui", "Akinyi", "Chebet", "Atieno", "Mwende"):
        me.record_cow(farmer_id, tag)
    me.record_cows_in_milk(farmer_id, today - timedelta(days=days + 1), 5)
    for i in range(days, 0, -1):
        d = today - timedelta(days=i)
        meal = rng.choice([4, 5, 6, 7, 8]) * 1.0  # kg per day for the herd
        base = 62 + 1.4 * meal + rng.uniform(-2, 2)
        for session, share in (("morning", 0.45), ("afternoon", 0.2), ("evening", 0.35)):
            me.record_yield(farmer_id, d, session, round(base * share, 1))
        me.record_feed(farmer_id, d, "dairy meal", meal, cost_kes=round(meal * 50, 2))
        me.record_feed(farmer_id, d, "napier", 60, cost_kes=300)
        me.record_water(farmer_id, d, 4, bucket=True)


def create_demo(password=None, today=None):
    """Create the demo logins (and the farm) when missing. Returns {email: password} for new ones only."""
    password = password or os.environ.get("DEMO_PASSWORD") or secrets.token_urlsafe(9)
    made = {}
    route = accounts.record_route("4A", "Demo route")
    if not db.user_by_email(ADMIN_EMAIL):
        accounts.create_account("admin", "Demo Admin (Fresha)", email=ADMIN_EMAIL, temp_password=password)
        made[ADMIN_EMAIL] = password
    vet = db.user_by_email(VET_EMAIL)
    if not vet:
        vet_id = accounts.create_account("vet", "Dr Demo Vet", email=VET_EMAIL, temp_password=password)
        made[VET_EMAIL] = password
        accounts.allocate_vet(route, vet_id)
    if not db.user_by_email(FARMER_EMAIL):
        farm = db.farmer_by_phone(DEMO_FARM_PHONE)
        if farm is None:
            farm_id = db.add_farmer("Mama Demo", DEMO_FARM_PHONE, "Demo Farm", 5)
            seed_farm(farm_id, today)
        else:
            farm_id = farm["id"]
        accounts.assign_route(farm_id, route)
        accounts.create_account("farmer", "Mama Demo", email=FARMER_EMAIL, temp_password=password, farmer_id=farm_id)
        made[FARMER_EMAIL] = password
    # demo logins skip the forced password change: judges should get straight in
    for email in made:
        db.update_user(db.user_by_email(email)["id"], must_change_password=False)
    return made


def main():
    made = create_demo()
    if not made:
        print("Demo accounts already exist. Nothing changed.")
        return 0
    print("Demo logins (Email & password tab). Save this now; it is not shown again:")
    for email, pw in made.items():
        print(f"  {email}   {pw}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
