"""Two numbers shared by modules that should not have to load the heavy maths libraries just to read them."""
MIN_COMPLETE_DAYS = 14  # days with all milkings, cows in milk known, and feed logged, before any advice
MAX_STEP = 0.10         # advice never moves a feed by more than 10%
