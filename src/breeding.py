"""Where each cow is in her breeding cycle, and when she is due for deworming. Pure.

The dates are TYPICAL figures for cattle, shown as estimates ("about"): the vet's word wins.
  - a cow comes back on heat about every 21 days when she is not in calf;
  - she is usually checked for pregnancy from about 60 days after service;
  - pregnancy lasts about 283 days, and a cow is usually dried off about 60 days before calving;
  - she is usually ready to be served again from about 60 days after calving;
  - cattle are dewormed about every 3 months (90 days).
"""
from datetime import timedelta

HEAT_CYCLE_DAYS = 21
PREGNANCY_CHECK_DAYS = 60
GESTATION_DAYS = 283
DRY_OFF_BEFORE_CALVING_DAYS = 60
SERVE_AFTER_CALVING_DAYS = 60
DEWORM_EVERY_DAYS = 90

KINDS = {
    "heat": "In heat",
    "served": "Served (AI or bull)",
    "confirmed_pregnant": "Confirmed in calf",
    "not_pregnant": "Checked: not in calf",
    "calved": "Calved",
    "aborted": "Lost the calf",
    "dried_off": "Dried off (stopped milking)",
}


def cow_status(events, today):
    """events = [{"event_date", "kind", "semen"}] for ONE cow, any order.

    Returns {"state", "label", "next", "due", "dry"}:
      state  open | served | in_calf | calved | new
      label  what to show as her status
      next   what to do or watch for next, in words (or None)
      due    expected calving date when served or in calf, else None
      dry    True when she is in her dry period: dried off by hand, or in calf and within
             60 days of the due date (a calving ends it)
    """
    manual_dry = False
    last_heat = served_on = calved_on = None
    semen = None
    state = "new"
    for e in sorted(events, key=lambda e: e["event_date"]):
        kind, day = e["kind"], e["event_date"]
        if kind == "heat":
            last_heat, state, served_on = day, "open", None
        elif kind == "served":
            served_on, semen, state = day, e.get("semen"), "served"
        elif kind == "confirmed_pregnant":
            if served_on is not None:
                state = "in_calf"
        elif kind in ("not_pregnant", "aborted"):
            state, served_on = "open", None
        elif kind == "calved":
            calved_on, state, served_on, last_heat, manual_dry = day, "calved", None, None, False
        elif kind == "dried_off":
            manual_dry = True
    fmt = lambda d: d.strftime("%d %b %Y")  # noqa: E731

    def result(state, label, nxt, due=None, computed_dry=False):
        return {"state": state, "label": label, "next": nxt, "due": due, "dry": manual_dry or computed_dry}

    if state == "new":
        return result(state, "No breeding records yet", "Record her next heat or service.")
    if state == "open":
        nxt = (
            f"Watch for heat about {fmt(last_heat + timedelta(days=HEAT_CYCLE_DAYS))}."
            if last_heat else "Watch for heat."
        )
        return result(state, "Not in calf", nxt)
    if state == "calved":
        ready = calved_on + timedelta(days=SERVE_AFTER_CALVING_DAYS)
        label = f"Calved {fmt(calved_on)}"
        nxt = f"Usually ready to be served from about {fmt(ready)}." if ready > today else "Ready to be served: watch for heat."
        return result(state, label, nxt)
    due = served_on + timedelta(days=GESTATION_DAYS)
    with_semen = f" with {semen}" if semen else ""
    if state == "served":
        check = served_on + timedelta(days=PREGNANCY_CHECK_DAYS)
        if today < served_on + timedelta(days=HEAT_CYCLE_DAYS):
            nxt = f"If she comes on heat about {fmt(served_on + timedelta(days=HEAT_CYCLE_DAYS))}, the service did not hold."
        elif today < check:
            nxt = f"No return to heat so far. Ask the vet to check for pregnancy from about {fmt(check)}."
        else:
            nxt = "Time to have the vet check for pregnancy, then record the result."
        return result(state, f"Served {fmt(served_on)}{with_semen}", nxt, due)
    days = (due - today).days
    dry = due - timedelta(days=DRY_OFF_BEFORE_CALVING_DAYS)
    if manual_dry and today < dry:
        nxt = f"Dried off early. Calving is expected about {fmt(due)}."
    elif days < 0:
        nxt = f"Calving was expected about {fmt(due)}. Record the calving when it happens."
    elif today < dry:
        nxt = f"Dry off about {fmt(dry)}."
    else:
        nxt = "Dry period: she should be dry now. Prepare for calving."
    return result(state, f"In calf, due about {fmt(due)}{with_semen}", nxt, due, computed_dry=today >= dry)


def deworm_status(last_given, today):
    """last_given = date of the most recent deworming (herd-wide or her own), or None.

    Returns {"state": "never"|"ok"|"soon"|"overdue", "due", "text"}. 'soon' = due within 14 days.
    """
    if last_given is None:
        return {"state": "never", "due": None, "text": "Never recorded"}
    due = last_given + timedelta(days=DEWORM_EVERY_DAYS)
    days = (due - today).days
    if days < 0:
        return {"state": "overdue", "due": due, "text": f"Overdue by {-days} day(s)"}
    if days <= 14:
        return {"state": "soon", "due": due, "text": f"Due in {days} day(s)"}
    return {"state": "ok", "due": due, "text": f"Due {due.strftime('%d %b %Y')}"}
