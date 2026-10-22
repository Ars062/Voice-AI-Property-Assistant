-- =============================================================================
-- 001_schema.sql  -  Voice AI Property Assistant schema (PostgreSQL 16)
-- Idempotent: safe to re-run.
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ---------------------------------------------------------------------------
-- Properties
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS properties (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    address_line  TEXT NOT NULL,
    city          TEXT NOT NULL,
    region        TEXT,
    postal_code   TEXT,
    property_type TEXT NOT NULL,
    description   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Rentable rooms / units
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rooms (
    id             SERIAL PRIMARY KEY,
    property_id    INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    unit_label     TEXT NOT NULL,
    room_type      TEXT NOT NULL,
    monthly_rent   NUMERIC(10, 2) NOT NULL CHECK (monthly_rent >= 0),
    deposit        NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (deposit >= 0),
    size_sqm       NUMERIC(6, 2) CHECK (size_sqm IS NULL OR size_sqm > 0),
    max_occupants  INTEGER NOT NULL DEFAULT 1 CHECK (max_occupants > 0),
    available_from DATE NOT NULL DEFAULT CURRENT_DATE,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    description    TEXT,
    UNIQUE (property_id, unit_label)
);

CREATE INDEX IF NOT EXISTS idx_rooms_property ON rooms (property_id);
CREATE INDEX IF NOT EXISTS idx_rooms_rent     ON rooms (monthly_rent);
CREATE INDEX IF NOT EXISTS idx_rooms_active   ON rooms (is_active) WHERE is_active;

-- ---------------------------------------------------------------------------
-- Amenities (many-to-many)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS amenities (
    id       SERIAL PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'general'
);

CREATE TABLE IF NOT EXISTS room_amenities (
    room_id    INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    amenity_id INTEGER NOT NULL REFERENCES amenities(id) ON DELETE CASCADE,
    PRIMARY KEY (room_id, amenity_id)
);

-- ---------------------------------------------------------------------------
-- Property policies (pets, smoking, parking, ...)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS policies (
    id          SERIAL PRIMARY KEY,
    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    policy_type TEXT NOT NULL,
    description TEXT NOT NULL,
    UNIQUE (property_id, policy_type)
);

-- ---------------------------------------------------------------------------
-- Bookings. A gist exclusion constraint makes double-booking impossible at
-- the database level even under concurrent transactions.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bookings (
    id              SERIAL PRIMARY KEY,
    room_id         INTEGER NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
    guest_name      TEXT NOT NULL,
    guest_email     TEXT,
    check_in        DATE NOT NULL,
    check_out       DATE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'confirmed'
                    CHECK (status IN ('confirmed', 'cancelled')),
    idempotency_key TEXT UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (check_out > check_in)
);

ALTER TABLE bookings DROP CONSTRAINT IF EXISTS bookings_no_overlap;
ALTER TABLE bookings ADD CONSTRAINT bookings_no_overlap
    EXCLUDE USING gist (
        room_id WITH =,
        daterange(check_in, check_out, '[)') WITH &&
    ) WHERE (status = 'confirmed');

CREATE INDEX IF NOT EXISTS idx_bookings_room_dates
    ON bookings (room_id, check_in, check_out);

-- ---------------------------------------------------------------------------
-- Owner/maintenance blocks (no guest PII)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS room_blocks (
    id         SERIAL PRIMARY KEY,
    room_id    INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    start_date DATE NOT NULL,
    end_date   DATE NOT NULL,
    reason     TEXT NOT NULL DEFAULT 'maintenance',
    CHECK (end_date > start_date),
    UNIQUE (room_id, start_date, end_date)
);

-- ---------------------------------------------------------------------------
-- Privacy-safe view: exposes blocked date ranges WITHOUT guest details.
-- The read-only role can SELECT this view but has no access to `bookings`.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW room_blocked_ranges AS
    SELECT room_id, check_in AS start_date, check_out AS end_date, 'booking'::text AS source
      FROM bookings
     WHERE status = 'confirmed'
    UNION ALL
    SELECT room_id, start_date, end_date, 'block'::text AS source
      FROM room_blocks;
