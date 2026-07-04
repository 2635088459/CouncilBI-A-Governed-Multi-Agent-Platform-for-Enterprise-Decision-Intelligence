#!/bin/sh
set -eu

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${CHATBI_READONLY_PASSWORD:?CHATBI_READONLY_PASSWORD is required}"

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=readonly_password="$CHATBI_READONLY_PASSWORD" <<'SQL'
CREATE SCHEMA IF NOT EXISTS business;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'chatbi_readonly'
    ) THEN
        CREATE ROLE chatbi_readonly LOGIN;
    END IF;
END
$$;

ALTER ROLE chatbi_readonly WITH PASSWORD :'readonly_password';
GRANT USAGE ON SCHEMA business TO chatbi_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA business TO chatbi_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA business
    GRANT SELECT ON TABLES TO chatbi_readonly;
ALTER ROLE chatbi_readonly SET search_path = business, public;
SQL
