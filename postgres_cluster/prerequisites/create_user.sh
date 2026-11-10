#!/bin/bash
# Site24x7 PostgreSQL Cluster User Creation Script
# Creates the least-privilege monitoring role and asks psql to set its password securely.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
SUPERUSER="${SUPERUSER:-postgres}"
DBNAME="${DBNAME:-postgres}"
MONITOR_USER="${MONITOR_USER:-site24x7}"

if [ ! -t 0 ] || [ -n "${NON_INTERACTIVE:-}" ]; then
    echo "Run this helper interactively. psql securely prompts for the monitoring-role password." >&2
    exit 1
fi

echo "Site24x7 PostgreSQL Cluster - Monitoring User Setup"
echo "Host: $PGHOST"
echo "Port: $PGPORT"
echo "Administrative user: $SUPERUSER"
read -r -p "Monitoring username [$MONITOR_USER]: " input_user
MONITOR_USER="${input_user:-$MONITOR_USER}"

echo "Creating/updating role privileges, then securely setting the role password."
psql -X -h "$PGHOST" -p "$PGPORT" -U "$SUPERUSER" -d "$DBNAME" \
    -v "mon_user=$MONITOR_USER" \
    -f "$script_dir/create_user.sql"

psql -X -h "$PGHOST" -p "$PGPORT" -U "$SUPERUSER" -d "$DBNAME" \
    -v "mon_user=$MONITOR_USER" \
    -c '\password :mon_user'

echo "Monitoring role '$MONITOR_USER' configured. Update postgres_cluster.cfg with its username and chosen password."
