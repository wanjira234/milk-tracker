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
# A second, newer farm for the judges to try: 15 simulated days ending the day before yesterday, with YESTERDAY left empty.
# The model looks at full days up to yesterday and needs 14 usable ones (it averages each day with the 2 before it),
# so a judge who logs yesterday's milk and feed (choosing yesterday's date) makes the advice appear.
FRESH_EMAIL = "newfarm@demo.milk"
FRESH_FARM_PHONE = "+254700000998"
FRESH_DAYS = 15
FRESH_NOISE = 0.6  # less day-to-day wobble than the 40-day farm, so 14 days are enough for a clear result


def seed_logs(farmer_id, today=None, days=40, seed=7, skip=0, noise=2.0):
    """`days` days of milk, feed and water ending yesterday. Dairy meal varies, and milk rises a little
    with it, so the model has something real to find. `skip` leaves the most recent days empty."""
    today = today or date.today()
    rng = random.Random(seed)
    meals = [rng.choice([4, 5, 6, 7, 8]) * 1.0 for _ in range(days + 2)]  # kg per day for the herd; 2 extra for the lag
    for k, i in enumerate(range(days + skip, skip, -1)):
        d = today - timedelta(days=i)
        meal = meals[k + 2]
        # milk follows the feed over about 3 days (the model's own assumption), so use that average
        base = 62 + 1.4 * sum(meals[k:k + 3]) / 3 + rng.uniform(-noise, noise)
        for session, share in (("morning", 0.45), ("afternoon", 0.2), ("evening", 0.35)):
            me.record_yield(farmer_id, d, session, round(base * share, 1))
        me.record_feed(farmer_id, d, "dairy meal", meal, cost_kes=round(meal * 50, 2))
        me.record_feed(farmer_id, d, "napier", 60, cost_kes=300)
        me.record_water(farmer_id, d, 4, bucket=True)


def seed_farm(farmer_id, today=None, days=40, seed=7, skip=0, noise=2.0):
    """The farm's set-up (price, feeds, cows) and `days` days of simulated records."""
    today = today or date.today()
    me.record_milk_price(farmer_id, 50)
    me.record_catalogue_item(farmer_id, "dairy meal", "bag", 70, 3500)
    me.record_catalogue_item(farmer_id, "napier", "mtungi", 20, 100)
    for tag in ("Njeri", "Wambui", "Akinyi", "Chebet", "Atieno", "Mwende"):
        me.record_cow(farmer_id, tag)
    me.record_cows_in_milk(farmer_id, today - timedelta(days=days + skip + 1), 5)
    seed_logs(farmer_id, today, days, seed, skip, noise)


def reset_fresh_farm(today=None):
    """Put the newer demo farm back to its simulated days (judges add to it, so it drifts). Returns the farm id,
    or None if the farm has not been created yet."""
    farm = db.farmer_by_phone(FRESH_FARM_PHONE)
    if farm is None:
        return None
    for table in ("yield_logs", "feed_logs", "water_logs", "model_snapshots"):
        db._query(f"DELETE FROM {table} WHERE farmer_id = %s", (farm["id"],))  # fixed table names, value is a parameter
    db._query("DELETE FROM sms_log WHERE farmer_id = %s", (farm["id"],))
    seed_logs(farm["id"], today, FRESH_DAYS, seed=11, skip=1, noise=FRESH_NOISE)
    return farm["id"]


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
    if not db.user_by_email(FRESH_EMAIL):
        farm = db.farmer_by_phone(FRESH_FARM_PHONE)
        if farm is None:
            farm_id = db.add_farmer("Baba Demo", FRESH_FARM_PHONE, "Fresh Demo Farm (simulated)", 4)
            seed_farm(farm_id, today, days=FRESH_DAYS, seed=11, skip=1, noise=FRESH_NOISE)
        else:
            farm_id = farm["id"]
        accounts.assign_route(farm_id, route)
        accounts.create_account("farmer", "Baba Demo", email=FRESH_EMAIL, temp_password=password, farmer_id=farm_id)
        made[FRESH_EMAIL] = password
    # demo logins skip the forced password change: judges should get straight in
    for email in made:
        db.update_user(db.user_by_email(email)["id"], must_change_password=False)
    return made


def database_host():
    """Where DATABASE_URL points (host only: the password is never shown)."""
    from urllib.parse import urlparse

    return urlparse(os.environ.get("DATABASE_URL", "")).hostname or "unknown"


def main(ask=input, argv=None):
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if "--reset-fresh" in argv:
        print(f"This puts the fresh demo farm back to {FRESH_DAYS} simulated days, in the database at: {database_host()}")
        if ask("Type the word demo to continue: ").strip().lower() != "demo":
            print("Cancelled. Nothing changed.")
            return 1
        with db.batch():
            done = reset_fresh_farm()
        print("Reset." if done else "The fresh demo farm does not exist yet: run this command without --reset-fresh first.")
        return 0
    print(f"This writes demo accounts and SIMULATED farm data into the database at: {database_host()}")
    print("Do this only on your separate DEMO project, never on the real farm database.")
    if ask("Type the word demo to continue: ").strip().lower() != "demo":
        print("Cancelled. Nothing changed.")
        return 1
    with db.batch():  # one connection, all-or-nothing: fast, and an interrupted run leaves nothing half-seeded
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
