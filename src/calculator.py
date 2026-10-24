"""The feed calculator: turn 'a truck load for KES X' into a price per kg and per everyday measure.

Pure functions, no Streamlit or database. Everything is an ESTIMATE: a truck load is counted
in tillies or mtungis, not weighed, and that is fine. The result is saved to the farm's feed
catalogue, and from then on logging a feed is just 'how many tillies'.

Fixed measures (agreed with the farm): a 1 kg tilly, a 2 kg tilly, the big cut-off
mtungi at about 20 kg and the 50 kg bag. A bucket (20 L) holds a different weight of every feed (wet pineapple
waste vs dry bran), so its kg is entered per feed, ideally after weighing one full bucket once.
"""
MAX_TOTAL_KG = 50_000
MAX_TOTAL_PRICE = 5_000_000

# name shown to the farmer -> (unit word saved in the catalogue, kg)
FIXED_MEASURES = {
    "1 kg tilly": ("tilly", 1.0),
    "2 kg tilly": ("2 kg tilly", 2.0),
    "big mtungi (about 20 kg)": ("mtungi", 20.0),
    "50 kg bag": ("bag", 50.0),  # wheat bran, dairy meal and the like come in 50 kg bags
}


def _positive(value, label):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number") from None
    if value != value or value <= 0:
        raise ValueError(f"{label} must be greater than zero")
    return value


def total_kg(count, kg_each):
    """Kg in `count` measures of `kg_each` kg."""
    kg = _positive(count, "how many") * _positive(kg_each, "kg in one measure")
    if kg > MAX_TOTAL_KG:
        raise ValueError(f"that is over {MAX_TOTAL_KG:,} kg; check the numbers")
    return kg


def price_per_kg(total_price, kg):
    """KES per kg. A price of 0 is allowed (a free feed); a missing price is not."""
    try:
        price = float(total_price)
    except (TypeError, ValueError):
        raise ValueError("price must be a number") from None
    if price != price or price < 0:
        raise ValueError("price cannot be negative")
    if price > MAX_TOTAL_PRICE:
        raise ValueError("price looks too high; check for a typo")
    return price / _positive(kg, "total kg")


def load_buckets(days, buckets_per_day):
    """Buckets in a load that is used up over `days` days at `buckets_per_day` a day.

    A truck load is rarely weighed or counted when it is offloaded; it is fed out in buckets over days,
    so the buckets are worked out from how long it lasted."""
    buckets = _positive(days, "days") * _positive(buckets_per_day, "buckets a day")
    if buckets > 100_000:
        raise ValueError("that is a lot of buckets; check the numbers")
    return buckets


def breakdown(total_price, kg, bucket_kg=None):
    """Price per kg and per measure. Returns rows {"measure","unit","kg","kes"}, cheapest-first
    ordering not applied: measures stay in the same order so the table doesn't jump around."""
    per_kg = price_per_kg(total_price, kg)
    measures = dict(FIXED_MEASURES)
    if bucket_kg:
        measures[f"20 L bucket (about {bucket_kg:g} kg)"] = ("bucket", _positive(bucket_kg, "kg in a bucket"))
    return [
        {"measure": name, "unit": unit, "kg": each, "kes": per_kg * each}
        for name, (unit, each) in measures.items()
    ]


def money(x):
    """KES for people: whole shillings from 10 up, cents below, so a 1 kg tilly of cheap
    napier doesn't read as 'KES 3'."""
    return f"KES {x:,.0f}" if x >= 10 else f"KES {x:,.2f}"
