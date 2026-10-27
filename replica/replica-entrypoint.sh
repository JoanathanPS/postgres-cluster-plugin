#!/bin/bash
# Entrypoint for pg-replica.
# First start (empty volume): clone the primary with pg_basebackup.
#   -R  writes standby.signal + primary_conninfo, so the node starts as a hot standby
#   -S  streams from the physical slot created on the primary
#   -X stream  includes the WAL needed for a consistent copy
# Later starts: the data directory exists, so it simply starts as a standby.
set -euo pipefail

: "${PGDATA:=/var/lib/postgresql/data}"
: "${PRIMARY_HOST:?PRIMARY_HOST is required}"
: "${PRIMARY_PORT:=5432}"
: "${REPLICATION_USER:?REPLICATION_USER is required}"
: "${REPLICATION_PASSWORD:?REPLICATION_PASSWORD is required}"
: "${REPLICATION_SLOT:?REPLICATION_SLOT is required}"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "replica: waiting for primary ${PRIMARY_HOST}:${PRIMARY_PORT} ..."
  until gosu postgres pg_isready -q -h "$PRIMARY_HOST" -p "$PRIMARY_PORT"; do
    sleep 2
  done

  mkdir -p "$PGDATA"
  chown postgres:postgres "$PGDATA"
  chmod 0700 "$PGDATA"

  echo "replica: running pg_basebackup from ${PRIMARY_HOST} using slot ${REPLICATION_SLOT} ..."
  gosu postgres env PGPASSWORD="$REPLICATION_PASSWORD" \
    pg_basebackup -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U "$REPLICATION_USER" \
                  -D "$PGDATA" -X stream -R -S "$REPLICATION_SLOT" --checkpoint=fast
  echo "replica: base backup complete"
fi

# Hand over to the official entrypoint (it skips initdb because PGDATA is populated
# and drops privileges to the postgres user).
exec docker-entrypoint.sh "$@"
