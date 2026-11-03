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
-- Optional two-factor login (authenticator app). The app works without these until they are added.
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret    TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled   BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_last_step BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_failed    INTEGER NOT NULL DEFAULT 0;

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

-- Messages from the public Contact us form; the head admin reads and clears them.
CREATE TABLE IF NOT EXISTS contact_messages (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    contact    TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    handled    BOOLEAN NOT NULL DEFAULT FALSE
);

-- ---------------------------------------------------------------------------
-- Phase 1: the farmer chooses their vet, and a money ledger (charges and payments).
--   The app stays neutral between providers: a farm on a buyer's route keeps the route vet as the
--   default, and may also add independent vets and send any request to one of them.
--   A charge is what a farm owes for something (a vet visit, drugs, semen, agrovet goods), with
--   its terms: paid on the spot, on credit until a due date, or deducted from the milk payment by
--   the buyer. The app moves no money; it records charges and the payments against them.
--   Money records are never deleted by the app: a wrong charge is voided, with who and why.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS farm_vets (
    farmer_id   INTEGER     NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    vet_user_id INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (farmer_id, vet_user_id)
);

-- NULL = the farm's route vet (as before); otherwise the vet the farmer chose for this request.
ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS chosen_vet_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_requests_chosen_vet ON service_requests (chosen_vet_id, status);

CREATE TABLE IF NOT EXISTS charges (
    id                 SERIAL PRIMARY KEY,
    farmer_id          INTEGER       NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    provider_user_id   INTEGER       REFERENCES users(id) ON DELETE SET NULL,  -- NULL = a supplier with no login
    provider_name      TEXT          NOT NULL CHECK (length(provider_name) BETWEEN 1 AND 80),  -- copied, so it reads right later
    category           TEXT          NOT NULL CHECK (category IN ('vet_visit', 'drugs', 'semen', 'agrovet', 'feed', 'other')),
    description        TEXT          CHECK (description IS NULL OR length(description) <= 200),
    amount_kes         NUMERIC(10,2) NOT NULL CHECK (amount_kes > 0 AND amount_kes <= 1000000),
    charged_on         DATE          NOT NULL,
    terms              TEXT          NOT NULL CHECK (terms IN ('paid', 'credit', 'milk_deduction')),
    due_on             DATE,
    request_id         INTEGER,      -- the vet visit this charge is for, if any (same farm: see below)
    created_by_user_id INTEGER       REFERENCES users(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    voided_at          TIMESTAMPTZ,
    voided_by_user_id  INTEGER       REFERENCES users(id) ON DELETE SET NULL,
    void_reason        TEXT          CHECK (void_reason IS NULL OR length(void_reason) <= 200),
    CHECK (terms <> 'credit' OR due_on IS NOT NULL),
    CHECK (due_on IS NULL OR due_on >= charged_on),
    CHECK ((voided_at IS NULL) = (void_reason IS NULL)),
    CHECK (voided_by_user_id IS NULL OR voided_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_charges_farm     ON charges (farmer_id, charged_on);
CREATE INDEX IF NOT EXISTS idx_charges_provider ON charges (provider_user_id, terms);
CREATE INDEX IF NOT EXISTS idx_charges_request  ON charges (request_id);
-- A charge's visit must be on the same farm, and a visit with money recorded against it can't be deleted.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'service_requests_id_farmer_key') THEN
        ALTER TABLE service_requests ADD CONSTRAINT service_requests_id_farmer_key UNIQUE (id, farmer_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'charges_request_same_farm') THEN
        ALTER TABLE charges ADD CONSTRAINT charges_request_same_farm
            FOREIGN KEY (request_id, farmer_id) REFERENCES service_requests (id, farmer_id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS charge_payments (
    id                  SERIAL PRIMARY KEY,
    charge_id           INTEGER       NOT NULL REFERENCES charges(id) ON DELETE CASCADE,
    amount_kes          NUMERIC(10,2) NOT NULL CHECK (amount_kes > 0),
    paid_on             DATE          NOT NULL,
    method              TEXT          NOT NULL CHECK (method IN ('mpesa', 'cash', 'bank', 'other')),
    reference           TEXT          CHECK (reference IS NULL OR length(reference) <= 40),  -- e.g. the M-Pesa code
    recorded_by_user_id INTEGER       REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_payments_charge ON charge_payments (charge_id);

-- ---------------------------------------------------------------------------
-- Phase 2: feed bought, feed left, and when it runs out.
--   A purchase is recorded in the farm's own unit (a truck load, a bag) and its kg is worked out
--   from the catalogue at the time, like a feed entry. A purchase with a price also becomes a
--   charge in the money ledger (category 'feed'), so it shows on the Money page.
--   A count says how much of a feed is left on a day ("finished" = 0): stock is the last count,
--   plus what was bought after it, minus what was fed after it.
-- ---------------------------------------------------------------------------
ALTER TABLE feed_catalogue ADD COLUMN IF NOT EXISTS lead_days INTEGER NOT NULL DEFAULT 3
    CHECK (lead_days BETWEEN 0 AND 60);  -- warn this many days before it runs out

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'feed_catalogue_id_farmer_key') THEN
        ALTER TABLE feed_catalogue ADD CONSTRAINT feed_catalogue_id_farmer_key UNIQUE (id, farmer_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'charges_id_farmer_key') THEN
        ALTER TABLE charges ADD CONSTRAINT charges_id_farmer_key UNIQUE (id, farmer_id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS feed_purchases (
    id                 SERIAL PRIMARY KEY,
    farmer_id          INTEGER       NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    catalogue_id       INTEGER       NOT NULL,
    purchased_on       DATE          NOT NULL,
    units              NUMERIC(8,2)  NOT NULL CHECK (units > 0 AND units <= 10000),
    kg                 NUMERIC(10,2) NOT NULL CHECK (kg > 0),
    cost_kes           NUMERIC(10,2) CHECK (cost_kes IS NULL OR cost_kes >= 0),
    charge_id          INTEGER,
    created_by_user_id INTEGER       REFERENCES users(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    FOREIGN KEY (catalogue_id, farmer_id) REFERENCES feed_catalogue (id, farmer_id) ON DELETE CASCADE,
    FOREIGN KEY (charge_id, farmer_id) REFERENCES charges (id, farmer_id)
);
CREATE INDEX IF NOT EXISTS idx_purchases_item ON feed_purchases (farmer_id, catalogue_id, purchased_on);

CREATE TABLE IF NOT EXISTS feed_stock_counts (
    id           SERIAL PRIMARY KEY,
    farmer_id    INTEGER       NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    catalogue_id INTEGER       NOT NULL,
    counted_on   DATE          NOT NULL,
    kg           NUMERIC(10,2) NOT NULL CHECK (kg >= 0),   -- 0 = finished
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    FOREIGN KEY (catalogue_id, farmer_id) REFERENCES feed_catalogue (id, farmer_id) ON DELETE CASCADE,
    UNIQUE (catalogue_id, counted_on)                      -- one count a day per feed; a second replaces it
);

-- ---------------------------------------------------------------------------
-- Phase 3: agrovets and pre-orders.
--   An agrovet is its own login (role 'agrovet'), approved by an admin like a vet. It keeps a priced
--   product list. A farmer adds the agrovets they use (by phone) and pre-orders from them; the agrovet
--   confirms (prices are copied onto the order then, so a later price change can't alter it), and
--   when the goods are collected or delivered, bills the order into the money ledger. A line the
--   farmer tied to one of their feeds also updates Feed stock. Names are copied onto orders, so the
--   farmer's history reads right even if the agrovet's login or a product goes.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_role_check'
               AND pg_get_constraintdef(oid) NOT LIKE '%agrovet%') THEN
        ALTER TABLE users DROP CONSTRAINT users_role_check;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_role_check') THEN
        ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('admin', 'vet', 'farmer', 'agrovet'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS agrovet_products (
    id              SERIAL PRIMARY KEY,
    agrovet_user_id INTEGER       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT          NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    unit            TEXT          NOT NULL CHECK (length(unit) BETWEEN 1 AND 30),   -- e.g. '70 kg bag'
    price_kes       NUMERIC(10,2) NOT NULL CHECK (price_kes > 0 AND price_kes <= 1000000),
    active          BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE (agrovet_user_id, name)
);

CREATE TABLE IF NOT EXISTS farm_agrovets (
    farmer_id       INTEGER     NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    agrovet_user_id INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (farmer_id, agrovet_user_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id              SERIAL PRIMARY KEY,
    farmer_id       INTEGER     NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
    agrovet_user_id INTEGER     REFERENCES users(id) ON DELETE SET NULL,
    agrovet_name    TEXT        NOT NULL CHECK (length(agrovet_name) BETWEEN 1 AND 80),
    status          TEXT        NOT NULL DEFAULT 'requested'
                    CHECK (status IN ('requested', 'confirmed', 'collected', 'cancelled', 'declined')),
    fulfilment      TEXT        NOT NULL CHECK (fulfilment IN ('pickup', 'delivery')),
    wanted_on       DATE        NOT NULL,
    ready_on        DATE,
    notes           TEXT        CHECK (notes IS NULL OR length(notes) <= 300),
    agrovet_note    TEXT        CHECK (agrovet_note IS NULL OR length(agrovet_note) <= 300),
    collected_on    DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status <> 'confirmed' OR ready_on IS NOT NULL),
    CHECK (status <> 'collected' OR collected_on IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_orders_agrovet ON orders (agrovet_user_id, status, ready_on);
CREATE INDEX IF NOT EXISTS idx_orders_farm    ON orders (farmer_id, created_at);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'orders_id_farmer_key') THEN
        ALTER TABLE orders ADD CONSTRAINT orders_id_farmer_key UNIQUE (id, farmer_id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS order_lines (
    id             SERIAL PRIMARY KEY,
    order_id       INTEGER       NOT NULL,
    farmer_id      INTEGER       NOT NULL,
    product_id     INTEGER       REFERENCES agrovet_products(id) ON DELETE SET NULL,
    product_name   TEXT          NOT NULL CHECK (length(product_name) BETWEEN 1 AND 80),
    unit           TEXT          NOT NULL CHECK (length(unit) BETWEEN 1 AND 30),
    qty            NUMERIC(8,2)  NOT NULL CHECK (qty > 0 AND qty <= 1000),
    unit_price_kes NUMERIC(10,2) CHECK (unit_price_kes IS NULL OR unit_price_kes > 0),  -- set when confirmed
    catalogue_id   INTEGER,      -- the farm's own feed this line restocks, if any
    charge_id      INTEGER,      -- the bill for this line, once collected
    FOREIGN KEY (order_id, farmer_id) REFERENCES orders (id, farmer_id) ON DELETE CASCADE,
    -- deferred: checked at commit, so deleting a whole farm (which cascades through orders, feeds and
    -- charges in no fixed order) succeeds, while deleting a feed or charge an order still uses does not
    FOREIGN KEY (catalogue_id, farmer_id) REFERENCES feed_catalogue (id, farmer_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (charge_id, farmer_id) REFERENCES charges (id, farmer_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX IF NOT EXISTS idx_order_lines_order ON order_lines (order_id);

-- ---------------------------------------------------------------------------
-- Phase 4: smoother journeys.
--   Agrovets list their town and M-Pesa till (or paybill), so farmers pick from a list of shops
--   (nearest town first) instead of typing a phone number, and know where to pay.
--   An order says how the farmer will pay: M-Pesa to the shop, cash at collection, or deducted
--   from the milk payment (the buyer's own store only). For M-Pesa the farmer reports the code and
--   the agrovet confirms it arrived, so both sides see whether it is paid.
-- ---------------------------------------------------------------------------
ALTER TABLE users ADD COLUMN IF NOT EXISTS town TEXT CHECK (town IS NULL OR length(town) <= 60);
ALTER TABLE users ADD COLUMN IF NOT EXISTS pay_kind TEXT CHECK (pay_kind IS NULL OR pay_kind IN ('till', 'paybill'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS pay_number TEXT CHECK (pay_number IS NULL OR pay_number ~ '^[0-9]{5,10}$');
ALTER TABLE users ADD COLUMN IF NOT EXISTS pay_account TEXT CHECK (pay_account IS NULL OR length(pay_account) <= 30);
ALTER TABLE farmers ADD COLUMN IF NOT EXISTS town TEXT CHECK (town IS NULL OR length(town) <= 60);

ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method TEXT NOT NULL DEFAULT 'cash'
    CHECK (payment_method IN ('mpesa', 'cash', 'milk_deduction'));
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_status TEXT NOT NULL DEFAULT 'unpaid'
    CHECK (payment_status IN ('unpaid', 'reported', 'received'));
ALTER TABLE orders ADD COLUMN IF NOT EXISTS mpesa_code TEXT CHECK (mpesa_code IS NULL OR mpesa_code ~ '^[A-Z0-9]{8,12}$');
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_reported_at TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_received_at TIMESTAMPTZ;
-- How many kg one unit of an ordered product is (worked out when the order is placed, from "70 kg bag" or
-- the farm's own feed unit), so collecting it can restock Feed stock without the farmer converting anything.
ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS kg_each NUMERIC(10,2) CHECK (kg_each IS NULL OR kg_each > 0);

-- A promotion: a percentage off one product between two dates. Confirming an order in that window
-- applies it (the price is then copied onto the order like any other).
CREATE TABLE IF NOT EXISTS promotions (
    id              SERIAL PRIMARY KEY,
    agrovet_user_id INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id      INTEGER     NOT NULL REFERENCES agrovet_products(id) ON DELETE CASCADE,
    percent_off     INTEGER     NOT NULL CHECK (percent_off BETWEEN 1 AND 50),
    starts_on       DATE        NOT NULL,
    ends_on         DATE        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (ends_on >= starts_on)
);
CREATE INDEX IF NOT EXISTS idx_promotions_agrovet ON promotions (agrovet_user_id, ends_on);

-- Organisations: each milk buyer or co-op (Fresha, a co-op) runs its own routes. An admin with an
-- organisation sees only that organisation's routes, their farms, vets and visits; an admin with none is
-- the platform owner and sees everything. An agrovet with an organisation is that buyer's own store, the
-- only kind that may take payment from a farm's milk money (for farms on that buyer's routes).
CREATE TABLE IF NOT EXISTS orgs (
    id         SERIAL PRIMARY KEY,
    name       TEXT        NOT NULL UNIQUE CHECK (length(name) BETWEEN 1 AND 80),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE routes ADD COLUMN IF NOT EXISTS org_id INTEGER REFERENCES orgs(id) ON DELETE SET NULL;
ALTER TABLE users  ADD COLUMN IF NOT EXISTS org_id INTEGER REFERENCES orgs(id) ON DELETE SET NULL;

-- ---------------------------------------------------------------------------
-- Phase 5: Maziwa as a bridge to the shops' own systems.
--   A shop keeps its own POS and stock; Maziwa shows its catalogue to farmers (read-only), carries the
--   farmer's order (what, pickup or delivery, the day and time, how they pay) to the shop, and brings back
--   the confirmation. Products come from the shop's system through a bridge, from an uploaded price list,
--   or typed in. Opening hours and time slots let the farmer choose a time the shop can actually serve.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shop_hours (
    agrovet_user_id INTEGER  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    weekday         SMALLINT NOT NULL CHECK (weekday BETWEEN 0 AND 6),   -- 0 = Monday
    opens           TIME     NOT NULL,
    closes          TIME     NOT NULL,
    delivers        BOOLEAN  NOT NULL DEFAULT FALSE,                      -- delivery rounds go out this day
    PRIMARY KEY (agrovet_user_id, weekday),
    CHECK (closes > opens)
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS slot_minutes INTEGER CHECK (slot_minutes IS NULL OR slot_minutes IN (30, 60, 120));
ALTER TABLE users ADD COLUMN IF NOT EXISTS bridge_kind TEXT CHECK (bridge_kind IS NULL OR length(bridge_kind) <= 30);
ALTER TABLE users ADD COLUMN IF NOT EXISTS catalogue_synced_at TIMESTAMPTZ;

ALTER TABLE orders ADD COLUMN IF NOT EXISTS wanted_time TIME;   -- the slot the farmer chose (NULL = any time that day)
ALTER TABLE orders ADD COLUMN IF NOT EXISTS ready_time  TIME;   -- the slot the shop confirmed

ALTER TABLE agrovet_products ADD COLUMN IF NOT EXISTS in_stock BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE agrovet_products ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'manual'
    CHECK (source IN ('manual', 'upload', 'bridge'));
ALTER TABLE agrovet_products ADD COLUMN IF NOT EXISTS external_ref TEXT CHECK (external_ref IS NULL OR length(external_ref) <= 60);

-- What Maziwa handed to a shop's own system (or would send by WhatsApp), so both sides can see it went.
CREATE TABLE IF NOT EXISTS bridge_outbox (
    id              SERIAL PRIMARY KEY,
    agrovet_user_id INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_id        INTEGER     REFERENCES orders(id) ON DELETE SET NULL,
    channel         TEXT        NOT NULL CHECK (channel IN ('pos', 'whatsapp')),
    event           TEXT        NOT NULL CHECK (event IN ('placed', 'cancelled', 'paid')),
    payload         JSONB       NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'sent' CHECK (status IN ('queued', 'sent', 'failed')),
    external_ref    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bridge_outbox_shop ON bridge_outbox (agrovet_user_id, created_at);
