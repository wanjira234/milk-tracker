# Milk Tracker

A dairy yield and feed tracker for smallholder farmers in Kenya.

Smallholder farmers already record milk yield: buyers like Fresha capture every milking and confirm it by SMS. That data rarely turns into a feed decision, even though feed is the biggest cost on a dairy farm. Milk Tracker closes the loop: it learns how each farm's yield responds to feed, then sends back a short feed suggestion and a monthly budget note by SMS, on a basic phone.

> Status: early build. Built first around one real dairy farm.

## How it works

1. Yield is recorded (manual entry for now; screenshot-of-SMS ingestion next).
2. Feed is logged against yield.
3. A model learns the farm's own yield-vs-feed response, retrained weekly.
4. A scheduled job sends the farmer a plain-language SMS with a feed suggestion.

## Stack

- Streamlit for the dashboard
- Postgres (Supabase), raw SQL via psycopg2
- Africa's Talking for SMS
- Modal for scheduled retraining and SMS dispatch
- Claude API for SMS wording

## Getting started

```bash
git clone https://github.com/wanjira234/milk-tracker
cd milk-tracker
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in your values
psql "$DATABASE_URL" -f sql/schema.sql
streamlit run app.py
```

## Project layout

See [CONTEXT.md](CONTEXT.md) for the full layout, decisions and working conventions.

## Tests

```bash
pytest                                   # logic tests
TEST_DATABASE_URL=postgresql://... pytest   # also runs DB tests (they truncate tables: use a throwaway database)
```
