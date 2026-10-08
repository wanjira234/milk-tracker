"""Yield and feed trends for one farm."""
from datetime import date, timedelta
from itertools import cycle

import streamlit as st

from src import db
from src.trends import MILKINGS_PER_DAY, daily_frame, signals, summary
from src.ui import farmer_selector

st.set_page_config(page_title="Dashboard", page_icon="🥛", layout="centered")
st.title("Dashboard")

farmer_id = farmer_selector()

days = st.radio("Period", [14, 30, 90], index=1, horizontal=True, format_func=lambda d: f"Last {d} days")
today = date.today()
start = today - timedelta(days=days - 1)

daily, feed_kg = daily_frame(
    db.daily_yield(farmer_id, start, today),
    db.daily_feed(farmer_id, start, today),
    start,
    today,
)
stats = summary(daily)

if stats["complete_days"] == 0 and stats["total_cost"] == 0:
    st.info("Nothing recorded in this period yet. Add milkings and feed on the feed log page.")
    st.stop()

c1, c2 = st.columns(2)
c1.metric("Average per day", f"{stats['avg_litres']:.1f} L" if stats["avg_litres"] is not None else "n/a")
best = stats["best_day"]
c2.metric("Best day", f"{best[1]:.1f} L" if best else "n/a", help=str(best[0]) if best else None)
c3, c4 = st.columns(2)
c3.metric("Feed spend", f"KES {stats['total_cost']:,.0f}")
cpl = stats["cost_per_litre"]
c4.metric("Feed cost per litre", f"KES {cpl:,.1f}" if cpl is not None else "n/a")

if stats["partial_days"]:
    st.caption(
        f"{stats['partial_days']} day(s) have fewer than {MILKINGS_PER_DAY} milkings recorded and are left out "
        "of the litres chart and averages, so a missing entry doesn't look like a drop in milk."
    )

st.subheader("Milk per day")
litres = daily["litres"].where(daily["complete"])
if litres.notna().any():
    st.line_chart(litres.rename("Litres"), color="#C65D3B")
else:
    st.caption("No complete days yet.")

st.subheader("Feed per day (kg)")
if not feed_kg.empty:
    # One chart per feed, each on its own scale: forage (30 kg) would flatten concentrate (4 kg) if stacked.
    palette = cycle(["#C65D3B", "#8A9A5B", "#D9A441", "#6B4F3A", "#A3B18A"])
    for feed_type, colour in zip(feed_kg.columns, palette):
        st.caption(feed_type)
        st.bar_chart(feed_kg[feed_type], color=colour, height=150)
else:
    st.caption("No feed recorded in this period.")

st.subheader("Does feed move yield?")
found = signals(daily, feed_kg)
if found:
    for feed_type, corr, n in found:
        direction = "rises with" if corr > 0 else "falls as you feed more of"
        st.write(f"**{feed_type}**: milk {direction} this feed (correlation {corr:+.2f}, {n} complete days).")
    st.caption(
        "An early signal only. It can't separate feed from weather, cow condition or stage of lactation, "
        "so treat it as a question to test, not an answer."
    )
else:
    st.caption(
        "Not enough variation yet. This needs at least 7 complete days where the amount of a feed changed. "
        "A ration that never changes can't show its effect."
    )
