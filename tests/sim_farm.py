"""Simulated farms with a KNOWN true feed effect, for checking src/models.py.

Not a test file (pytest does not collect it). Used by test_models.py.
"""
import numpy as np
import pandas as pd

from src.models import cows_series


def make_farm(
    rng,
    n=60,
    effect=0.0,          # true extra litres per cow per day for 1 extra kg of dairy meal per cow per day
    cows=6,
    levels=(3, 4, 5, 6),  # herd kg/day of dairy meal; the farmer switches between these
    lag=2,                # milk responds to the meal averaged over today and the previous `lag` days
    noise=0.4,            # sd of daily litres per cow
    ar=0.5,               # day-to-day autocorrelation of that noise
    trend=-0.02,          # slow drift in litres per cow per day (lactation, season)
    together=False,       # second feed always moves with the meal
    dry_off_day=None,     # a cow is dried off from this day
    log_dry_off=True,     # whether the herd change is recorded
    meal_shift_at=None,   # the ration also changes by `meal_shift` kg from this day
    meal_shift=0.0,
):
    """Return (daily, feed_kg, cows) in the shapes src.models.feed_effects expects."""
    idx = pd.date_range("2026-08-01", periods=n, freq="D")

    def steps(choices, lo=3, hi=7):
        out = []
        while len(out) < n + lag:
            out += [rng.choice(choices)] * int(rng.integers(lo, hi))
        return np.array(out[: n + lag], dtype=float)

    meal = steps(list(levels))
    if meal_shift_at is not None:
        meal[meal_shift_at + lag:] += meal_shift
    banana = meal * 2 if together else steps([4, 6, 8, 10], 2, 5)
    napier = np.full(n + lag, 30.0)  # never varies, so there is nothing to learn from it

    cows_arr = np.full(n, float(cows))
    herd = [{"effective_date": idx[0].date(), "cows_in_milk": cows}]
    if dry_off_day is not None:
        cows_arr[dry_off_day:] = cows - 1
        if log_dry_off:
            herd.append({"effective_date": idx[dry_off_day].date(), "cows_in_milk": cows - 1})

    meal_pc = meal / np.r_[np.full(lag, cows), cows_arr]
    lagged = pd.Series(meal_pc).rolling(lag + 1).mean().to_numpy()[lag:]
    e = np.zeros(n)
    for t in range(n):
        e[t] = (ar * e[t - 1] if t else 0.0) + rng.normal(0, noise)
    litres = (8.0 + trend * np.arange(n) + effect * lagged + e) * cows_arr

    daily = pd.DataFrame({"litres": litres, "complete": True, "milkings": 3}, index=idx)
    feed_kg = pd.DataFrame(
        {"dairy meal": meal[lag:], "banana trunks": banana[lag:], "napier": napier[lag:]}, index=idx
    )
    return daily, feed_kg, cows_series(herd, idx)
