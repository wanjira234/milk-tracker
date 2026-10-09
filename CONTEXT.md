# CONTEXT.md

Anchor file for Claude Code sessions. Read this first, and keep it current when decisions change.

## What this is

A dairy yield and feed tracker for smallholder farmers in Kenya (working name: Milk Tracker; final name not chosen yet). It tracks milk yield, correlates it with feed, suggests feed changes, and helps the farmer budget for the current and upcoming month. Suggestions go back to the farmer by SMS.

First user: the owner's parents' dairy operation. They sell to Fresha (Githunguri Dairy) and receive an SMS confirmation for each milking submission, three times a day (morning, afternoon, evening).

Built for the FNB App of the Year Hackathon (Best African Solution category). Goal: top 2 in round 1. Also the project behind a Z Fellows application.

## The loop we are building

1. Yield comes in (manual entry for the MVP).
2. Feed is logged against yield.
3. A model learns each farm's own yield response to feed.
4. The farmer gets a short SMS with a feed suggestion and budget note.

The point of difference is closing this loop per farm, on a basic phone, using yield data that buyers already collect. Do not drift into generic farm record-keeping.

## Feed reality on the first farm (from the owner)

- Milk price: Fresha pays **KES 50 per litre**. Store it per farmer; do not hard-code it.
- Feeds in use: pineapple waste (Del Monte, bought by the truck load), machicha (brewers' spent grain, bought weekly), napier, maize stalks, hay, banana trunks (heavy use at the moment), and store-bought feeds and protein mixes bought separately and mixed at home. Some feeds are mixed together, some fed standalone. No molasses. Water is from a well, so it is not a variable.
- Consequences for the data model: bulky feeds are not weighed (trunks, wheelbarrows, truck loads) and are bought in lumps, not per feeding. Logging kg per feeding with a cost on every entry does not match how the farm works. Solved with a per-farm feed catalogue (unit, kg per unit, KES per unit): the farmer logs "6 trunks" and the app stores kg and cost computed at log time, so a later price change never rewrites history.
- Herd size changes (calving, drying off) and moves yield more than most feed changes do. Yield per cow in milk is the honest outcome measure; the model should not trust herd litres alone.
- Owner's direction: show milk trends and let a farmer track which feed combinations help yield and which don't, so other farmers can later get suggestions from what worked. Per farm first. Learning across farms needs many farms, consistent feed names, and farmer consent to pool data.

## Advice rules (agreed 2026-10-09)

- Not enough data: the farmer gets a data-nudge SMS (what is missing), never feed advice and never generic tips.
- A single suggestion changes a feed by at most 10%.
- Advice optimises feed margin: milk income (price per litre x litres) minus feed cost.
- Strict evidence bar before any advice: at least 14 complete days, at least 3 different amounts of that feed, and a clear milk-vs-feed slope.

## Stack

- Dashboard: Streamlit (multipage: `app.py` plus `pages/`)
- Database: Postgres on Supabase, **raw SQL via psycopg2, no ORM**. This is deliberate, for hands-on Postgres practice. Do not introduce SQLAlchemy or any ORM.
- SMS out: Africa's Talking
- Scheduled jobs: Modal Labs (weekly retrain, daily SMS dispatch)
- Message generation: Claude API, Haiku, for natural-language SMS text
- Theme: terracotta (primary) on a cream background

## Decisions already made

- **Yield ingestion:** manual entry for the MVP. Near-term upgrade: the farmer uploads a screenshot of the Fresha SMS and Claude vision extracts the figures.
- **Why not read the Fresha SMS directly:** Africa's Talking only receives messages sent to its own shortcode, not messages sent to a personal phone. Do not design around that.
- **Farmer signup:** lightweight, CSV-based.
- **Pitch deck:** deferred until the demo is live.

## Layout

```
app.py                      Streamlit entry point
pages/1_dashboard.py        Yield and feed trends
pages/2_feed_log.py         Log feed against yield
pages/3_budget.py           Current and upcoming month feed budget
pages/4_farm_setup.py       Milk price, feed catalogue (own units), cows in milk
src/ui.py                   Shared Streamlit helpers (farmer selector, error text)
src/db.py                   Postgres connection and queries (psycopg2)
src/trends.py               Pure dashboard calculations (daily tables, summary, feed-yield signals)
src/budget.py               Pure budget maths (month-end projection, budget status, next-month estimate)
src/models.py               Yield-vs-feed model
src/suggestions.py          Turns model output into feed suggestions
src/llm.py                  Claude (Haiku) SMS wording
src/sms.py                  Africa's Talking client
src/ingestion/manual_entry.py   Manual yield entry
src/ingestion/sms_forward.py    Screenshot/forwarded-SMS ingestion (later)
modal_jobs/weekly_retrain.py    Scheduled retrain
modal_jobs/daily_sms_dispatch.py   Scheduled SMS dispatch
sql/schema.sql              Database schema
tests/test_db.py            DB layer tests (need TEST_DATABASE_URL; they truncate tables)
tests/test_manual_entry.py  Validation tests (no database needed)
tests/test_trends.py        Dashboard calculation tests (no database needed)
tests/test_budget.py        Budget maths tests (no database needed)
tests/test_suggestions.py   Tests for the suggestion logic
```

## Working conventions

- **Run and verify in small steps.** One piece at a time, run it, confirm, then move on.
- **Verify edits with copy-and-diff.** A silent `str_replace` failure has happened before. After any edit, confirm it landed (diff or re-read), and never trust a success message alone.
- Secrets live in `.env` (never committed). `.env.example` lists the variable names only.
- DB tests use `TEST_DATABASE_URL`, never `DATABASE_URL`, because they truncate tables. Never point it at Supabase production.
- SMS must stay short. Keep suggestion text within one or two SMS segments.
- Farmers are on basic phones and many are older. Anything farmer-facing is SMS or very simple. The Streamlit dashboard is for the owner, family and demos.

## Current status

- Scaffold exists. Foundation layer done and tested: `.gitignore`, `requirements.txt`, `.env.example`, Streamlit theme, `sql/schema.sql` (idempotent), `src/db.py`, `tests/test_db.py` (7 passing).
- Schema is herd-level: one `farmers` row is one farm; yield is per milking session (morning/afternoon/evening), unique per farmer/date/session.
- Still to build: ingestion, model, suggestions, SMS and LLM wiring, dashboard pages, Modal jobs, farmer signup, deck.
- `src/ingestion/manual_entry.py` done: `record_yield` / `record_feed` validate (session, non-negative, plausible caps, no future dates, feed type normalised to lowercase) then write via `src/db.py`. Validators are pure functions, tested without a DB. 26 tests passing in total.
- `app.py` (home: add farmer with Kenyan phone normalisation, today and 7-day litres) and `pages/2_feed_log.py` (yield and feed entry forms, last 14 days) work. Checked headlessly with Streamlit AppTest against local Postgres, and visually by screenshot. `normalize_phone` lives in `manual_entry.py`.
- `pages/1_dashboard.py` done: 14/30/90-day views, average and best day, feed spend, feed cost per litre, milk-per-day chart, one feed chart per feed (each on its own scale, because forage kg would flatten concentrate kg), and a "does feed move yield?" correlation signal. Calculations live in `src/trends.py` and are tested without Streamlit or a DB.
- Dashboard rule: a day only counts if all 3 milkings are recorded (`MILKINGS_PER_DAY`). Partial days are left out of litres charts and averages and reported in a caption, so a missing entry never looks like a drop in milk.
- The feed-yield correlation is an early signal only: needs at least 7 complete days and variation in the feed amount; a constant ration is skipped. The model in `src/models.py` should take over from this.
- `pages/3_budget.py` done: this month's budget vs spend, month-end projection, status (on track / on pace to overspend with a daily allowance / over budget), next month's estimate and budget, and a recent-months table. Maths in `src/budget.py`; per-month spend from `db.monthly_feed_spend`. 65 tests passing in total.
- Budget rules: projections only count from day 7 of the month (`MIN_DAYS_FOR_PROJECTION`), so one early feed purchase can't swing the pace. Next month's estimate uses this month's pace once reliable, else last month's daily rate. Feed entries logged without a cost make spend an understatement, and the page warns about them.
- Farm setup done (`pages/4_farm_setup.py`, schema additions, `db.py` and `manual_entry.py` functions): per-farmer milk price, per-farm feed catalogue, and a cows-in-milk log that carries each entry forward until the next one (`db.cows_in_milk_on`). The feed log page logs in catalogue units, with plain kg still available for feeds not in the catalogue. 86 tests passing in total.
- Decisions made 2026-10-09: the catalogue approach above; cows in milk is logged whenever it changes (the model works on litres per cow in milk); the first version of advice is single-feed advice plus a "what changed" view comparing the weeks before and after a ration change. A combination model is not attempted: one farm cannot support it, and it needs many farms, consistent feed names and farmer consent to pool data.
- Next up: `src/models.py` (per-feed effect on litres per cow in milk, honouring the advice rules above), the "what changed" view, then suggestions, SMS wording (Claude Haiku), the Modal jobs and farmer signup.
