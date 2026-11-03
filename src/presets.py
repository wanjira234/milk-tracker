"""The feeds most Kenyan dairy farms use, with the way they're usually bought and a rough weight.

The weights are typical figures for a starting point, not measurements: every farm can change them
(a pickup of napier varies a lot), and the app says they are estimates. Prices are left to the farm,
because they change by area and season.
"""

# (name, unit, kg in one unit: a rough typical figure)
COMMON_FEEDS = (
    ("dairy meal", "70 kg bag", 70),
    ("maize germ", "70 kg bag", 70),
    ("hay", "bale", 15),
    ("napier", "pickup load", 1000),
    ("silage", "50 kg bag", 50),
    ("machicha", "bag", 50),
    ("pineapple waste", "pickup load", 1000),
    ("banana stems", "trunk", 25),
    ("maize stalks", "bundle", 10),
    ("lucerne", "bale", 20),
)


def missing(catalogue):
    """The common feeds this farm hasn't added yet."""
    have = {i["name"].lower() for i in catalogue}
    return [f for f in COMMON_FEEDS if f[0] not in have]
