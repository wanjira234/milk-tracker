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
src/db.py                   Postgres connection and queries (psycopg2)
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
- Next up: `src/ingestion/manual_entry.py`, then the feed log and dashboard pages.
