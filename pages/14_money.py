"""Money. Farmer: this month's statement, what is owed to whom, and costs from any supplier.
Vet: who owes me, taking payments, and correcting a wrong bill. The app records money; it moves none."""
from datetime import date, timedelta

import streamlit as st

from src.messages import ICON

from src import db, ledger
from src.auth import require_login
from src.ui import cap, md

st.set_page_config(page_title="Money", page_icon=ICON, layout="centered")
user = require_login(roles=("farmer", "vet"))


def kes(x):
    return "-" if x is None else f"KES {x:,.0f}"


def attempt(action, done):
    try:
        action()
    except ValueError as e:
        st.error(cap(e))
        return False
    st.success(done)
    return True


def pay_form(charge, key):
    """Take a payment on one credit charge (the logic checks who may and how much)."""
    rest = ledger.owed(charge)
    with st.form(key, clear_on_submit=True):
        c1, c2 = st.columns(2)
        amount = c1.text_input("Amount (KES)", value=f"{rest:.0f}", key=f"{key}_amt")
        method = c2.selectbox("How", list(ledger.METHODS), format_func=ledger.METHODS.get, key=f"{key}_method")
        ref = st.text_input("M-Pesa code (optional)", key=f"{key}_ref")
        if st.form_submit_button("Record payment"):
            if attempt(lambda: ledger.record_payment(user, charge["id"], amount, method, ref), "Payment recorded."):
                st.rerun()


def void_form(charge, key):
    with st.form(key, clear_on_submit=True):
        reason = st.text_input("Why cancel it?", key=f"{key}_why")
        if st.form_submit_button("Cancel this charge"):
            if attempt(lambda: ledger.void_charge(user, charge["id"], reason), "Cancelled. It stays on record as cancelled."):
                st.rerun()


def charge_line(c, safe=md):
    """One charge as a line; `safe` escapes the typed note for markdown (pass str for plain-text labels)."""
    tail = ledger.TERMS[c["terms"]]
    if c["terms"] == "credit":
        rest = ledger.owed(c)
        tail = f"owes {kes(rest)}, due {c['due_on']}" if rest else "paid off"
    note = f" · {safe(c['description'])}" if c["description"] else ""
    return f"{c['charged_on']} · {ledger.CATEGORIES[c['category']]}{note} · {kes(float(c['amount_kes']))} · {tail}"


today = date.today()

# --- the vet ------------------------------------------------------------------------------------
if user["role"] == "vet":
    st.title("Money")
    st.caption("Bills you raised when marking visits done. Payments go straight to you; this is your record.")
    mine = db.charges_for_provider(user["id"], credit_only=True)
    owing = ledger.debtors(mine, today)
    c1, c2 = st.columns(2)
    c1.metric("Owed to you", kes(sum(d["owed"] for d in owing)))
    c2.metric("Overdue", kes(sum(d["overdue"] for d in owing)))
    st.header("Who owes me")
    if not owing:
        st.caption("Nobody owes you anything.")
    for d in owing:
        with st.expander(f"{md(d['farm'])} · {kes(d['owed'])}" + (f" · {d['days_overdue']} days overdue" if d["days_overdue"] else "")):
            if d["phone"]:
                st.caption(d["phone"])
            for c in d["charges"]:
                st.write(charge_line(c))
                pay_form(c, f"pay_{c['id']}")
    st.header("Recent bills")
    recent = db.charges_for_provider(user["id"], limit=30)
    if not recent:
        st.caption("No bills yet. Add a fee or drugs when you mark a visit done.")
    for c in recent:
        with st.container(border=True):
            st.markdown(f"**{md(c['farm_name'] or c['farmer_name'])}** · " + charge_line(c))
            if (c["terms"] != "credit" or float(c["paid_kes"]) == 0) and st.toggle("Wrong? Cancel it", key=f"voidt_{c['id']}"):
                void_form(c, f"void_{c['id']}")
    st.stop()

# --- the farmer ---------------------------------------------------------------------------------
farmer_id = user["farmer_id"]
st.title("Money")
first = today.replace(day=1)
last_month = (first - timedelta(days=1)).replace(day=1)
which = st.radio("Month", ["this", "last"], format_func={"this": "This month", "last": "Last month"}.get,
                 horizontal=True, key="money_month")
start, end = (first, today) if which == "this" else (last_month, first - timedelta(days=1))

s = ledger.statement(db.month_litres(farmer_id, start, end), db.get_milk_price(farmer_id),
                     db.month_feed_spend(farmer_id, start), db.charges_for_farm(farmer_id, start, end),
                     db.open_credit_for_farm(farmer_id), today)
c1, c2, c3 = st.columns(3)
c1.metric("Milk income", kes(s["income"]), help=f"{s['litres']:,.0f} litres recorded x your milk price")
c2.metric("Buyer deductions", kes(s["deductions"]), help="Vet, semen and store costs taken off the milk payment")
c3.metric("Expected payout", kes(s["expected_payout"]))
if s["income"] is None:
    st.info("Set your milk price on Farm setup to see income and payout.")
st.caption("An estimate from your records. Your milk buyer's statement is the official figure; if they differ, ask the buyer.")
c1, c2 = st.columns(2)
c1.metric("All costs (incl. feed)", kes(s["total_costs"]))
c2.metric("Left after costs", kes(s["after_costs"]))
rows = [{"What": k, "KES": round(v)} for k, v in s["by_category"].items()]
if s["feed_from_log"] and s["feed_cost"]:
    rows.append({"What": "Feed (from the feed log)", "KES": round(s["feed_cost"])})
if rows:
    st.dataframe(rows, hide_index=True, use_container_width=True)
if s["feed_from_log"]:
    st.caption("Feed is counted from the feed log. Record feed purchases on Feed stock to count what you actually paid.")

st.header("What I owe")
if not s["owing"]:
    st.caption("Nothing on credit.")
for o in s["owing"]:
    st.write(f"**{md(o['supplier'])}**: {kes(o['owed'])}" + (f", of which {kes(o['overdue'])} is overdue" if o["overdue"] else "")
             + (f" · next due {o['next_due']}" if o["next_due"] else ""))
mine = [c for c in db.open_credit_for_farm(farmer_id) if c["provider_user_id"] is None]
if mine:
    with st.expander("Record a payment on something I recorded"):
        pick = st.selectbox("Which", [c["id"] for c in mine], format_func={c["id"]: f"{c['provider_name']} · " + charge_line(c, str) for c in mine}.get,
                            key="pay_pick")
        pay_form(next(c for c in mine if c["id"] == pick), "pay_own")
st.caption("Bills from a vet are marked paid by that vet when they receive your payment.")

st.header("Record a cost")
st.caption("Anything bought or owed outside the app: agrovet goods, the buyer's store, a vet without a login.")
with st.form("add_cost", clear_on_submit=True):
    c1, c2 = st.columns(2)
    supplier = c1.text_input("From", placeholder="Mboga Center", key="cost_from")
    category = c2.selectbox("For", list(ledger.FARMER_CATEGORIES), format_func=ledger.CATEGORIES.get, key="cost_cat")
    c1, c2 = st.columns(2)
    amount = c1.text_input("Amount (KES)", key="cost_amt")
    on = c2.date_input("Date", value=today, max_value=today, key="cost_day")
    note = st.text_input("What (optional)", placeholder="2 bags dairy meal", key="cost_note")
    terms = st.radio("Payment", list(ledger.TERMS), format_func=ledger.TERMS.get, horizontal=True, key="cost_terms")
    c1, c2 = st.columns(2)
    due = c1.date_input("Due by (if on credit)", value=today + timedelta(days=ledger.DEFAULT_CREDIT_DAYS), key="cost_due")
    method = c2.selectbox("Paid by (if paid now)", list(ledger.METHODS), format_func=ledger.METHODS.get, key="cost_method")
    ref = st.text_input("M-Pesa code (optional)", key="cost_ref")
    if st.form_submit_button("Save", type="primary"):
        if attempt(lambda: ledger.record_farm_cost(user, farmer_id, supplier, category, amount, on, terms,
                                                   due_on=due if terms == "credit" else None,
                                                   method=method if terms == "paid" else None,
                                                   reference=ref if terms == "paid" else None, description=note), "Saved."):
            st.rerun()

st.header("This month's records" if which == "this" else "Last month's records")
rows = db.charges_for_farm(farmer_id, start, end)
if not rows:
    st.caption("Nothing recorded.")
for c in rows:
    with st.container(border=True):
        st.markdown(f"**{md(c['provider_name'])}** · " + charge_line(c))
        if c["provider_user_id"] is None and (c["terms"] != "credit" or float(c["paid_kes"]) == 0) \
                and st.toggle("Wrong? Cancel it", key=f"voidt_{c['id']}"):
            void_form(c, f"void_{c['id']}")
