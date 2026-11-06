#!/bin/bash
# Test bed standby: copy the primary once, then start as a hot standby.
set -e
export PGDATA=/var/lib/postgresql/data
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  until pg_isready -h pgp-pg1 -U site24x7 >/dev/null 2>&1; do sleep 2; done
  mkdir -p "$PGDATA" && chown postgres:postgres "$PGDATA" && chmod 700 "$PGDATA"
  gosu postgres pg_basebackup -h pgp-pg1 -U site24x7 -D "$PGDATA" -R -X stream
fi
exec docker-entrypoint.sh postgres -c hot_standby=on
