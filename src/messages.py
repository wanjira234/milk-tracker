"""Turn a decision into an SMS, and check any rewording of it. Pure: no network, no database.

The numbers and feed names in a message come from the decision, never from a language model.
`template_message` writes a plain version from the facts; `src/llm.py` may ask Claude Haiku to
phrase it more naturally, and `check_message` rejects the rewording if it changes a figure,
drops the feed, flips the direction, makes a promise, adds a link, or won't fit in two SMS
segments. A rejected rewording falls back to the template, so what a farmer receives is
always something the model actually said.

The Swahili wording is a DRAFT: have a Kiswahili speaker read it before any farmer gets it.
"""
import math
import re

from src.sms import MAX_SEGMENTS, gsm_length, sms_segments
from src.suggestions import MAX_STEP

APP_NAME = "Milk Tracker"  # working name; change here when the final name is chosen
LANGUAGES = ("en", "sw")

# --- facts ------------------------------------------------------------------


def _num(x):
    return f"{x:g}"


def _plural(unit, n):
    unit = unit.strip()
    return unit if n == 1 or unit.lower().endswith("s") else unit + "s"


def _digits_in(*texts):
    return {float(m) for t in texts for m in re.findall(r"\d+(?:\.\d+)?", t or "")}


def _amount(advice):
    """How big the step is, in the farm's own unit when it is at least half a unit, else kg.

    Returns (text, [numbers], kg_shown) or None if the step rounds to nothing a farmer could
    measure. kg_shown is the exact kg when the text is in kg, else None (units are converted).
    """
    units = advice.get("step_units")
    if units:
        return f"{_num(units)} {_plural(advice['unit'], units)}", [float(units)], None
    # round DOWN so the step never goes past the 10% limit; below 0.1 kg is not measurable
    kg = advice.get("step_kg_used", advice["step_kg"])
    value = math.floor(kg * 10 + 1e-9) / 10 if kg < 10 else math.floor(kg + 1e-9)
    if value < 0.1:
        return None
    return f"{_num(value)} kg", [float(value)], float(value)


def facts_from_decision(decision, lang="en"):
    """The facts an SMS may state, or None when there is nothing worth sending.

    Nothing is sent when the decision is 'none', or when the recommended step is too small
    to measure (better silent than an instruction of 0.0 kg).
    """
    if lang not in LANGUAGES:
        raise ValueError(f"language must be one of {LANGUAGES}")
    kind = decision["kind"]
    if kind == "advice":
        a = decision["advice"]
        amount = _amount(a)
        if amount is None:
            return None
        text, numbers, kg_shown = amount
        used = a.get("step_kg_used", a["step_kg"])
        shown = kg_shown if kg_shown is not None else used  # the kg the farmer is told to change by
        # the gain and the percentage describe the amount in the text, rounded down (never oversell)
        gain = math.floor(a["gain_per_day_at_least"] * shown / used + 1e-9)
        percent = max(1, math.floor(shown / a["recent_kg"] * 100 + 1e-9))
        numbers = numbers + [float(percent)]
        if gain >= 1:
            numbers.append(float(gain))
        return {
            "kind": "advice", "lang": lang, "verdict": a["verdict"], "feed": a["feed"],
            "amount": text, "percent": percent, "gain": gain if gain >= 1 else None,
            "numbers": numbers, "extra_numbers": sorted(_digits_in(a["feed"], a.get("unit"))),
        }
    if kind == "nudge":
        items = decision["nudges"][:2]
        numbers = [float(n["days_needed"]) for n in items if n["code"] == "few_days"]
        extra = {3.0} if any(n["code"] == "few_days" for n in items) else set()  # "all 3 milkings"
        for n in items:
            extra |= _digits_in(n.get("feed"))
        return {
            "kind": "nudge", "lang": lang,
            "items": [{k: n[k] for k in ("code", "days_needed", "feed") if k in n} for n in items],
            "feeds": [n["feed"] for n in items if n.get("feed")],
            "numbers": numbers, "extra_numbers": sorted(extra),
        }
    return None


# --- the plain template ------------------------------------------------------

_ADVICE = {
    "en": {
        "increase": "{app}: your records suggest more {feed} pays. Try {amount} more a day ({percent}% more than now) and keep logging.{gain}",
        "decrease": "{app}: your records suggest less {feed} saves money. Try {amount} less a day ({percent}% less than now) and keep logging.{gain}",
        "gain_increase": " Likely worth at least KES {gain} a day.",
        "gain_decrease": " Likely saves at least KES {gain} a day.",
    },
    "sw": {
        "increase": "{app}: rekodi zako zinaonyesha kuongeza {feed} kuna faida. Jaribu kuongeza {amount} kwa siku ({percent}% zaidi ya sasa) na uendelee kuandika.{gain}",
        "decrease": "{app}: rekodi zako zinaonyesha kupunguza {feed} kunaokoa pesa. Jaribu kupunguza {amount} kwa siku ({percent}% chini ya sasa) na uendelee kuandika.{gain}",
        "gain_increase": " Huenda faida ni angalau KES {gain} kwa siku.",
        "gain_decrease": " Huenda ukaokoa angalau KES {gain} kwa siku.",
    },
}

_NUDGE = {
    "en": {
        "intro": "{app}: to give you feed advice, please ",
        "join": " and ",
        "no_cows": "tell the app how many cows are in milk",
        "no_price": "set the milk price per litre",
        "few_days": "log {n} more day(s) with all 3 milkings and the feed",
        "no_cost": "add the price of {feed}",
    },
    "sw": {
        "intro": "{app}: ili kukupa ushauri wa chakula, tafadhali ",
        "join": " na ",
        "no_cows": "weka idadi ya ng'ombe wanaokamuliwa",
        "no_price": "weka bei ya maziwa kwa lita",
        "few_days": "andika siku {n} zaidi zenye kukamua mara 3 na chakula",
        "no_cost": "weka bei ya {feed}",
    },
}


def template_message(facts):
    """The plain, always-correct message for these facts."""
    t = (_ADVICE if facts["kind"] == "advice" else _NUDGE)[facts["lang"]]
    if facts["kind"] == "advice":
        gain = t["gain_" + facts["verdict"]].format(gain=facts["gain"]) if facts["gain"] else ""
        return t[facts["verdict"]].format(
            app=APP_NAME, feed=facts["feed"], amount=facts["amount"], percent=facts["percent"], gain=gain,
        )
    parts = [
        t[i["code"]].format(n=_num(i.get("days_needed", 0)), feed=i.get("feed", ""))
        for i in facts["items"]
    ]
    return t["intro"].format(app=APP_NAME) + t["join"].join(parts) + "."


# --- checking a rewording ----------------------------------------------------

_REPLACEMENTS = {
    "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
    "…": "...", "×": "x", " ": " ", "→": "->",
}
_DIRECTION_WORDS = {
    "en": {"increase": r"\b(less|reduce|cut|decrease|lower|fewer)\b", "decrease": r"\b(more|increase|extra|raise|add)\b"},
    "sw": {"increase": r"(punguza|kupunguza|chini)", "decrease": r"(ongeza|kuongeza|zaidi)"},
}
_NUMBER_WORDS = r"\b(one|two|three|four|five|six|seven|eight|nine|ten|half|double|twice|moja|mbili|tatu|nne|tano|sita|saba|nane|tisa|kumi|nusu)\b"
_PROMISES = r"(guarantee|definitely|certain|for sure|promise|hakika|uhakika|ahadi)"
_LINKS = r"(https?://|www\.|\.com\b|\.co\.ke|\.ke\b)"


def normalize(text):
    """Plain single-line text: smart quotes and dashes become ASCII, whitespace is collapsed."""
    for old, new in _REPLACEMENTS.items():
        text = text.replace(old, new)
    return " ".join(text.split())


def _numbers_in(text):
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)  # 1,500 is one number
    return [float(m) for m in re.findall(r"\d+(?:\.\d+)?", text)]


def check_message(text, facts):
    """Problems that make `text` unsafe to send for these facts. An empty list means it is fine."""
    problems = []
    text = normalize(text)
    if not text:
        return ["empty message"]
    if gsm_length(text) is None:
        problems.append("uses characters outside the basic SMS alphabet (emoji or symbols)")
    if sms_segments(text) > MAX_SEGMENTS:
        problems.append(f"too long: {sms_segments(text)} SMS segments, the limit is {MAX_SEGMENTS}")
    if not text.startswith(APP_NAME + ":"):
        problems.append(f"does not start with '{APP_NAME}:'")
    # a number written as a word could change a figure without showing up as a digit
    allowed_words = set(re.findall(_NUMBER_WORDS, template_message(facts).lower()))
    for w in sorted(set(re.findall(_NUMBER_WORDS, text.lower())) - allowed_words):
        problems.append(f"uses the number word '{w}', which is not in the facts")
    if re.search(r"[*_`#]", text):
        problems.append("contains formatting characters")
    if re.search(_LINKS, text, re.I):
        problems.append("contains a link")
    if re.search(_PROMISES, text, re.I):
        problems.append("makes a promise the model can't back")

    found = set(_numbers_in(text))
    required = set(facts["numbers"])
    allowed = required | set(facts["extra_numbers"])
    for n in sorted(required - found):
        problems.append(f"missing the number {_num(n)}")
    for n in sorted(found - allowed):
        problems.append(f"contains the number {_num(n)}, which is not in the facts")

    lowered = text.lower()
    names = [facts["feed"]] if facts["kind"] == "advice" else facts["feeds"]
    for name in names:
        if name.lower() not in lowered:
            problems.append(f"does not name the feed '{name}'")
    if facts["kind"] == "advice":
        # the feed's own name ("extra protein") must not count as a direction word
        outside_name = lowered.replace(facts["feed"].lower(), " ")
        if re.search(_DIRECTION_WORDS[facts["lang"]][facts["verdict"]], outside_name):
            problems.append(f"seems to say the opposite of '{facts['verdict']}'")
    return problems
