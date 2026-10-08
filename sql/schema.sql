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
