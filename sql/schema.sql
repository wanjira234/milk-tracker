-- Milk Tracker schema. Safe to re-run (idempotent).
-- One "farmer" row = one farm. Yield is recorded at herd level, per milking
-- session, because that is what the buyer (e.g. Fresha) confirms by SMS.

CREATE TABLE IF NOT EXISTS farmers (
    id          SERIAL PRIMARY KEY,
    name        TEXT        NOT NULL,
    phone       TEXT        NOT NULL UNIQUE,   -- E.164, e.g. +2547XXXXXXXX
    farm_name   TEXT,
    herd_size   INTEGER     CHECK (herd_size IS NULL OR herd_size > 0),
    active      BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS yield_logs (
    id          SERIAL PRIMARY KEY,
    farmer_id   INTEGER     NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    log_date    DATE        NOT NULL,
    session     TEXT        NOT NULL CHECK (session IN ('morning', 'afternoon', 'evening')),
    litres      NUMERIC(7,2) NOT NULL CHECK (litres >= 0),
    source      TEXT        NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'screenshot')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (farmer_id, log_date, session)
);

CREATE TABLE IF NOT EXISTS feed_logs (
    id          SERIAL PRIMARY KEY,
    farmer_id   INTEGER     NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    log_date    DATE        NOT NULL,
    feed_type   TEXT        NOT NULL,          -- e.g. dairy meal, napier, hay, silage
    kg          NUMERIC(8,2) NOT NULL CHECK (kg >= 0),
    cost_kes    NUMERIC(10,2) CHECK (cost_kes IS NULL OR cost_kes >= 0),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS monthly_budgets (
    farmer_id   INTEGER     NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    month       DATE        NOT NULL CHECK (month = date_trunc('month', month)::date),
    feed_budget_kes NUMERIC(10,2) NOT NULL CHECK (feed_budget_kes >= 0),
    PRIMARY KEY (farmer_id, month)
);

CREATE TABLE IF NOT EXISTS sms_log (
    id          SERIAL PRIMARY KEY,
    farmer_id   INTEGER     NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    body        TEXT        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'failed')),
    provider_ref TEXT,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_yield_farmer_date ON yield_logs (farmer_id, log_date);
CREATE INDEX IF NOT EXISTS idx_feed_farmer_date  ON feed_logs  (farmer_id, log_date);
CREATE INDEX IF NOT EXISTS idx_sms_farmer_sent   ON sms_log    (farmer_id, sent_at);

-- ---------------------------------------------------------------------------
-- Farm setup: milk price, feed catalogue, cows in milk.
-- ---------------------------------------------------------------------------

-- What the buyer pays per litre (KES). Per farmer, never hard-coded in the app.
ALTER TABLE farmers ADD COLUMN IF NOT EXISTS milk_price_kes NUMERIC(8,2)
    CHECK (milk_price_kes IS NULL OR milk_price_kes > 0);

-- Each farm's own feeds, measured the way the farm measures them (trunk, wheelbarrow,
-- truck load...), with a one-time conversion to kg and a price per unit.
CREATE TABLE IF NOT EXISTS feed_catalogue (
    id           SERIAL PRIMARY KEY,
    farmer_id    INTEGER     NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    name         TEXT        NOT NULL,            -- lowercase, e.g. 'banana trunks'
    unit         TEXT        NOT NULL,            -- e.g. 'trunk', 'wheelbarrow'
    kg_per_unit  NUMERIC(8,2)  NOT NULL CHECK (kg_per_unit > 0),
    kes_per_unit NUMERIC(10,2) NOT NULL CHECK (kes_per_unit >= 0),
    active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (farmer_id, name)
);

-- A feed entry may now be logged in units; kg and cost_kes stay the canonical values
-- (computed and stored at log time, so a later price change doesn't rewrite history).
ALTER TABLE feed_logs ADD COLUMN IF NOT EXISTS units NUMERIC(8,2)
    CHECK (units IS NULL OR units > 0);
ALTER TABLE feed_logs ADD COLUMN IF NOT EXISTS catalogue_id INTEGER
    REFERENCES feed_catalogue(id) ON DELETE SET NULL;

-- Cows in milk from effective_date until the next entry. Yield per cow is the honest
-- outcome measure, because calving and drying off move litres more than feed does.
CREATE TABLE IF NOT EXISTS herd_log (
    farmer_id      INTEGER NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    effective_date DATE    NOT NULL,
    cows_in_milk   INTEGER NOT NULL CHECK (cows_in_milk >= 0),
    PRIMARY KEY (farmer_id, effective_date)
);
