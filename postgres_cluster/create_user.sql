-- Site24x7 PostgreSQL Cluster Monitoring User Creation Script
-- Creates a dedicated least-privilege user for PostgreSQL cluster monitoring.
-- Run this script as a superuser (e.g. 'postgres') on the primary node
-- (or each node if standalone/bootstrap).

\set ON_ERROR_STOP on

-- Default monitoring username is 'site24x7'
-- You can override password via: psql -v mon_user=site24x7 -v mon_pass='your_password' -f create_user.sql

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'site24x7') THEN
        CREATE ROLE site24x7 WITH LOGIN PASSWORD 'site24x7';
    ELSE
        ALTER ROLE site24x7 WITH LOGIN;
    END IF;
END
$$;

-- Grant pg_read_all_stats for viewing activity, replication, and bgwriter stats
GRANT pg_read_all_stats TO site24x7;

-- Grant pg_read_all_settings for viewing server configuration and settings
GRANT pg_read_all_settings TO site24x7;

-- Enforce read-only transaction mode and connection limits
ALTER ROLE site24x7 SET default_transaction_read_only = on;
ALTER ROLE site24x7 CONNECTION LIMIT 10;

-- Grant execute on WAL inspection functions if present
DO $$
BEGIN
    EXECUTE 'GRANT EXECUTE ON FUNCTION pg_ls_waldir() TO site24x7';
EXCEPTION WHEN OTHERS THEN
    -- Ignore if function does not exist or version does not support it
    NULL;
END
$$;
