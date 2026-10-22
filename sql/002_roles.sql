-- =============================================================================
-- 002_roles.sql  -  Restricted, read-only role for property search.
-- Defence in depth:
--   * no table privileges except an explicit allow-list
--   * no access to `bookings` (guest PII)
--   * default_transaction_read_only so even a mistake cannot write
-- Idempotent: safe to re-run.
-- =============================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'voice_readonly') THEN
        CREATE ROLE voice_readonly LOGIN PASSWORD 'voice_readonly_pw';
    END IF;
END
$$;

ALTER ROLE voice_readonly SET default_transaction_read_only = on;
ALTER ROLE voice_readonly SET statement_timeout = '8s';
ALTER ROLE voice_readonly SET idle_in_transaction_session_timeout = '15s';

DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO voice_readonly', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO voice_readonly;

GRANT SELECT ON
    properties,
    rooms,
    amenities,
    room_amenities,
    policies,
    room_blocks,
    room_blocked_ranges
TO voice_readonly;

-- Explicitly deny guest data.
REVOKE ALL ON bookings FROM voice_readonly;

-- Make sure no inherited PUBLIC grants leak write access.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
