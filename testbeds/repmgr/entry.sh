#!/bin/bash
set -e

cat > /tmp/repmgr.conf <<CONF
node_id=${NODE_ID}
node_name='${NODE_NAME}'
conninfo='host=${NODE_NAME} user=repmgr dbname=repmgr connect_timeout=2'
data_directory='${PGDATA}'
pg_bindir='/usr/lib/postgresql/17/bin'
use_replication_slots=yes
failover='automatic'
promote_command='/usr/lib/postgresql/17/bin/repmgr standby promote -f /tmp/repmgr.conf --log-to-file'
follow_command='/usr/lib/postgresql/17/bin/repmgr standby follow -f /tmp/repmgr.conf --log-to-file --upstream-node-id=%n'
log_level='INFO'
log_file='/tmp/repmgrd.log'
CONF

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  if [ "$NODE_TYPE" = "witness" ]; then
    initdb -D "$PGDATA" --auth=trust
    cat >> "$PGDATA/postgresql.conf" <<CONF
listen_addresses='*'
shared_preload_libraries='repmgr'
CONF
    echo "host all all 0.0.0.0/0 trust" >> "$PGDATA/pg_hba.conf"
    echo "host replication all 0.0.0.0/0 trust" >> "$PGDATA/pg_hba.conf"
    pg_ctl -D "$PGDATA" -w start
    psql -d postgres -c "CREATE USER repmgr SUPERUSER" -c "CREATE DATABASE repmgr OWNER repmgr" \
         -c "CREATE USER site24x7 PASSWORD 'site24x7'" -c "GRANT pg_monitor TO site24x7"
    until psql -h "$PRIMARY_HOST" -U repmgr -d repmgr -c "select 1" >/dev/null 2>&1; do sleep 2; done
    repmgr -f /tmp/repmgr.conf -h "$PRIMARY_HOST" -U repmgr -d repmgr witness register
    psql -d repmgr -c "GRANT USAGE ON SCHEMA repmgr TO site24x7" -c "GRANT SELECT ON ALL TABLES IN SCHEMA repmgr TO site24x7"
    pg_ctl -D "$PGDATA" -w stop
  elif [ "$NODE_ID" = "1" ]; then
    initdb -D "$PGDATA" --auth=trust
    cat >> "$PGDATA/postgresql.conf" <<CONF
listen_addresses='*'
shared_preload_libraries='repmgr'
wal_level=replica
max_wal_senders=10
max_replication_slots=10
hot_standby=on
wal_log_hints=on
CONF
    echo "host all all 0.0.0.0/0 trust" >> "$PGDATA/pg_hba.conf"
    echo "host replication all 0.0.0.0/0 trust" >> "$PGDATA/pg_hba.conf"
    pg_ctl -D "$PGDATA" -w start
    psql -d postgres -c "CREATE USER repmgr SUPERUSER" -c "CREATE DATABASE repmgr OWNER repmgr" \
         -c "CREATE USER site24x7 PASSWORD 'site24x7'" -c "GRANT pg_monitor TO site24x7"
    repmgr -f /tmp/repmgr.conf primary register
    psql -d repmgr -c "GRANT USAGE ON SCHEMA repmgr TO site24x7" -c "GRANT SELECT ON ALL TABLES IN SCHEMA repmgr TO site24x7"
    pg_ctl -D "$PGDATA" -w stop
  else
    until psql -h "$PRIMARY_HOST" -U repmgr -d repmgr -c "select 1" >/dev/null 2>&1; do sleep 2; done
    sleep 3
    repmgr -h "$PRIMARY_HOST" -U repmgr -d repmgr -f /tmp/repmgr.conf standby clone -F
    pg_ctl -D "$PGDATA" -w start
    repmgr -f /tmp/repmgr.conf standby register -F
    pg_ctl -D "$PGDATA" -w stop
  fi
fi

pg_ctl -D "$PGDATA" -w start
repmgrd -f /tmp/repmgr.conf -d --pid-file=/tmp/repmgrd.pid

trap "kill \$(cat /tmp/repmgrd.pid 2>/dev/null) 2>/dev/null; pg_ctl -D '$PGDATA' -w stop; exit 0" SIGTERM SIGINT

while true; do
  sleep 2
done
