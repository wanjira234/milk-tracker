"""A shop's opening hours and the time slots a farmer can choose for pickup or delivery. Pure: no database.

`hours` is {weekday: {"opens": time, "closes": time, "delivers": bool}} with Monday = 0. A shop with no
hours set takes orders for any day, without a time (the shop then sets the time when it confirms).
"""
from datetime import datetime, time, timedelta

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SLOT_CHOICES = (30, 60, 120)
DEFAULT_SLOT = 60
LEAD_MINUTES = 60      # a same-day slot must start at least this long from now, so the shop can get it ready
HORIZON_DAYS = 14      # how far ahead a farmer can choose


def _minutes(t):
    return t.hour * 60 + t.minute


def _time(m):
    return time(m // 60, m % 60)


def slot_minutes(shop):
    m = (shop or {}).get("slot_minutes")
    return m if m in SLOT_CHOICES else DEFAULT_SLOT


def label(t, minutes=DEFAULT_SLOT):
    """'10:00-11:00' for a slot starting at t; 'Any time' for no time."""
    if t is None:
        return "Any time"
    end = _minutes(t) + minutes
    return f"{t:%H:%M}-{_time(min(end, 24 * 60 - 1)):%H:%M}"


def is_open(hours, day, fulfilment="pickup"):
    row = (hours or {}).get(day.weekday())
    return bool(row) and (fulfilment != "delivery" or row["delivers"])


def days_open(hours, today, fulfilment="pickup", days=HORIZON_DAYS, now=None, minutes=DEFAULT_SLOT):
    """The days a farmer can choose: every day when the shop set no hours, else the days it is open (and, for
    delivery, the days it delivers), leaving out today if no slot is left."""
    out = [today + timedelta(days=i) for i in range(days + 1)]
    if not hours:
        return out
    return [d for d in out if is_open(hours, d, fulfilment) and slots_on(hours, d, fulfilment, now, minutes)]


def slots_on(hours, day, fulfilment="pickup", now=None, minutes=DEFAULT_SLOT):
    """Slot start times on a day, or [] when closed. Today's slots start LEAD_MINUTES from now at the earliest."""
    if not is_open(hours, day, fulfilment):
        return []
    row = hours[day.weekday()]
    start, end = _minutes(row["opens"]), _minutes(row["closes"])
    first = start
    if now is not None and day == now.date():
        soonest = _minutes(now.time()) + LEAD_MINUTES
        first = max(start, start + -(-(soonest - start) // minutes) * minutes)  # next slot boundary after the lead
    return [_time(m) for m in range(first, end - minutes + 1, minutes)]


def check(hours, day, t, fulfilment="pickup", now=None, minutes=DEFAULT_SLOT):
    """Raise ValueError unless (day, t) is a time this shop can serve. No hours set: any day, no time."""
    if not hours:
        if t is not None:
            raise ValueError("this shop hasn't set its hours: choose a day and it will set the time")
        return
    if not is_open(hours, day, fulfilment):
        raise ValueError("the shop doesn't deliver that day" if fulfilment == "delivery" and is_open(hours, day)
                         else f"the shop is closed on {DAYS[day.weekday()]}s")
    if t is None:
        raise ValueError("choose a time")
    if t not in slots_on(hours, day, fulfilment, now, minutes):
        raise ValueError("choose one of the shop's times for that day")


def summary(hours):
    """'Mon-Sat 08:00-18:00 · delivers Tue, Fri' style text for the farmer."""
    if not hours:
        return "Hours not set"
    groups, prev = [], None
    for wd in range(7):
        row = hours.get(wd)
        key = (row["opens"], row["closes"]) if row else None
        if key and prev and prev[0] == key and prev[2] == wd - 1:
            prev[2] = wd
        else:
            prev = [key, wd, wd] if key else None
            if prev:
                groups.append(prev)
    text = ", ".join((DAYS[a][:3] if a == b else f"{DAYS[a][:3]}-{DAYS[b][:3]}") + f" {k[0]:%H:%M}-{k[1]:%H:%M}" for k, a, b in groups)
    deliver = [DAYS[wd][:3] for wd in range(7) if hours.get(wd) and hours[wd]["delivers"]]
    return text + (f" · delivers {', '.join(deliver)}" if deliver else " · pickup only")


def parse(rows):
    """Rows from the shop's hours form: [{"weekday", "open": bool, "opens": time, "closes": time, "delivers": bool}].
    Returns the hours dict, or raises ValueError."""
    out = {}
    for r in rows:
        if not r.get("open"):
            continue
        wd = int(r["weekday"])
        opens, closes = r.get("opens"), r.get("closes")
        if not isinstance(opens, time) or not isinstance(closes, time):
            raise ValueError(f"give opening and closing times for {DAYS[wd]}")
        if closes <= opens:
            raise ValueError(f"{DAYS[wd]}: closing must be after opening")
        out[wd] = {"opens": opens.replace(second=0, microsecond=0), "closes": closes.replace(second=0, microsecond=0),
                   "delivers": bool(r.get("delivers"))}
    return out


def now_local():
    """Now in Nairobi time (the shops' clock), as a naive datetime."""
    from datetime import timezone

    return datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)

