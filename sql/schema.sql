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

-- ---------------------------------------------------------------------------
-- Daily SMS job: what kind of message each one was, and the language a farmer reads.
-- ---------------------------------------------------------------------------
ALTER TABLE sms_log ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'other'
    CHECK (kind IN ('advice', 'nudge', 'other'));
ALTER TABLE farmers ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'en'
    CHECK (language IN ('en', 'sw'));

-- Weekly snapshot of what the model believed, so "what changed" can be shown later.
CREATE TABLE IF NOT EXISTS model_snapshots (
    id            SERIAL PRIMARY KEY,
    farmer_id     INTEGER NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    taken_on      DATE    NOT NULL,
    usable_days   INTEGER NOT NULL,
    decision_kind TEXT    NOT NULL,
    effects       JSONB   NOT NULL,
    recent_kg     JSONB   NOT NULL,
    UNIQUE (farmer_id, taken_on)
);

-- ---------------------------------------------------------------------------
-- Water: total litres the herd drank on a day (one row per farm per day).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS water_logs (
    farmer_id  INTEGER NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    log_date   DATE    NOT NULL,
    litres     NUMERIC(8,1) NOT NULL CHECK (litres > 0),
    PRIMARY KEY (farmer_id, log_date)
);

-- ---------------------------------------------------------------------------
-- Per-cow records: the cows, breeding events, the semen the farm can choose from,
-- and deworming. Every link carries the farmer id too, so a record can never point
-- at another farm's cow or semen.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cows (
    id         SERIAL PRIMARY KEY,
    farmer_id  INTEGER NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    tag        TEXT    NOT NULL,              -- the name or ear-tag number the farm uses
    active     BOOLEAN NOT NULL DEFAULT TRUE, -- false = sold or died; history is kept
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (farmer_id, tag),
    UNIQUE (id, farmer_id)
);

CREATE TABLE IF NOT EXISTS semen_options (
    id         SERIAL PRIMARY KEY,
    farmer_id  INTEGER NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    name       TEXT    NOT NULL,              -- bull name or breed, e.g. "Friesian - Kamau"
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (farmer_id, name),
    UNIQUE (id, farmer_id)
);

CREATE TABLE IF NOT EXISTS breeding_events (
    id          SERIAL PRIMARY KEY,
    farmer_id   INTEGER NOT NULL,
    cow_id      INTEGER NOT NULL,
    event_date  DATE    NOT NULL,
    kind        TEXT    NOT NULL CHECK (kind IN ('heat', 'served', 'confirmed_pregnant', 'not_pregnant', 'calved', 'aborted')),
    semen_id    INTEGER,                      -- only for 'served'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (cow_id, farmer_id)   REFERENCES cows (id, farmer_id)           ON DELETE CASCADE,
    FOREIGN KEY (semen_id, farmer_id) REFERENCES semen_options (id, farmer_id),
    CHECK (semen_id IS NULL OR kind = 'served')
);
CREATE INDEX IF NOT EXISTS idx_breeding_cow_date ON breeding_events (cow_id, event_date);

CREATE TABLE IF NOT EXISTS dewormings (
    id         SERIAL PRIMARY KEY,
    farmer_id  INTEGER NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    cow_id     INTEGER,                       -- NULL = the whole herd was dewormed
    given_on   DATE    NOT NULL,
    product    TEXT,
    FOREIGN KEY (cow_id, farmer_id) REFERENCES cows (id, farmer_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_deworm_farmer_date ON dewormings (farmer_id, given_on);

-- ---------------------------------------------------------------------------
-- Life stages and family: calf / heifer / cow, mother links, birth and weaning dates,
-- and a 'dried_off' breeding event for the dry period.
-- ---------------------------------------------------------------------------
ALTER TABLE cows ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'cow'
    CHECK (kind IN ('calf', 'heifer', 'cow'));
ALTER TABLE cows ADD COLUMN IF NOT EXISTS sex TEXT NOT NULL DEFAULT 'female'
    CHECK (sex IN ('female', 'male'));
ALTER TABLE cows ADD COLUMN IF NOT EXISTS dam_id INTEGER;   -- the mother, another cow on the same farm
ALTER TABLE cows ADD COLUMN IF NOT EXISTS born_on DATE;
ALTER TABLE cows ADD COLUMN IF NOT EXISTS weaned_on DATE;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cows_dam_same_farm') THEN
        ALTER TABLE cows ADD CONSTRAINT cows_dam_same_farm
            FOREIGN KEY (dam_id, farmer_id) REFERENCES cows (id, farmer_id);
    END IF;
END $$;

ALTER TABLE breeding_events DROP CONSTRAINT IF EXISTS breeding_events_kind_check;
ALTER TABLE breeding_events ADD CONSTRAINT breeding_events_kind_check
    CHECK (kind IN ('heat', 'served', 'confirmed_pregnant', 'not_pregnant', 'calved', 'aborted', 'dried_off'));

-- ---------------------------------------------------------------------------
-- Accounts, roles and routes.
--   role 'farmer' is linked to one farm; 'vet' and 'admin' are not.
--   A route (for example 4A) has one allocated vet; a farm belongs to one route.
--   Login is by SMS code (phone) or by email + password. Passwords are stored only as
--   scrypt hashes; SMS codes only as keyed hashes, and they expire.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id                   SERIAL PRIMARY KEY,
    role                 TEXT    NOT NULL CHECK (role IN ('admin', 'vet', 'farmer')),
    name                 TEXT    NOT NULL,
    phone                TEXT    UNIQUE,
    email                TEXT    UNIQUE,
    password_hash        TEXT,
    farmer_id            INTEGER UNIQUE REFERENCES farmers(id) ON DELETE CASCADE,
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    active               BOOLEAN NOT NULL DEFAULT TRUE,
    failed_logins        INTEGER NOT NULL DEFAULT 0,   -- consecutive wrong passwords
    locked_until         TIMESTAMPTZ,                  -- set after too many
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (phone IS NOT NULL OR email IS NOT NULL),
    CHECK (role <> 'farmer' OR farmer_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS routes (
    id          SERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,          -- e.g. 4A
    name        TEXT,
    vet_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
);

ALTER TABLE farmers ADD COLUMN IF NOT EXISTS route_id INTEGER REFERENCES routes(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS login_codes (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    salt       TEXT    NOT NULL,
    code_hash  TEXT    NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    used       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_login_codes_user ON login_codes (user_id, created_at);

-- Self-signup waits for an admin's approval (a pending login cannot log in and has no farm yet).
ALTER TABLE users ADD COLUMN IF NOT EXISTS pending   BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS farm_name TEXT;

DO $$
DECLARE c text;
BEGIN
    FOR c IN SELECT conname FROM pg_constraint
             WHERE conrelid = 'users'::regclass AND contype = 'c'
               AND pg_get_constraintdef(oid) LIKE '%farmer_id IS NOT NULL%'
               AND conname <> 'users_farmer_has_farm'
    LOOP
        EXECUTE format('ALTER TABLE users DROP CONSTRAINT %I', c);
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_farmer_has_farm') THEN
        ALTER TABLE users ADD CONSTRAINT users_farmer_has_farm
            CHECK (role <> 'farmer' OR farmer_id IS NOT NULL OR pending);
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Vets: the semen they offer (with prices), and service requests from farmers.
-- Which vet answers a request is worked out from the farm's route at the time, so changing a
-- route's vet moves its open requests with it. The semen price is copied onto the request so a
-- later price change can't alter what the farmer agreed to. Fresha deducts the semen cost from
-- the monthly milk payment; the app moves no money, it only records the cost.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vet_semen (
    id          SERIAL PRIMARY KEY,
    vet_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,                       -- e.g. "Friesian - Kamau"
    price_kes   NUMERIC(10,2) NOT NULL CHECK (price_kes >= 0),
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (vet_user_id, name)
);

CREATE TABLE IF NOT EXISTS service_requests (
    id              SERIAL PRIMARY KEY,
    farmer_id       INTEGER NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    cow_id          INTEGER,
    kind            TEXT    NOT NULL CHECK (kind IN ('ai', 'sick', 'vaccination', 'other')),
    notes           TEXT,
    preferred_date  DATE    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'scheduled', 'done', 'cancelled')),
    scheduled_for   DATE,
    semen_id        INTEGER REFERENCES vet_semen(id),
    semen_price_kes NUMERIC(10,2) CHECK (semen_price_kes IS NULL OR semen_price_kes >= 0),
    done_on         DATE,
    done_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    vet_notes       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (cow_id, farmer_id) REFERENCES cows (id, farmer_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_requests_farm   ON service_requests (farmer_id, status);
CREATE INDEX IF NOT EXISTS idx_requests_status ON service_requests (status, scheduled_for);

-- ---------------------------------------------------------------------------
-- Alerts (outbreaks and notices) and the SMS outbox. An alert goes to one route's farmers or to
-- every route (route_id NULL). Sending it by SMS is a separate, one-time action, recorded here so
-- it can never be sent twice by accident.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id                 SERIAL PRIMARY KEY,
    kind               TEXT NOT NULL CHECK (kind IN ('outbreak', 'notice')),
    title              TEXT NOT NULL,
    body               TEXT NOT NULL,
    route_id           INTEGER REFERENCES routes(id) ON DELETE CASCADE,   -- NULL = all routes
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_on         DATE,
    sms_sent_at        TIMESTAMPTZ,
    sms_ok             INTEGER NOT NULL DEFAULT 0,
    sms_failed         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alerts_route ON alerts (route_id, created_at);

ALTER TABLE sms_log DROP CONSTRAINT IF EXISTS sms_log_kind_check;
ALTER TABLE sms_log ADD CONSTRAINT sms_log_kind_check CHECK (kind IN ('advice', 'nudge', 'alert', 'other'));

-- ---------------------------------------------------------------------------
-- Vaccination days: posted for one route or all routes; a farmer books a number of animals, and the
-- booking becomes a vaccination visit (a service request) on the route vet's day sheet. The unique
-- index below means a farm cannot book the same day twice (a cancelled booking can be rebooked).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vaccination_days (
    id                 SERIAL PRIMARY KEY,
    vaccine            TEXT NOT NULL,
    day                DATE NOT NULL,
    place              TEXT,
    notes              TEXT,
    route_id           INTEGER REFERENCES routes(id) ON DELETE CASCADE,   -- NULL = all routes
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    cancelled          BOOLEAN NOT NULL DEFAULT FALSE
);
ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS vaccination_day_id INTEGER REFERENCES vaccination_days(id) ON DELETE SET NULL;
ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS animals INTEGER CHECK (animals IS NULL OR animals > 0);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_booking_per_day ON service_requests (vaccination_day_id, farmer_id)
    WHERE vaccination_day_id IS NOT NULL AND status IN ('open', 'scheduled', 'done');

-- The shared owner password is guessed against one counter for everyone, not one per browser session.
CREATE TABLE IF NOT EXISTS owner_lockout (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    failures     INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ
);
INSERT INTO owner_lockout (id) VALUES (1) ON CONFLICT DO NOTHING;

-- Route admins: an admin login limited to some routes (a head admin has route_admin FALSE and sees all).
ALTER TABLE users ADD COLUMN IF NOT EXISTS route_admin BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS admin_routes (
    user_id  INTEGER NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
    route_id INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, route_id)
);
