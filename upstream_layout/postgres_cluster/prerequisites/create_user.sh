#!/bin/bash
# Site24x7 PostgreSQL Cluster User Creation Script
# Automates creating the least-privilege 'site24x7' monitoring user.

set -e

# Default variables
PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
SUPERUSER="${SUPERUSER:-postgres}"
DBNAME="${DBNAME:-postgres}"
MONITOR_USER="${MONITOR_USER:-site24x7}"
MONITOR_PASSWORD="${MONITOR_PASSWORD:-site24x7}"

echo "=========================================================="
echo " Site24x7 PostgreSQL Cluster - Monitoring User Setup      "
echo "=========================================================="
echo "Host:             $PGHOST"
echo "Port:             $PGPORT"
echo "Superuser:        $SUPERUSER"
echo "Monitoring User:  $MONITOR_USER"
echo "Database:         $DBNAME"
echo "=========================================================="

if [ -t 0 ] && [ -z "$NON_INTERACTIVE" ]; then
    read -p "Enter PostgreSQL Host [$PGHOST]: " input_host
    PGHOST="${input_host:-$PGHOST}"
    read -p "Enter PostgreSQL Port [$PGPORT]: " input_port
    PGPORT="${input_port:-$PGPORT}"
    read -p "Enter Administrative User [$SUPERUSER]: " input_admin
    SUPERUSER="${input_admin:-$SUPERUSER}"
    read -p "Enter Monitoring Username [$MONITOR_USER]: " input_user
    MONITOR_USER="${input_user:-$MONITOR_USER}"
    read -s -p "Enter Password for '$MONITOR_USER' [$MONITOR_PASSWORD]: " input_pass
    echo
    MONITOR_PASSWORD="${input_pass:-$MONITOR_PASSWORD}"
fi

echo "Connecting to PostgreSQL and creating user '$MONITOR_USER'..."

psql -h "$PGHOST" -p "$PGPORT" -U "$SUPERUSER" -d "$DBNAME" <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$MONITOR_USER') THEN
        CREATE ROLE "$MONITOR_USER" WITH LOGIN PASSWORD '$MONITOR_PASSWORD';
    ELSE
        ALTER ROLE "$MONITOR_USER" WITH LOGIN PASSWORD '$MONITOR_PASSWORD';
    END IF;
END
\$\$;

DO \$\$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pg_monitor') THEN
        EXECUTE 'GRANT pg_monitor TO "$MONITOR_USER"';
    END IF;
END
\$\$;

GRANT pg_read_all_stats TO "$MONITOR_USER";
GRANT pg_read_all_settings TO "$MONITOR_USER";
ALTER ROLE "$MONITOR_USER" SET default_transaction_read_only = on;
ALTER ROLE "$MONITOR_USER" CONNECTION LIMIT 10;

DO \$\$
BEGIN
    EXECUTE 'GRANT EXECUTE ON FUNCTION pg_ls_waldir() TO "$MONITOR_USER"';
EXCEPTION WHEN OTHERS THEN
    NULL;
END
\$\$;

DO \$\$
BEGIN
    EXECUTE 'GRANT EXECUTE ON FUNCTION pg_ls_archive_statusdir() TO "$MONITOR_USER"';
EXCEPTION WHEN OTHERS THEN
    NULL;
END
\$\$;
EOF

echo "Verifying monitoring user privileges for pg_ls_waldir() and pg_ls_archive_statusdir()..."
PGPASSWORD="$MONITOR_PASSWORD" psql -h "$PGHOST" -p "$PGPORT" -U "$MONITOR_USER" -d "$DBNAME" -c "SELECT count(*) AS wal_files_accessible FROM pg_ls_waldir();"
PGPASSWORD="$MONITOR_PASSWORD" psql -h "$PGHOST" -p "$PGPORT" -U "$MONITOR_USER" -d "$DBNAME" -c "SELECT count(*) AS archive_status_accessible FROM pg_ls_archive_statusdir();"

echo
echo "✓ Monitoring user '$MONITOR_USER' configured and verified successfully!"
echo "You can now update postgres_cluster.cfg with username='$MONITOR_USER' and password."
