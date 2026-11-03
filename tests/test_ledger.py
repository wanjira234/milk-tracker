"""The ledger's input checks and pure views (statement, debtors). No database needed."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from src import ledger

TODAY = date(2026, 11, 3)


def charge(**kw):
    base = {"id": 1, "farmer_id": 1, "farmer_name": "Mama A", "farm_name": "A Farm", "farmer_phone": "+254700000001",
            "provider_name": "Dr Kibet", "category": "vet_visit", "amount_kes": Decimal("1000"), "paid_kes": Decimal("0"),
            "terms": "credit", "due_on": TODAY + timedelta(days=10), "voided_at": None}
    return {**base, **kw}


@pytest.mark.parametrize("value, expected", [("1500", Decimal("1500.00")), (" 1,200.5 ", Decimal("1200.50")), (99.999, Decimal("100.00"))])
def test_amounts_are_shillings_rounded_to_cents(value, expected):
    assert ledger.parse_amount(value) == expected


@pytest.mark.parametrize("value, why", [("", "shillings"), ("abc", "shillings"), ("nan", "more than 0"), ("inf", "shillings"),
                                        ("0", "more than 0"), ("-5", "more than 0"), ("1000001", "at most")])
def test_bad_amounts_are_refused(value, why):
    with pytest.raises(ValueError, match=why):
        ledger.parse_amount(value)


def test_credit_gets_a_due_date_and_cannot_run_too_long():
    assert ledger._settlement("credit", None, TODAY, None, None, TODAY)[0] == TODAY + timedelta(days=30)
    with pytest.raises(ValueError, match="before the charge"):
        ledger._settlement("credit", TODAY - timedelta(days=1), TODAY, None, None, TODAY)
    with pytest.raises(ValueError, match="at most 180"):
        ledger._settlement("credit", TODAY + timedelta(days=181), TODAY, None, None, TODAY)


def test_paid_now_needs_a_method_and_a_clean_reference():
    assert ledger._settlement("paid", None, TODAY, "mpesa", " sk3abc12xy ", TODAY) == (None, "mpesa", "SK3ABC12XY")
    with pytest.raises(ValueError, match="how it was paid"):
        ledger._settlement("paid", None, TODAY, None, None, TODAY)
    for bad in ("<script>", "a b", "x" * 41):
        with pytest.raises(ValueError, match="reference"):
            ledger._settlement("paid", None, TODAY, "mpesa", bad, TODAY)
    with pytest.raises(ValueError, match="how it is paid"):
        ledger._settlement("barter", None, TODAY, None, None, TODAY)


def test_visit_lines_drop_blanks_and_check_the_rest():
    assert ledger.visit_lines([("vet_visit", "800", ""), ("drugs", "", "none"), ("drugs", "0", None)]) == [
        ("vet_visit", Decimal("800.00"), None)]
    with pytest.raises(ValueError, match="what each line is for"):
        ledger.visit_lines([("semen", "500", "")])  # semen comes from the AI visit itself
    with pytest.raises(ValueError, match="at most 5"):
        ledger.visit_lines([("drugs", "10", "")] * 6)


def test_only_credit_carries_a_balance():
    assert ledger.owed(charge(paid_kes=Decimal("300"))) == 700
    assert ledger.owed(charge(paid_kes=Decimal("1000"))) == 0
    assert ledger.owed(charge(terms="paid")) == 0
    assert ledger.owed(charge(terms="milk_deduction")) == 0
    assert ledger.owed(charge(voided_at=TODAY)) == 0


def test_the_statement_takes_the_buyers_deductions_off_the_milk_income():
    month = [charge(terms="milk_deduction", amount_kes=Decimal("1500"), category="semen"),
             charge(terms="paid", amount_kes=Decimal("2000"), category="agrovet", provider_name="Mboga Center"),
             charge(terms="credit", amount_kes=Decimal("800"))]
    open_credit = [charge(terms="credit", amount_kes=Decimal("800")),
                   charge(terms="credit", amount_kes=Decimal("600"), paid_kes=Decimal("100"), due_on=TODAY - timedelta(days=3),
                          provider_name="Mboga Center")]
    s = ledger.statement(litres=1000.0, milk_price=Decimal("50"), feed_cost=20000, charges=month, open_credit=open_credit, today=TODAY)
    assert s["income"] == 50000 and s["deductions"] == 1500 and s["expected_payout"] == 48500
    assert s["paid_elsewhere"] == 2000 and s["credit_this_month"] == 800
    assert s["total_costs"] == 20000 + 1500 + 2000 + 800 and s["after_costs"] == 50000 - 24300
    assert list(s["by_category"]) == ["Agrovet goods", "AI semen", "Vet visit"]  # biggest first
    assert s["owed_total"] == 800 + 500
    assert s["owing"][0] == {"supplier": "Mboga Center", "owed": 500, "overdue": 500, "next_due": None}  # overdue first
    assert s["owing"][1]["next_due"] == TODAY + timedelta(days=10)


def test_a_statement_without_a_milk_price_still_shows_costs():
    s = ledger.statement(litres=500.0, milk_price=None, feed_cost=None, charges=[], open_credit=[], today=TODAY)
    assert s["income"] is None and s["expected_payout"] is None and s["after_costs"] is None and s["total_costs"] == 0


def test_debtors_put_the_longest_overdue_farm_first():
    rows = [charge(farmer_id=1, amount_kes=Decimal("1000")),
            charge(farmer_id=2, farm_name="B Farm", amount_kes=Decimal("400"), due_on=TODAY - timedelta(days=20)),
            charge(farmer_id=2, farm_name="B Farm", amount_kes=Decimal("300"), due_on=TODAY - timedelta(days=5)),
            charge(farmer_id=3, amount_kes=Decimal("500"), paid_kes=Decimal("500"))]  # paid off: not a debtor
    d = ledger.debtors(rows, TODAY)
    assert [r["farmer_id"] for r in d] == [2, 1]
    assert d[0]["owed"] == 700 and d[0]["overdue"] == 700 and d[0]["days_overdue"] == 20
    assert d[1]["overdue"] == 0 and d[1]["days_overdue"] == 0


def test_typed_text_cannot_become_a_link_or_formatting():
    from src.ui import md

    assert md("[pay here](http://x.io)") == "\\[pay here\\]\\(http\\://x\\.io\\)"
    assert md("**Mboga** Center") == "\\*\\*Mboga\\*\\* Center"
    assert md(None) == ""


def test_feed_is_counted_once_purchases_win_over_the_feed_log():
    from_log = ledger.statement(100.0, Decimal("50"), 3000, [charge(terms="paid", category="agrovet")], [], TODAY)
    assert from_log["feed_from_log"] and from_log["total_costs"] == 3000 + 1000
    bought = ledger.statement(100.0, Decimal("50"), 3000, [charge(terms="paid", category="feed", amount_kes=Decimal("5000"))], [], TODAY)
    assert not bought["feed_from_log"] and bought["total_costs"] == 5000
