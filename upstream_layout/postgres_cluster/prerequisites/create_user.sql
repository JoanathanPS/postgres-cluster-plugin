-- Site24x7 PostgreSQL Cluster Monitoring User Creation Script
-- Creates a dedicated least-privilege user for PostgreSQL cluster monitoring.
-- Run this script as a superuser (e.g. 'postgres') on the primary node.
--
--   psql -h <primary-host> -U postgres -v mon_user=site24x7 -v mon_pass='your_password' -f create_user.sql
--
-- mon_user defaults to 'site24x7' and mon_pass defaults to 'site24x7' if you do not pass them.
-- Always choose your own password for a real cluster.

\set ON_ERROR_STOP on

\if :{?mon_user}
\else
  \set mon_user site24x7
\endif
\if :{?mon_pass}
\else
  \set mon_pass site24x7
\endif

-- Create the login role (an existing role keeps its password)
SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L', :'mon_user', :'mon_pass')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'mon_user') \gexec
SELECT format('ALTER ROLE %I WITH LOGIN', :'mon_user') \gexec

-- pg_monitor (PostgreSQL 10+): full read-only monitoring privileges (activity, WAL, archiving)
SELECT format('GRANT pg_monitor TO %I', :'mon_user')
 WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pg_monitor') \gexec

-- pg_read_all_stats: activity, replication and bgwriter statistics
SELECT format('GRANT pg_read_all_stats TO %I', :'mon_user') \gexec

-- pg_read_all_settings: server configuration and settings
SELECT format('GRANT pg_read_all_settings TO %I', :'mon_user') \gexec

-- Enforce read-only transactions and a connection limit
SELECT format('ALTER ROLE %I SET default_transaction_read_only = on', :'mon_user') \gexec
SELECT format('ALTER ROLE %I CONNECTION LIMIT 10', :'mon_user') \gexec

-- Execute on the WAL directory functions when they exist (pg_ls_archive_statusdir needs PostgreSQL 12+)
SELECT format('GRANT EXECUTE ON FUNCTION pg_ls_waldir() TO %I', :'mon_user')
 WHERE EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'pg_ls_waldir') \gexec
SELECT format('GRANT EXECUTE ON FUNCTION pg_ls_archive_statusdir() TO %I', :'mon_user')
 WHERE EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'pg_ls_archive_statusdir') \gexec

-- OPTIONAL, Multi-Master (native logical replication): lets the plugin read pg_subscription for peer node discovery.
SELECT format('GRANT SELECT ON pg_catalog.pg_subscription TO %I', :'mon_user')
 WHERE EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'pg_catalog' AND c.relname = 'pg_subscription') \gexec

-- OPTIONAL, repmgr clusters only: lets the plugin read the repmgr node list (database "repmgr") for node discovery.
-- Without it the plugin still finds the nodes by walking the replication topology.
-- \c repmgr
-- GRANT USAGE ON SCHEMA repmgr TO site24x7;
-- GRANT SELECT ON ALL TABLES IN SCHEMA repmgr TO site24x7;

SELECT 'monitoring user ' || :'mon_user' || ' is ready' AS result;
