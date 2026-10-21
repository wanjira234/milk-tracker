"""Which cows are milking, and the cows-in-milk count worked out from the cow records. Pure.

A cow is milking from the day she calves (or is recorded as already in milk) until the day
she is dried off. Calves, heifers and bulls never have those events, so they are never
counted. A cow sold or dead stops counting from the day she left.
"""
LACTATION_KINDS = {"calved": "milking", "milking": "milking", "dried_off": "dry"}


def lactation_on(events, day):
    """'milking', 'dry', or None (nothing recorded yet) for ONE cow on `day`.
    Several events on one day: the later-recorded one (higher id) wins."""
    state = None
    relevant = sorted(
        (e for e in events if e["kind"] in LACTATION_KINDS and e["event_date"] <= day),
        key=lambda e: (e["event_date"], e.get("id", 0)),
    )
    for e in relevant:
        state = LACTATION_KINDS[e["kind"]]
    return state


def _counts_on(cows, events_by_cow, day):
    n = 0
    for c in cows:
        if c["sex"] != "female":
            continue
        if c.get("retired_on") and c["retired_on"] <= day:
            continue
        if lactation_on(events_by_cow.get(c["id"], []), day) == "milking":
            n += 1
    return n


def _group(events):
    by_cow = {}
    for e in events:
        by_cow.setdefault(e["cow_id"], []).append(e)
    return by_cow


def cows_in_milk_on(cows, events, day):
    """How many cows were milking on `day`, or None before any milking was recorded."""
    by_cow = _group(events)
    first = [e["event_date"] for e in events if e["kind"] in ("calved", "milking")]
    if not first or day < min(first):
        return None
    return _counts_on(cows, by_cow, day)


def history(cows, events):
    """Change points [{effective_date, cows_in_milk}], NEWEST first, like the typed-in log.
    Only dates where the count changed; empty until a milking has been recorded."""
    by_cow = _group(events)
    days = {e["event_date"] for e in events if e["kind"] in LACTATION_KINDS}
    days |= {c["retired_on"] for c in cows if c.get("retired_on")}
    out, last = [], None
    for d in sorted(days):
        n = cows_in_milk_on(cows, events, d)
        if n is None or n == last:
            continue
        out.append({"effective_date": d, "cows_in_milk": n})
        last = n
    return list(reversed(out))
