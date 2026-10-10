"""Per-farm yield-vs-feed model. Pure functions: no Streamlit, no database.

For each feed, estimate how litres per cow in milk move with kg of that feed per cow,
controlling for a time trend, and say how much evidence there is. The rules (agreed with
the owner, see CONTEXT.md) are deliberately strict: with about one data point a day, the
honest answer is usually "not enough evidence yet".
"""
import numpy as np
import pandas as pd
from scipy import stats

WINDOW_DAYS = 90          # lactation stage and season drift, so old days stop being relevant
LAG_DAYS = 2              # milk responds over 2-3 days: use the feed averaged over today and the 2 days before
MIN_COMPLETE_DAYS = 14    # days with all milkings, cows in milk known, and feed logged
MIN_DISTINCT_LEVELS = 3   # the amount of the feed must have varied: a constant ration says nothing
LEVEL_GAP = 0.10          # amounts within 10% of each other count as the same level
CONFIDENCE = 0.95
COLLINEAR_CORR = 0.8      # feeds that move together cannot have their effects separated


def cows_series(herd_rows, index):
    """Cows in milk on every day of `index`, carried forward from each entry.

    Days before the first entry are NaN (unknown). `herd_rows` are herd_log rows.
    """
    if not herd_rows:
        return pd.Series(np.nan, index=index, dtype=float)
    s = pd.Series(
        {pd.Timestamp(r["effective_date"]): float(r["cows_in_milk"]) for r in herd_rows}
    ).sort_index()
    return s.reindex(s.index.union(index)).ffill().reindex(index)


def distinct_levels(values, rel_gap=LEVEL_GAP):
    """How many clearly different amounts appear in `values` (zero counts as an amount)."""
    v = np.sort(np.asarray(values, dtype=float))
    if len(v) == 0:
        return 0
    positive = v[v > 0]
    scale = float(np.median(positive)) if len(positive) else 0.0
    gap = max(rel_gap * scale, 1e-9)
    levels, last = 1, v[0]
    for x in v[1:]:
        if x - last > gap:
            levels += 1
            last = x
    return levels


def model_frame(daily, feed_kg, cows, lag_days=LAG_DAYS):
    """Per-cow daily tables. Returns (litres_pc, kg_pc, lagged).

    litres_pc  litres per cow in milk, on days with all milkings and a known herd, else NaN
    kg_pc      kg of each feed per cow, NaN on days when no feed at all was logged
               (that is unknown, not "fed nothing") or the herd is unknown
    lagged     kg_pc averaged over today and the previous `lag_days` days
    """
    cows = cows.reindex(daily.index)
    known = cows.notna() & (cows > 0)
    litres_pc = (daily["litres"] / cows).where(daily["complete"] & known)
    logged = feed_kg.sum(axis=1) > 0 if not feed_kg.empty else pd.Series(False, index=daily.index)
    kg_pc = feed_kg.div(cows, axis=0).where(logged & known)
    lagged = kg_pc.rolling(lag_days + 1, min_periods=lag_days + 1).mean()
    return litres_pc, kg_pc, lagged


def _fit(y, X):
    """OLS with standard errors corrected for autocorrelated residuals. Returns (beta, se, df).

    Milk on consecutive days is similar, so plain OLS standard errors come out too small and
    find feed effects that are not there. Simulation on farms with no real effect: plain OLS
    flagged about 25% of feeds at "95% confidence"; this correction brings it near the nominal
    5%. The residual lag-1 autocorrelation inflates the standard error and shrinks the
    effective sample size accordingly.
    """
    n, k = X.shape
    xtx_inv = np.linalg.inv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    resid = y - X @ beta
    rss = float(resid @ resid)
    sigma2 = rss / (n - k)
    se = np.sqrt(np.diag(xtx_inv) * sigma2)
    rho = float(resid[1:] @ resid[:-1]) / rss if rss > 0 else 0.0
    rho = min(max(rho, 0.0), 0.9)
    se = se * np.sqrt((1 + rho) / (1 - rho))
    df = max(1, int(round(n * (1 - rho) / (1 + rho))) - k)
    return beta, se, df


def feed_effects(
    daily, feed_kg, cows, cost_per_kg=None, price=None,
    window_days=WINDOW_DAYS, confidence=CONFIDENCE,
):
    """Estimate each feed's effect on litres per cow in milk, with the evidence behind it.

    Returns one dict per feed that was fed in the window. `status` is one of:
      too_few_days     fewer than MIN_COMPLETE_DAYS usable days
      too_few_amounts  the amount hardly varied, so there is nothing to learn from
      moves_with       always changes together with another feed (`moves_with` names it)
      unclear          enough data, but the effect could be zero
      clear            enough data and the effect is clearly not zero
    For unclear/clear, `slope` is extra litres per cow per day for 1 extra kg per cow per day,
    with `ci_low`/`ci_high`. Testing several feeds at once produces false alarms by chance, so
    the (1 - confidence) error budget is split across the feeds actually tested; `confidence_used`
    is the per-feed level. `margin_per_kg` (KES per extra kg per cow per day) needs `price`
    (KES per litre) and `cost_per_kg[feed]`.
    """
    if feed_kg.empty:
        return []
    daily, feed_kg = daily.iloc[-window_days:], feed_kg.iloc[-window_days:]
    litres_pc, kg_pc, lagged = model_frame(daily, feed_kg, cows)
    day0 = daily.index[0]
    results, fitted = [], []
    for feed in feed_kg.columns:
        raw = kg_pc[feed]
        if not (raw.fillna(0) > 0).any():
            continue
        usable = litres_pc.notna() & lagged[feed].notna()
        n = int(usable.sum())
        out = {
            "feed": feed, "status": None, "n_days": n,
            "mean_kg_pc": float(raw[raw > 0].mean()),
            "min_kg_pc": float(raw[usable].min()) if n else None,
            "max_kg_pc": float(raw[usable].max()) if n else None,
            "slope": None, "ci_low": None, "ci_high": None, "margin_per_kg": None, "moves_with": None,
        }
        results.append(out)
        if n < MIN_COMPLETE_DAYS:
            out["status"] = "too_few_days"
            continue
        if distinct_levels(raw[usable]) < MIN_DISTINCT_LEVELS:
            out["status"] = "too_few_amounts"
            continue
        partner = None
        for other in feed_kg.columns:
            if other == feed:
                continue
            o = kg_pc[other][usable]
            if o.std() > 0 and abs(raw[usable].corr(o)) > COLLINEAR_CORR:
                partner = other
                break
        if partner:
            out["status"], out["moves_with"] = "moves_with", partner
            continue

        t = (daily.index[usable] - day0).days.to_numpy(dtype=float)
        x = lagged[feed][usable].to_numpy(dtype=float)
        y = litres_pc[usable].to_numpy(dtype=float)
        try:
            beta, se, df = _fit(y, np.column_stack([np.ones(n), t, x]))
        except np.linalg.LinAlgError:
            out["status"] = "unclear"
            continue
        fitted.append((out, float(beta[2]), float(se[2]), df))

    # Split the error budget across the feeds tested (Bonferroni), then judge each one.
    used = 1 - (1 - confidence) / max(len(fitted), 1)
    for out, slope, se, df in fitted:
        crit = stats.t.ppf(1 - (1 - used) / 2, df)
        out["slope"], out["confidence_used"] = slope, used
        out["ci_low"], out["ci_high"] = slope - crit * se, slope + crit * se
        out["status"] = "clear" if out["ci_low"] > 0 or out["ci_high"] < 0 else "unclear"
        if price is not None and cost_per_kg and out["feed"] in cost_per_kg:
            out["margin_per_kg"] = slope * price - cost_per_kg[out["feed"]]
    return results
