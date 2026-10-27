#!/bin/bash
# Runs once, on the primary's first start (empty data volume), via the official
# postgres image's /docker-entrypoint-initdb.d mechanism.
#
# Creates:
#   * a replication role + physical replication slot for pg-replica
#   * a least-privilege monitoring role for the Site24x7 postgres plugin
#     (LOGIN + pg_read_all_stats, as required by the plugin README)
#   * a pg_hba.conf rule allowing streaming replication with SCRAM auth
#
# Note: this file may be *sourced* by the entrypoint (if it is not executable on
# the host, e.g. on Windows), so it avoids `set -u` and `exit`.
set -eo pipefail

for v in REPLICATION_USER REPLICATION_PASSWORD REPLICATION_SLOT MONITOR_USER MONITOR_PASSWORD; do
  if [ -z "${!v}" ]; then
    echo "01-init-cluster.sh: environment variable $v is empty" >&2
    false
  fi
done

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" --dbname "${POSTGRES_DB:-postgres}" \
     -v repl_user="$REPLICATION_USER" -v repl_pass="$REPLICATION_PASSWORD" \
     -v repl_slot="$REPLICATION_SLOT" \
     -v mon_user="$MONITOR_USER"     -v mon_pass="$MONITOR_PASSWORD" <<'SQL'
-- Replication account: may only open replication connections.
CREATE ROLE :"repl_user" WITH LOGIN REPLICATION PASSWORD :'repl_pass';

-- Physical slot so the primary keeps the WAL the replica still needs.
SELECT pg_create_physical_replication_slot(:'repl_slot');

-- Monitoring account for Site24x7: no superuser, no CREATE, read-only by default.
CREATE ROLE :"mon_user" WITH LOGIN PASSWORD :'mon_pass'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT 5;
GRANT pg_read_all_stats TO :"mon_user";
ALTER ROLE :"mon_user" SET default_transaction_read_only = on;
SQL

# The image already appends "host all all all scram-sha-256"; the keyword "all"
# does not match replication connections, so add an explicit rule.
echo "host replication ${REPLICATION_USER} all scram-sha-256" >> "$PGDATA/pg_hba.conf"

echo "01-init-cluster.sh: created roles '${REPLICATION_USER}', '${MONITOR_USER}' and slot '${REPLICATION_SLOT}'"
