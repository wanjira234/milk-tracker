"""Pure calculations behind the dashboard. No Streamlit, no database."""
import numpy as np
import pandas as pd

MILKINGS_PER_DAY = 3  # morning, afternoon, evening (what the buyer confirms)
MIN_DAYS_FOR_SIGNAL = 7


def daily_frame(yield_rows, feed_rows, start, end):
    """Build per-day tables for [start, end], one row per calendar day.

    Returns (daily, feed_kg):
      daily   columns: litres, milkings, complete, cost_kes
      feed_kg one column per feed type, kg per day (0 where none)
    Days with fewer than MILKINGS_PER_DAY milkings are marked incomplete.
    """
    idx = pd.date_range(start, end, freq="D")
    daily = pd.DataFrame(index=idx)

    y = pd.DataFrame(yield_rows)
    if y.empty:
        daily["litres"] = np.nan
        daily["milkings"] = 0
    else:
        y["log_date"] = pd.to_datetime(y["log_date"])
        y = y.set_index("log_date")
        daily["litres"] = y["litres"].astype(float)
        daily["milkings"] = y["sessions"]
    daily["milkings"] = daily["milkings"].fillna(0).astype(int)
    daily["complete"] = daily["milkings"] >= MILKINGS_PER_DAY

    f = pd.DataFrame(feed_rows)
    if f.empty:
        daily["cost_kes"] = 0.0
        feed_kg = pd.DataFrame(index=idx)
    else:
        f["log_date"] = pd.to_datetime(f["log_date"])
        f["kg"] = f["kg"].astype(float)
        f["cost_kes"] = f["cost_kes"].astype(float)
        daily["cost_kes"] = f.groupby("log_date")["cost_kes"].sum().reindex(idx).fillna(0.0)
        feed_kg = (
            f.pivot_table(index="log_date", columns="feed_type", values="kg", aggfunc="sum")
            .reindex(idx)
            .fillna(0.0)
        )
    return daily, feed_kg


def summary(daily):
    """Headline numbers. Litres figures use complete days only."""
    done = daily[daily["complete"]]
    partial = int(((daily["milkings"] > 0) & ~daily["complete"]).sum())
    out = {
        "complete_days": int(len(done)),
        "partial_days": partial,
        "avg_litres": float(done["litres"].mean()) if len(done) else None,
        "best_day": None,
        "total_cost": float(daily["cost_kes"].sum()),
        "cost_per_litre": None,
    }
    if len(done):
        best = done["litres"].idxmax()
        out["best_day"] = (best.date(), float(done.loc[best, "litres"]))
        litres = float(done["litres"].sum())
        if litres > 0:
            out["cost_per_litre"] = float(done["cost_kes"].sum()) / litres
    return out


def signals(daily, feed_kg, min_days=MIN_DAYS_FOR_SIGNAL):
    """Correlation between daily litres and daily kg of each feed, on complete days.

    Returns [(feed_type, correlation, n_days)] strongest first. A feed is skipped
    when there are too few days or no variation (a constant ration says nothing).
    This is an early signal, not proof: it does not separate feed from weather,
    cow condition or stage of lactation.
    """
    if feed_kg.empty:
        return []
    done = daily["complete"]
    litres = daily.loc[done, "litres"]
    results = []
    for feed_type in feed_kg.columns:
        kg = feed_kg.loc[done, feed_type]
        if len(litres) < min_days or litres.std() == 0 or kg.std() == 0:
            continue
        results.append((feed_type, float(litres.corr(kg)), int(len(litres))))
    return sorted(results, key=lambda r: abs(r[1]), reverse=True)
