"""Service requests: a farmer asks for a vet, that vet schedules and completes it.

Logic only (no Streamlit). Rules that matter here:
  - a request goes to the farm's route vet, unless the farmer sends it to a vet they added themselves;
  - a vet can only touch requests that are theirs: from farms on their routes, or sent to them (checked on every action);
  - a farmer can only cancel their own requests;
  - semen must come from the route vet's own list, and its price is copied onto the request;
  - completing an AI visit also records the service on the cow's breeding record, so the farmer
    does not enter it twice, and its semen cost counts in the farm's monthly costs;
  - completing a visit can also bill it (fee, drugs, and the semen on an AI visit) in the money ledger,
    in the same transaction, so a visit is never marked done with half its bill saved.
"""
from datetime import date, timedelta

from src import db, ledger
from src.ingestion import manual_entry as me

KINDS = {"ai": "AI (insemination)", "sick": "Sick cow", "other": "Something else", "vaccination": "Vaccination"}
FARMER_KINDS = ("ai", "sick", "other")  # vaccination requests come from booked vaccination days
STATUS_WORDS = {"open": "waiting for the vet", "scheduled": "booked", "done": "done", "cancelled": "cancelled"}
MAX_OPEN = 20      # one farm can't flood its vet
HORIZON_DAYS = 60  # how far ahead a day can be asked for or booked
MAX_NOTE = 300
MAX_OWN_VETS = 5   # vets a farm may add besides its route vet


def _clean(text, limit, what):
    text = " ".join(str(text or "").split())
    if len(text) > limit:
        raise ValueError(f"{what} is too long ({limit} characters at most)")
    return text


def _check_day(day, today, what):
    if day < today:
        raise ValueError(f"{what} cannot be in the past")
    if day > today + timedelta(days=HORIZON_DAYS):
        raise ValueError(f"{what} must be within the next {HORIZON_DAYS} days")


# --- the vet's semen list ---------------------------------------------------------------------


def record_vet_semen(vet_user, name, price_kes):
    """Add or reprice a bull or breed on this vet's list. Returns the semen id."""
    if vet_user["role"] != "vet":
        raise ValueError("only a vet keeps a semen list")
    name = _clean(name, 80, "the name")
    if not name:
        raise ValueError("enter the bull name or breed")
    try:
        price = round(float(price_kes), 2)
    except (TypeError, ValueError):
        raise ValueError("enter the price in shillings") from None
    if not 0 < price <= 100000:
        raise ValueError("the price must be more than 0 and at most 100,000 shillings")
    return db.add_vet_semen(vet_user["id"], name, price)


# --- farmer side ------------------------------------------------------------------------------


def add_own_vet(farmer_id, phone):
    """The farmer adds a vet they use (not their route vet) by the vet's phone number. Returns the vet's user id.
    The vet must already have an approved vet login."""
    phone = me.normalize_phone(phone)
    vet = db.user_by_phone(phone)
    if not vet or vet["role"] != "vet" or not vet["active"] or vet.get("pending"):
        raise ValueError("no vet with that number uses Maziwa Plus yet: ask them to sign up as a vet")
    if vet["id"] == db.route_vet_id(farmer_id):
        raise ValueError("that is already your route vet")
    if not db.is_farm_vet(farmer_id, vet["id"]) and len(db.farm_vets(farmer_id)) >= MAX_OWN_VETS:
        raise ValueError(f"you can add at most {MAX_OWN_VETS} vets: remove one first")
    db.add_farm_vet(farmer_id, vet["id"])
    return vet["id"]


def vets_for_farm(farmer_id):
    """[(vet id or None, label)] the farmer can send a request to: the route vet first (None), then their own."""
    route_vet = db.route_vet_id(farmer_id)
    route_user = db.get_user(route_vet) if route_vet else None
    out = [(None, f"Route vet: {route_user['name']}" if route_user else "Route vet (none allocated yet)")]
    return out + [(v["id"], v["name"]) for v in db.farm_vets(farmer_id) if v["id"] != route_vet]


def request_service(farmer_id, kind, preferred_date, cow_id=None, semen_id=None, notes=None, today=None, vet_id=None):
    """A farmer asks a vet for something: the route vet (vet_id None) or one of the farm's own vets.
    Returns the request id."""
    today = today or date.today()
    if vet_id is not None and not db.is_farm_vet(farmer_id, vet_id):
        raise ValueError("choose one of your vets")
    if kind not in FARMER_KINDS:
        raise ValueError("choose what you need")
    _check_day(preferred_date, today, "the day")
    notes = _clean(notes, MAX_NOTE, "the note")
    if kind == "other" and not notes:
        raise ValueError("say what you need")
    price = None
    if kind in ("ai", "sick"):
        animals = {c["id"]: c for c in db.list_cows(farmer_id)}
        if cow_id not in animals:
            raise ValueError("choose the cow")
        if kind == "ai" and animals[cow_id]["kind"] == "calf":
            raise ValueError("a calf cannot be served")
        if db.has_open_request(farmer_id, cow_id, kind):
            raise ValueError("this cow already has an open request of this kind")
    else:
        cow_id = None
    if kind == "ai" and semen_id is not None:
        semen = db.get_vet_semen(semen_id)
        answering = vet_id if vet_id is not None else db.route_vet_id(farmer_id)
        if not semen or not semen["active"] or answering is None or semen["vet_user_id"] != answering:
            raise ValueError("choose the semen from your vet's list")
        price = semen["price_kes"]
    else:
        semen_id = None
    if db.open_request_count(farmer_id) >= MAX_OPEN:
        raise ValueError(f"you already have {MAX_OPEN} open requests: wait for the vet to clear some")
    return db.add_request(farmer_id, kind, preferred_date, cow_id, semen_id, price, notes or None, chosen_vet_id=vet_id)


def cancel_request(request_id, farmer_id):
    """A farmer withdraws their own request while it is still waiting or booked."""
    q = db.get_request(request_id)
    if not q or q["farmer_id"] != farmer_id:
        raise ValueError("that request is not yours")
    if q["status"] not in ("open", "scheduled"):
        raise ValueError("only a waiting or booked request can be cancelled")
    db.update_request(request_id, status="cancelled")


# --- vet side ---------------------------------------------------------------------------------


def _own_request(request_id, vet_user):
    if vet_user["role"] != "vet":
        raise ValueError("only a vet can do this")
    q = db.get_request(request_id)
    if not q or q["vet_user_id"] != vet_user["id"]:
        raise ValueError("that request is not on your routes and was not sent to you")
    return q


def default_terms(request):
    """How a visit is usually settled: the buyer's route vet through the milk payment, any other vet on credit."""
    return "milk_deduction" if request.get("chosen_vet_id") is None else "credit"


def schedule_request(request_id, vet_user, day, today=None):
    """The vet books a day for the visit."""
    today = today or date.today()
    q = _own_request(request_id, vet_user)
    if q["status"] not in ("open", "scheduled"):
        raise ValueError("this request is already closed")
    _check_day(day, today, "the visit day")
    db.update_request(request_id, status="scheduled", scheduled_for=day)


def complete_request(request_id, vet_user, notes=None, semen_id=None, today=None,
                     lines=(), terms=None, due_on=None, method=None, reference=None):
    """The vet marks a visit done. An AI visit needs the semen used and records the service on the cow.

    Billing: `lines` = [(category, amount, note)] for the fee, drugs or anything else; the semen of an AI
    visit is billed automatically at the agreed price. `terms` = how it is settled (default: the route
    vet's bill goes to the milk payment, any other vet's on credit). Everything is checked first and then
    written in one transaction."""
    today = today or date.today()
    q = _own_request(request_id, vet_user)
    if q["status"] not in ("open", "scheduled"):
        raise ValueError("this request is already closed")
    notes = _clean(notes, MAX_NOTE, "the note")
    fields = {"status": "done", "done_on": today, "done_by_user_id": vet_user["id"], "vet_notes": notes or None}
    semen = None
    if q["kind"] == "ai":
        semen_id = semen_id if semen_id is not None else q["semen_id"]
        semen = db.get_vet_semen(semen_id) if semen_id is not None else None
        if not semen or semen["vet_user_id"] != vet_user["id"]:
            raise ValueError("choose the semen used, from your own list")
        # the price the farmer was quoted stands when the vet used that same semen
        price = q["semen_price_kes"] if semen_id == q["semen_id"] and q["semen_price_kes"] is not None else semen["price_kes"]
        fields.update(semen_id=semen_id, semen_price_kes=price)
    done = {**q, **fields, "semen_name": semen["name"] if semen else q["semen_name"]}
    charges, payment = ledger.bill_for_visit(done, vet_user, lines, terms or default_terms(q), due_on, method, reference, today)
    with db.batch():  # all or nothing: the visit, the cow's record and the bill
        if db.lock_request_status(request_id) not in ("open", "scheduled"):  # someone finished it meanwhile
            raise ValueError("this request is already closed")
        if semen is not None:
            farm_semen = db.add_semen(q["farmer_id"], semen["name"])  # the farm's own list, so the cow's record names it
            me.record_breeding_event(q["farmer_id"], q["cow_id"], today, "served", farm_semen, today=today)
        db.update_request(request_id, **fields)
        if charges:
            db.add_charges(charges, payment)


def carry_list(visits):
    """What the vet needs in the bag for these visits, as plain lines."""
    semen, vaccines, sick, other = {}, {}, 0, 0
    for v in visits:
        if v["kind"] == "ai":
            name = v["semen_name"] or "semen (to be chosen)"
            semen[name] = semen.get(name, 0) + 1
        elif v["kind"] == "vaccination":
            name = v.get("vaccine") or "vaccine"
            vaccines[name] = vaccines.get(name, 0) + (v.get("animals") or 1)
        elif v["kind"] == "sick":
            sick += 1
        elif v["kind"] == "other":
            other += 1
    lines = [f"{name}: {n} straw{'s' if n != 1 else ''}" for name, n in sorted(semen.items())]
    lines += [f"{name}: {n} dose{'s' if n != 1 else ''}" for name, n in sorted(vaccines.items())]
    if sick:
        lines.append(f"treatment kit for {sick} sick-cow visit{'s' if sick != 1 else ''}")
    if other:
        lines.append(f"{other} other request{'s' if other != 1 else ''}: read the notes")
    return lines


def inbox(vet_user):
    """Requests on the vet's routes that have no day yet."""
    return [q for q in db.requests_for_vet(vet_user["id"], ("open",))]


def day_sheet(vet_user, day):
    """The vet's visits for one day, grouped by farm, with what to carry."""
    visits = [q for q in db.requests_for_vet(vet_user["id"], ("scheduled", "done"))
              if (q["scheduled_for"] or q["done_on"]) == day]
    farms = {}
    for q in visits:
        farms.setdefault(q["farmer_id"], {"farm": q["farm_name"] or q["farmer_name"], "phone": q["farmer_phone"],
                                          "route": q["route_code"], "visits": []})["visits"].append(q)
    pending = [q for q in visits if q["status"] == "scheduled"]
    return {"farms": list(farms.values()), "carry": carry_list(pending), "total": len(visits), "done": len(visits) - len(pending)}


# --- admin side -------------------------------------------------------------------------------


def attendance(day, routes=None):
    """Per vet: how many of the day's visits are done, how many are still to do, and how many are late.
    Requests on farms with no vet are listed apart, because nobody is answering them."""
    rows = db.requests_for_attendance(day)
    if routes is not None:  # a route admin sees only their routes' requests
        rows = [q for q in rows if q["route_id"] in routes]
    vets, unattended = {}, []
    for q in rows:
        if q["vet_user_id"] is None:
            unattended.append(q)
            continue
        v = vets.setdefault(q["vet_user_id"], {"vet": q["vet_name"], "booked_today": 0, "done_today": 0,
                                                "to_do_today": [], "late": [], "waiting": 0})
        due = q["scheduled_for"] or q["preferred_date"]
        if q["status"] == "done":
            v["done_today"] += 1
            v["booked_today"] += 1
        elif q["status"] == "scheduled" and q["scheduled_for"] == day:
            v["booked_today"] += 1
            v["to_do_today"].append(q)
        elif due < day:
            v["late"].append(q)
        elif q["status"] == "open":
            v["waiting"] += 1
    return {"vets": sorted(vets.values(), key=lambda v: v["vet"]), "unattended": unattended}
