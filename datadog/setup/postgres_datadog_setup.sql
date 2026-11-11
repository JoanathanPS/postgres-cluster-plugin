-- =============================================================================
-- PostgreSQL Setup for Datadog Monitoring
-- Execute this script as a postgres superuser on your PostgreSQL instance
-- =============================================================================

-- 1. Create the 'datadog' monitoring user with a secure password
CREATE USER datadog WITH PASSWORD 'datadog';

-- 2. Grant pg_monitor role (PostgreSQL 10+)
-- This gives safe, read-only access to pg_stat_activity, pg_stat_database,
-- pg_stat_archiver, pg_stat_replication, and other system catalogs.
GRANT pg_monitor TO datadog;

-- 3. Grant schema usage and SELECT permissions on public schema
GRANT USAGE ON SCHEMA public TO datadog;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO datadog;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO datadog;

-- 4. Enable pg_stat_statements extension (for Query / DBM monitoring)
-- Note: shared_preload_libraries must include 'pg_stat_statements' in postgresql.conf
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- 5. Verification query to test datadog user connectivity & permissions:
-- SELECT datname, numbackends FROM pg_stat_database WHERE datname = current_database();
