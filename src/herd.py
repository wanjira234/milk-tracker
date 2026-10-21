"""What to show for each animal: calf, heifer or cow, her family, and whether she is milking. Pure.

Typical figures (shown as "usually", the vet's word wins): calves are weaned at about 3 months;
a heifer is first served at about 15 months.
"""
from src.breeding import cow_status

WEANING_MONTHS = 3
FIRST_SERVICE_MONTHS = 15
DAYS_PER_MONTH = 30.4


def age_months(born_on, today):
    return (today - born_on).days / DAYS_PER_MONTH


def age_text(born_on, today):
    days = (today - born_on).days
    if days < 0:
        return None
    if days < 60:
        return f"{days} day(s) old"
    months = int(days / DAYS_PER_MONTH)
    if months < 24:
        return f"{months} months old"
    return f"{months // 12} years old"


def animal_card(cow, events, mother_tag, offspring, today):
    """cow = {"kind","tag","sex","born_on","weaned_on"}; events = her breeding events;
    offspring = [{"tag","born_on"}]. Returns {"stage","status","milk","next","family"}."""
    status = cow_status(events, today)
    family = []
    if mother_tag:
        family.append(f"Mother: {mother_tag}")
    if offspring:
        parts = [f"{o['tag']}" + (f" (born {o['born_on'].strftime('%d %b %Y')})" if o.get("born_on") else "") for o in offspring]
        family.append("Calves: " + ", ".join(parts))
    kind = cow["kind"]

    if kind == "calf":
        age = age_text(cow["born_on"], today) if cow.get("born_on") else None
        sex = "Female calf" if cow.get("sex") != "male" else "Male calf"
        if cow.get("weaned_on"):
            text, nxt = f"{sex}, weaned {cow['weaned_on'].strftime('%d %b %Y')}", None
        else:
            text = f"{sex}, still on milk" + (f", {age}" if age else "")
            if cow.get("born_on") and age_months(cow["born_on"], today) >= WEANING_MONTHS:
                nxt = "Old enough to wean. Record the weaning date when she or he is weaned."
            else:
                nxt = f"Usually weaned at about {WEANING_MONTHS} months."
        return {"stage": "Calf", "status": text, "milk": None, "next": nxt, "family": family}

    if kind == "heifer":
        if status["state"] == "new":
            text = "Waiting for first heat"
            if cow.get("born_on"):
                months = age_months(cow["born_on"], today)
                if months < FIRST_SERVICE_MONTHS:
                    nxt = f"{int(months)} months old. Usually served for the first time at about {FIRST_SERVICE_MONTHS} months."
                else:
                    nxt = "Old enough to serve: watch for her first heat."
            else:
                nxt = "Watch for her first heat."
            return {"stage": "Heifer", "status": text, "milk": None, "next": nxt, "family": family}
        return {"stage": "Heifer", "status": status["label"], "milk": None, "next": status["next"], "family": family}

    return {
        "stage": "Cow", "status": status["label"], "milk": "Dry" if status["dry"] else "Milking",
        "next": status["next"], "family": family,
    }


def milking_summary(cows, events_by_cow, today):
    """(milking, dry) counts among the grown cows (kind 'cow'). A cow with no records counts as milking."""
    milking = dry = 0
    for c in cows:
        if c["kind"] != "cow":
            continue
        if cow_status(events_by_cow.get(c["id"], []), today)["dry"]:
            dry += 1
        else:
            milking += 1
    return milking, dry
