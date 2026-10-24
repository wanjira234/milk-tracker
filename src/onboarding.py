"""The farmer's 'get started' checklist: what to set up, in the order that makes the rest work.

Pure functions, no Streamlit or database; the home page reads the facts and shows the steps."""

# (key, what the farmer does, why it matters, page)
STEPS = [
    ("price", "Set your milk price", "so the app can show what is left after feed", "pages/4_farm_setup.py"),
    ("cows", "Add your cows", "so the herd and vet visits have names", "pages/5_cows.py"),
    ("in_milk", "Say how many cows are in milk", "so one cow calving is not mistaken for a feed effect", "pages/4_farm_setup.py"),
    ("feeds", "Add what you feed", "a truck load, bales or bags, bought or grown", "pages/4_farm_setup.py"),
    ("first_log", "Log today's milk and feed", "advice starts after 14 full days of records", "pages/2_feed_log.py"),
]


def checklist(price, cows, in_milk, feeds, logged):
    """[(key, label, why, page, done)] in order. The arguments are facts about the farm: a milk price or
    None, how many cows, cows-in-milk or None, how many feeds, how many days of milk logged."""
    done = {
        "price": price is not None,
        "cows": bool(cows),
        "in_milk": in_milk is not None,
        "feeds": bool(feeds),
        "first_log": bool(logged),
    }
    return [(key, label, why, page, done[key]) for key, label, why, page in STEPS]


def next_step(items):
    """The first step not done, or None when the farm is set up."""
    return next((item for item in items if not item[4]), None)
