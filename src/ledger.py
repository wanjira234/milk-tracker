"""The money ledger: what a farm owes for vet visits, drugs, semen and goods, and what has been paid.

Logic only (no Streamlit). The app records money; it never moves it. Rules that matter here:
  - every charge says how it is settled: paid on the spot, on credit until a due date, or deducted
    from the milk payment by the buyer (only a route vet, or the farmer recording a buyer's deduction,
    may use that);
  - a vet raises charges only on their own visits and takes payments only on their own charges;
  - a farmer records their own costs (any supplier, with or without a login) and payments on those;
  - nobody can pay more than is owed, and a wrong charge is voided (kept, with who and why), never
    deleted; a credit charge only while nothing has been paid on it;
  - a buyer's admin sees none of this: what a farm spends elsewhere is the farmer's business.

The statement and debtor views at the bottom are pure functions of rows, tested without a database.
"""
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from src import db

CATEGORIES = {"vet_visit": "Vet visit", "drugs": "Drugs and treatment", "semen": "AI semen",
              "agrovet": "Agrovet goods", "feed": "Feed", "other": "Other"}
FARMER_CATEGORIES = ("agrovet", "feed", "vet_visit", "drugs", "other")  # semen comes from AI visits
VET_CATEGORIES = ("vet_visit", "drugs", "other")                        # semen is added from the visit itself
TERMS = {"paid": "Paid now", "credit": "On credit", "milk_deduction": "Deducted from milk payment"}
METHODS = {"mpesa": "M-Pesa", "cash": "Cash", "bank": "Bank", "other": "Other"}
MAX_AMOUNT = Decimal("1000000")
MAX_LINES = 5            # lines on one visit's bill
MAX_BACKDATE_DAYS = 366  # a cost older than a year belongs in last year's books
MAX_CREDIT_DAYS = 180
DEFAULT_CREDIT_DAYS = 30
_REFERENCE = re.compile(r"^[A-Za-z0-9-]{4,40}$")


# --- input checks -------------------------------------------------------------------------------


def _clean(text, limit, what):
    text = " ".join(str(text or "").split())
    if len(text) > limit:
        raise ValueError(f"{what} is too long ({limit} characters at most)")
    return text


def parse_amount(value, what="the amount"):
    """Shillings as a Decimal rounded to cents; more than 0 and at most a million."""
    try:
        amount = Decimal(str(value).replace(",", "").strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError(f"enter {what} in shillings") from None
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{what} must be more than 0")
    if amount > MAX_AMOUNT:
        raise ValueError(f"{what} must be at most 1,000,000 shillings")
    return amount


def _check_reference(reference):
    reference = (reference or "").strip().upper()
    if reference and not _REFERENCE.match(reference):
        raise ValueError("the reference should be the M-Pesa code or receipt number (letters and numbers only)")
    return reference or None


def _check_charge_day(day, today):
    if day > today:
        raise ValueError("the date cannot be in the future")
    if day < today - timedelta(days=MAX_BACKDATE_DAYS):
        raise ValueError("the date must be within the last year")


def _settlement(terms, due_on, charged_on, method, reference, today):
    """Check how a charge is settled. Returns (due_on, method, reference) cleaned for that terms."""
    if terms not in TERMS:
        raise ValueError("choose how it is paid")
    if terms == "credit":
        due_on = due_on or charged_on + timedelta(days=DEFAULT_CREDIT_DAYS)
        if due_on < charged_on:
            raise ValueError("the due date cannot be before the charge")
        if due_on > charged_on + timedelta(days=MAX_CREDIT_DAYS):
            raise ValueError(f"credit can run at most {MAX_CREDIT_DAYS} days")
        return due_on, None, None
    if terms == "paid":
        if method not in METHODS:
            raise ValueError("choose how it was paid")
        return None, method, _check_reference(reference)
    return None, None, None  # milk deduction: the buyer settles it on the monthly milk payment


def _own_farm(user, farmer_id):
    if not user or user.get("role") != "farmer" or user.get("farmer_id") != farmer_id:
        raise ValueError("you can only record money for your own farm")


# --- the farmer's own records -------------------------------------------------------------------


def record_farm_cost(user, farmer_id, supplier, category, amount, charged_on, terms, due_on=None,
                     method=None, reference=None, description=None, today=None):
    """A farmer records a cost from any supplier (Mboga Center, the buyer's store, a vet with no login).
    Returns the charge id."""
    today = today or date.today()
    _own_farm(user, farmer_id)
    supplier = _clean(supplier, 80, "the supplier's name")
    if not supplier:
        raise ValueError("say who it was from")
    if category not in FARMER_CATEGORIES:
        raise ValueError("choose what it was for")
    amount = parse_amount(amount)
    _check_charge_day(charged_on, today)
    due_on, method, reference = _settlement(terms, due_on, charged_on, method, reference, today)
    charge = {"farmer_id": farmer_id, "provider_user_id": None, "provider_name": supplier, "category": category,
              "description": _clean(description, 200, "the note") or None, "amount_kes": amount,
              "charged_on": charged_on, "terms": terms, "due_on": due_on, "request_id": None,
              "created_by_user_id": user["id"]}
    payment = None if terms != "paid" else {"method": method, "paid_on": charged_on, "reference": reference,
                                            "recorded_by_user_id": user["id"]}
    return db.add_charges([charge], payment)[0]


# --- the vet's bill for a visit -----------------------------------------------------------------


def visit_lines(lines):
    """[(category, amount, note)] from the vet's form: blank amounts dropped, the rest checked."""
    out = []
    for category, amount, note in lines:
        if str(amount or "").strip() in ("", "0"):
            continue
        if category not in VET_CATEGORIES:
            raise ValueError("choose what each line is for")
        out.append((category, parse_amount(amount, "each amount"), _clean(note, 200, "the note") or None))
    if len(out) > MAX_LINES:
        raise ValueError(f"at most {MAX_LINES} lines on one bill")
    return out


def check_visit_terms(request, vet_user, terms):
    """Deduction from the milk payment is the buyer's arrangement with its own route vets: a vet the
    farmer chose themselves is paid directly or on credit."""
    if terms == "milk_deduction" and (request.get("chosen_vet_id") is not None or db.route_vet_id(request["farmer_id"]) != vet_user["id"]):
        raise ValueError("only the route vet's bills can be deducted from the milk payment")


def bill_for_visit(request, vet_user, lines, terms, due_on=None, method=None, reference=None, today=None):
    """The charges a completed visit leaves: the vet's lines, plus the semen at the agreed price on an AI
    visit. `request` is the request as it will be once done (semen id and price settled).
    Returns (charges, payment) ready for db.add_charges; charges is empty if there is nothing to bill."""
    today = today or date.today()
    check_visit_terms(request, vet_user, terms)
    priced = visit_lines(lines)
    if request["kind"] == "ai" and request.get("semen_price_kes"):
        priced.append(("semen", parse_amount(request["semen_price_kes"]), request.get("semen_name")))
    if not priced:
        return [], None
    due_on, method, reference = _settlement(terms, due_on, today, method, reference, today)
    base = {"farmer_id": request["farmer_id"], "provider_user_id": vet_user["id"], "provider_name": vet_user["name"][:80],
            "charged_on": today, "terms": terms, "due_on": due_on, "request_id": request["id"],
            "created_by_user_id": vet_user["id"]}
    charges = [{**base, "category": c, "amount_kes": a, "description": n} for c, a, n in priced]
    payment = None if terms != "paid" else {"method": method, "paid_on": today, "reference": reference,
                                            "recorded_by_user_id": vet_user["id"]}
    return charges, payment


# --- payments and corrections -------------------------------------------------------------------


def _may_settle(user, charge):
    """Who may take a payment on (or void) a charge: the provider who raised it, or for a cost the farmer
    recorded themselves, that farmer. Returns nothing; raises if not allowed."""
    if charge is None:
        raise ValueError("that charge does not exist")
    if charge["provider_user_id"] is not None:
        if user.get("id") != charge["provider_user_id"]:
            raise ValueError("only the one who raised this charge can change it")
    elif user.get("role") != "farmer" or user.get("farmer_id") != charge["farmer_id"]:
        raise ValueError("only the farm that recorded this cost can change it")


def record_payment(user, charge_id, amount, method, reference=None, paid_on=None, today=None):
    """A payment received on a credit charge (part or all of what is owed). Returns the payment id."""
    today = today or date.today()
    paid_on = paid_on or today
    charge = db.get_charge(charge_id)
    _may_settle(user, charge)
    if method not in METHODS:
        raise ValueError("choose how it was paid")
    if paid_on > today:
        raise ValueError("the date cannot be in the future")
    if paid_on < charge["charged_on"]:
        raise ValueError("a payment cannot be before the charge")
    return db.add_payment(charge_id, parse_amount(amount), paid_on, method, _check_reference(reference), user["id"])


def void_charge(user, charge_id, reason):
    """Cancel a wrong charge: it stays on record as cancelled, with who and why."""
    charge = db.get_charge(charge_id)
    _may_settle(user, charge)
    reason = _clean(reason, 200, "the reason")
    if not reason:
        raise ValueError("say why it is being cancelled")
    if charge["voided_at"] is not None:
        raise ValueError("that charge is already cancelled")
    if not db.void_charge(charge_id, user["id"], reason):
        raise ValueError("a charge with payments on it cannot be cancelled")


# --- pure views: what is owed, the month statement, the vet's debtors ----------------------------


def owed(charge):
    """KES still owed on a charge: only credit charges carry a balance."""
    if charge["terms"] != "credit" or charge.get("voided_at") is not None:
        return 0.0
    return max(float(charge["amount_kes"]) - float(charge["paid_kes"] or 0), 0.0)


def statement(litres, milk_price, feed_cost, charges, open_credit, today):
    """One month so far, for the farmer. `charges` = this month's (not voided); `open_credit` = every credit
    charge still owed, any month. All amounts in KES.

    expected payout = milk income - what the buyer will deduct. It is an estimate: the buyer's own
    statement is the official record (and the app says so)."""
    income = None if milk_price is None else litres * float(milk_price)
    by_terms = {t: 0.0 for t in TERMS}
    by_category = {}
    for c in charges:
        a = float(c["amount_kes"])
        by_terms[c["terms"]] += a
        by_category[c["category"]] = by_category.get(c["category"], 0.0) + a
    deductions = by_terms["milk_deduction"]
    owing = {}
    for c in open_credit:
        rest = owed(c)
        if rest <= 0:
            continue
        o = owing.setdefault(c["provider_name"], {"supplier": c["provider_name"], "owed": 0.0, "overdue": 0.0, "next_due": None})
        o["owed"] += rest
        if c["due_on"] < today:
            o["overdue"] += rest
        elif o["next_due"] is None or c["due_on"] < o["next_due"]:
            o["next_due"] = c["due_on"]
    total_costs = float(feed_cost or 0) + sum(by_terms.values())
    return {
        "litres": litres,
        "income": income,
        "deductions": deductions,
        "expected_payout": None if income is None else income - deductions,
        "paid_elsewhere": by_terms["paid"],
        "credit_this_month": by_terms["credit"],
        "feed_cost": float(feed_cost or 0),
        "by_category": {CATEGORIES[k]: v for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])},
        "total_costs": total_costs,
        "after_costs": None if income is None else income - total_costs,
        "owing": sorted(owing.values(), key=lambda o: (-o["overdue"], -o["owed"])),
        "owed_total": sum(o["owed"] for o in owing.values()),
    }


def debtors(charges, today):
    """A vet's (or agrovet's) open credit, one row per farm, most overdue first."""
    farms = {}
    for c in charges:
        rest = owed(c)
        if rest <= 0:
            continue
        d = farms.setdefault(c["farmer_id"], {"farmer_id": c["farmer_id"], "farm": c["farm_name"] or c["farmer_name"],
                                              "phone": c["farmer_phone"], "owed": 0.0, "overdue": 0.0, "days_overdue": 0,
                                              "charges": []})
        d["owed"] += rest
        d["charges"].append(c)
        if c["due_on"] < today:
            d["overdue"] += rest
            d["days_overdue"] = max(d["days_overdue"], (today - c["due_on"]).days)
    return sorted(farms.values(), key=lambda d: (-d["days_overdue"], -d["owed"]))
