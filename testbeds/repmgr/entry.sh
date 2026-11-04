#!/bin/bash
# Test bed: repmgr cluster node. NODE_ID, NODE_NAME, PRIMARY_HOST come from the environment.
set -e
cat > /tmp/repmgr.conf <<CONF
node_id=${NODE_ID}
node_name=${NODE_NAME}
conninfo='host=${NODE_NAME} user=repmgr dbname=repmgr connect_timeout=2'
data_directory='${PGDATA}'
use_replication_slots=yes
CONF
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  if [ "$NODE_ID" = "1" ]; then
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
exec postgres -D "$PGDATA"
