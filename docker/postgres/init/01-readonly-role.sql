CREATE SCHEMA IF NOT EXISTS business;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'chatbi_readonly'
    ) THEN
        CREATE ROLE chatbi_readonly LOGIN PASSWORD 'chatbi_readonly_password';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA business TO chatbi_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA business TO chatbi_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA business
    GRANT SELECT ON TABLES TO chatbi_readonly;
ALTER ROLE chatbi_readonly SET search_path = business, public;
