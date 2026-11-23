#!/usr/bin/python3
"""
Site24x7 PostgreSQL plugin, version 2.

Monitors the PostgreSQL server at --host/--port. Every metric comes from a
declarative catalogue (QUERIES, TABLES, RATES below): each entry is one SQL
statement, the PostgreSQL versions it applies to, and the metrics its columns
become. A small engine runs the catalogue, so adding a metric is one entry and
never a new branch of code.

Rules the engine enforces:
  * A failed or inapplicable query removes its metrics; it never reports 0.
  * A NULL value removes that metric for this poll.
  * `status` is 0 only when the server cannot be monitored at all (driver
    missing, connection or authentication failure, unsupported version).
  * Rates and deltas need a previous sample of the same server process; until
    then they are omitted, never shown as 0.
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time

try:
    import psycopg2
    HAVE_PSYCOPG2 = True
except ImportError:
    psycopg2 = None
    HAVE_PSYCOPG2 = False


PLUGIN_VERSION = 2
HEARTBEAT = True

VERSION_FLOOR = (9, 6)
CONNECT_TIMEOUT_S = 10
STATEMENT_TIMEOUT_MS = 5000
CYCLE_BUDGET_S = 40.0          # the agent kills a plugin after 50 s
RATE_MIN_INTERVAL_S = 0.5
RATE_MAX_INTERVAL_S = 3600.0
LONG_QUERY_S = 300

# Site24x7 platform limits
MAX_TABLES = 10
MAX_COLUMNS = 15
MAX_ROWS = 25
MAX_STRING_COLS = 5            # including `name`
MAX_NAME_CHARS = 520
MAX_STRING_CHARS = 100
MAX_METRICS = 200
MAX_MSG_CHARS = 180

RESERVED_KEYS = {
    "plugin_version", "heartbeat_required", "status", "msg", "units",
    "tabs", "s247config", "applog",
}

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(PLUGIN_DIR, ".state")

DRIVER_MISSING_MSG = (
    "psycopg2 module not installed. Install it for the agent's Python: "
    "pip3 install psycopg2-binary"
)

# Node roles reported in `Node Role`.
ROLE_PRIMARY = "primary"
ROLE_STANDBY = "standby"

# Which kind of node a query applies to.
ANY, PRIMARY, STANDBY = "any", "primary", "standby"


# =============================================================================
# 1. CATALOGUE
# =============================================================================

class M(object):
    """One metric produced by one column of a query."""

    def __init__(self, name, unit="", tab="", kind=int):
        self.name = name
        self.unit = unit
        self.tab = tab
        self.kind = kind          # int, float or str


class Variant(object):
    """The SQL used from PostgreSQL `min_ver` upward, and the metrics its columns map to."""

    def __init__(self, min_ver, sql, fields):
        self.min_ver = min_ver
        self.sql = sql
        self.fields = fields


class Query(object):
    """A single-row query. The highest variant the server satisfies is used."""

    def __init__(self, key, variants, role=ANY, when=None):
        self.key = key
        self.variants = sorted(variants, key=lambda v: v.min_ver, reverse=True)
        self.role = role
        self.when = when          # optional callable(node) -> bool

    def pick(self, version):
        for v in self.variants:
            if version >= v.min_ver:
                return v
        return None


class Table(object):
    """A multi-row query whose rows become a Site24x7 child table."""

    def __init__(self, name, tab, variants, units, role=ANY, when=None):
        self.name = name
        self.tab = tab
        self.variants = sorted(variants, key=lambda v: v[0], reverse=True)
        self.units = units        # column -> unit, also fixes column order and types
        self.role = role
        self.when = when

    def pick(self, version):
        for min_ver, sql in self.variants:
            if version >= min_ver:
                return sql
        return None


class Rate(object):
    """A per-second rate (or a per-poll delta) of a cumulative counter metric."""

    def __init__(self, name, source, unit, tab, delta=False, scale=1.0):
        self.name = name
        self.source = source
        self.unit = unit
        self.tab = tab
        self.delta = delta        # True: change since the previous poll, not per second
        self.scale = scale


TAB_ORDER = [
    "Activity",
    "Transactions and Sessions",
    "DB and IO stats",
    "BG Writer",
    "Vacuum and Wraparound",
    "WAL and Archiving",
    "Replication",
    "Plugin",
]
SUMMARY = ""                      # metrics with no tab chart on the built-in Summary tab

# pg_stat_activity filter for client sessions, excluding this plugin's own session.
_CLIENTS_10 = "backend_type = 'client backend' AND pid <> pg_backend_pid()"
_CLIENTS_96 = "datname IS NOT NULL AND pid <> pg_backend_pid()"


def _activity_sql(clients):
    return (
        "SELECT count(*) FILTER (WHERE state = 'active'),"
        " count(*) FILTER (WHERE state = 'active' AND wait_event IS NOT NULL),"
        " count(*) FILTER (WHERE state = 'idle'),"
        " count(*) FILTER (WHERE state LIKE 'idle in transaction%%'),"
        " count(*) FILTER (WHERE xact_start IS NOT NULL),"
        " coalesce(max(extract(epoch FROM now() - xact_start)), 0)::bigint,"
        " count(*) FILTER (WHERE state = 'active' AND now() - query_start > interval '%d seconds'),"
        " count(*) FILTER (WHERE cardinality(pg_blocking_pids(pid)) > 0)"
        " FROM pg_stat_activity WHERE %s" % (LONG_QUERY_S, clients)
    )


_ACTIVITY_FIELDS = [
    M("Active Queries", "queries", "Activity"),
    M("Active Waiting Queries", "queries", "Activity"),
    M("Idle Connections", "connections", "Activity"),
    M("Transactions Idle In Transaction", "transactions", "Transactions and Sessions"),
    M("Transactions Open", "transactions", "Transactions and Sessions"),
    M("Longest Transaction", "s", "Activity"),
    M("Long Running Queries", "queries", "Activity"),
    M("Blocked Sessions", "sessions", "Activity"),
]

QUERIES = [
    Query("server", [Variant((9, 6),
        "SELECT current_setting('server_version'),"
        " floor(extract(epoch FROM now() - pg_postmaster_start_time()))::bigint,"
        " current_setting('max_connections')::int,"
        " (SELECT count(*) FROM pg_database WHERE datname NOT IN ('template0', 'template1')),"
        " (SELECT count(*) FROM pg_stat_all_tables)",
        [M("Server Version", tab="Activity", kind=str),
         M("Uptime", "s", SUMMARY),
         M("Max Connections", "connections", "Activity"),
         M("Database Count", "databases", "DB and IO stats"),
         M("Table Count", "tables", "DB and IO stats")])]),

    Query("activity", [
        Variant((10, 0), _activity_sql(_CLIENTS_10), _ACTIVITY_FIELDS),
        Variant((9, 6), _activity_sql(_CLIENTS_96), _ACTIVITY_FIELDS)]),

    Query("database_totals", [Variant((9, 6),
        "SELECT sum(numbackends), sum(xact_commit), sum(xact_rollback), sum(conflicts),"
        " sum(deadlocks), sum(tup_inserted), sum(tup_updated), sum(tup_deleted),"
        " sum(tup_fetched), sum(tup_returned), sum(blks_read), sum(blks_hit),"
        " sum(temp_files), round(sum(temp_bytes) / 1048576.0, 2)"
        " FROM pg_stat_database",
        [M("Active Connections", "connections", SUMMARY),
         M("Total Commits", "transactions", "Transactions and Sessions"),
         M("Total Rollbacks", "transactions", "Transactions and Sessions"),
         M("Total Conflicts", "conflicts", "Transactions and Sessions"),
         M("Total Deadlocks", "deadlocks", "Transactions and Sessions"),
         M("Total Rows Inserted", "rows", "DB and IO stats"),
         M("Total Rows Updated", "rows", "DB and IO stats"),
         M("Total Rows Deleted", "rows", "DB and IO stats"),
         M("Total Rows Fetched", "rows", "DB and IO stats"),
         M("Total Rows Returned", "rows", "DB and IO stats"),
         M("Total Block Reads", "blocks", "DB and IO stats"),
         M("Total Block Hits", "blocks", "DB and IO stats"),
         M("Total Temp Files", "files", "DB and IO stats"),
         M("Total Temp Data", "MB", "DB and IO stats", float)])]),

    Query("sessions", [Variant((14, 0),
        "SELECT sum(sessions), sum(sessions_abandoned), sum(sessions_fatal), sum(sessions_killed)"
        " FROM pg_stat_database",
        [M("Total Sessions", "sessions", "Transactions and Sessions"),
         M("Total Sessions Abandoned", "sessions", "Transactions and Sessions"),
         M("Total Sessions Fatal", "sessions", "Transactions and Sessions"),
         M("Total Sessions Killed", "sessions", "Transactions and Sessions")])]),

    Query("bgwriter", [
        Variant((17, 0),
            "SELECT c.num_timed, c.num_requested, c.write_time, c.sync_time, c.buffers_written,"
            " b.buffers_clean, b.maxwritten_clean, b.buffers_alloc"
            " FROM pg_stat_checkpointer c, pg_stat_bgwriter b",
            [M("Checkpoints Timed", "checkpoints", "BG Writer"),
             M("Checkpoints Req", "checkpoints", "BG Writer"),
             M("Checkpoint Write Time", "ms", "BG Writer", float),
             M("Checkpoint Sync Time", "ms", "BG Writer", float),
             M("Buffers Checkpoint", "buffers", "BG Writer"),
             M("Buffers Clean", "buffers", "BG Writer"),
             M("Maxwritten Clean", "times", "BG Writer"),
             M("Buffers Alloc", "buffers", "BG Writer")]),
        Variant((9, 6),
            "SELECT checkpoints_timed, checkpoints_req, checkpoint_write_time, checkpoint_sync_time,"
            " buffers_checkpoint, buffers_clean, maxwritten_clean, buffers_alloc,"
            " buffers_backend, buffers_backend_fsync FROM pg_stat_bgwriter",
            [M("Checkpoints Timed", "checkpoints", "BG Writer"),
             M("Checkpoints Req", "checkpoints", "BG Writer"),
             M("Checkpoint Write Time", "ms", "BG Writer", float),
             M("Checkpoint Sync Time", "ms", "BG Writer", float),
             M("Buffers Checkpoint", "buffers", "BG Writer"),
             M("Buffers Clean", "buffers", "BG Writer"),
             M("Maxwritten Clean", "times", "BG Writer"),
             M("Buffers Alloc", "buffers", "BG Writer"),
             M("Buffers Backend", "buffers", "BG Writer"),
             M("Buffers Backend Fsync", "fsyncs", "BG Writer")])]),

    Query("locks", [Variant((9, 6),
        "SELECT count(*), count(*) FILTER (WHERE NOT granted) FROM pg_locks"
        " WHERE pid IS DISTINCT FROM pg_backend_pid()",
        [M("Locks Count", "locks", "Activity"),
         M("Waiting Locks", "locks", "Activity")])]),

    Query("table_stats", [Variant((9, 6),
        "SELECT (SELECT sum(idx_scan) FROM pg_stat_user_indexes),"
        " (SELECT sum(idx_tup_read) FROM pg_stat_user_indexes),"
        " (SELECT sum(idx_tup_fetch) FROM pg_stat_user_indexes),"
        " sum(seq_scan), sum(n_dead_tup), sum(n_live_tup),"
        " count(*) FILTER (WHERE coalesce(last_vacuum, last_autovacuum) IS NULL AND n_live_tup > 0),"
        " floor(extract(epoch FROM now() - min(greatest(last_vacuum, last_autovacuum))))::bigint"
        " FROM pg_stat_user_tables",
        [M("Index Scans", "scans", "DB and IO stats"),
         M("Index Rows Read", "rows", "DB and IO stats"),
         M("Index Rows Fetched", "rows", "DB and IO stats"),
         M("Sequential Scans", "scans", "DB and IO stats"),
         M("Dead Tuples", "rows", "Vacuum and Wraparound"),
         M("Live Tuples", "rows", "Vacuum and Wraparound"),
         M("Tables Never Vacuumed", "tables", "Vacuum and Wraparound"),
         M("Oldest Table Vacuum Age", "s", "Vacuum and Wraparound")])]),

    Query("heap", [Variant((9, 6),
        "SELECT sum(heap_blks_read), sum(heap_blks_hit),"
        " CASE WHEN coalesce(sum(heap_blks_hit) + sum(heap_blks_read), 0) = 0 THEN NULL"
        " ELSE round(sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)), 4) END,"
        " CASE WHEN coalesce(sum(idx_blks_hit) + sum(idx_blks_read), 0) = 0 THEN NULL"
        " ELSE round(100.0 * sum(idx_blks_hit) / (sum(idx_blks_hit) + sum(idx_blks_read)), 2) END"
        " FROM pg_statio_user_tables",
        [M("Heap Blocks Read", "blocks", "DB and IO stats"),
         M("Heap Blocks Hit", "blocks", "DB and IO stats"),
         M("Cache Hit Ratio", "ratio", "DB and IO stats", float),
         M("Index Hit Percent", "%", "DB and IO stats", float)])]),

    Query("wraparound", [Variant((9, 6),
        "SELECT max(age(datfrozenxid)), max(mxid_age(datminmxid)),"
        " round(100.0 * max(age(datfrozenxid)) / current_setting('autovacuum_freeze_max_age')::numeric, 2)"
        " FROM pg_database WHERE datallowconn",
        [M("Max XID Age", "transactions", "Vacuum and Wraparound"),
         M("Max Multixact Age", "multixacts", "Vacuum and Wraparound"),
         M("XID Wraparound Percent", "%", "Vacuum and Wraparound", float)])]),

    Query("database_size", [Variant((9, 6),
        "SELECT round(sum(CASE WHEN has_database_privilege(oid, 'CONNECT')"
        " THEN pg_database_size(oid) ELSE 0 END) / 1048576.0, 2)"
        " FROM pg_database WHERE datallowconn",
        [M("Total Database Size", "MB", "DB and IO stats", float)])]),

    Query("checksums", [Variant((12, 0),
        "SELECT sum(checksum_failures) FROM pg_stat_database",
        [M("Checksum Failures", "failures", "DB and IO stats")])]),

    Query("wal_position", [
        Variant((10, 0),
            "SELECT round(pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0') / 1048576.0, 2)",
            [M("WAL Written", "MB", "WAL and Archiving", float)]),
        Variant((9, 6),
            "SELECT round(pg_xlog_location_diff(pg_current_xlog_location(), '0/0') / 1048576.0, 2)",
            [M("WAL Written", "MB", "WAL and Archiving", float)])],
        role=PRIMARY),

    Query("wal_directory", [Variant((10, 0),
        "SELECT count(*), round(coalesce(sum(size), 0) / 1048576.0, 2) FROM pg_ls_waldir()",
        [M("WAL Files", "files", "WAL and Archiving"),
         M("WAL Directory Size", "MB", "WAL and Archiving", float)])]),

    Query("archiver", [
        Variant((12, 0),
            "SELECT archived_count, failed_count,"
            " floor(extract(epoch FROM now() - last_archived_time))::bigint,"
            " CASE WHEN last_failed_time IS NOT NULL AND (last_archived_time IS NULL"
            " OR last_failed_time > last_archived_time) THEN 1 ELSE 0 END,"
            " (SELECT count(*) FROM pg_ls_archive_statusdir() WHERE name LIKE '%.ready')"
            " FROM pg_stat_archiver",
            [M("Archived Count", "files", "WAL and Archiving"),
             M("Archive Failed Count", "files", "WAL and Archiving"),
             M("Last Archive Age", "s", "WAL and Archiving"),
             M("Archiving Failing", "flag", "WAL and Archiving"),
             M("Archive Ready Files", "files", "WAL and Archiving")]),
        Variant((9, 6),
            "SELECT archived_count, failed_count,"
            " floor(extract(epoch FROM now() - last_archived_time))::bigint,"
            " CASE WHEN last_failed_time IS NOT NULL AND (last_archived_time IS NULL"
            " OR last_failed_time > last_archived_time) THEN 1 ELSE 0 END"
            " FROM pg_stat_archiver",
            [M("Archived Count", "files", "WAL and Archiving"),
             M("Archive Failed Count", "files", "WAL and Archiving"),
             M("Last Archive Age", "s", "WAL and Archiving"),
             M("Archiving Failing", "flag", "WAL and Archiving")])],
        when=lambda node: node.settings.get("archive_mode", "off") != "off"),

    Query("wal_receiver", [
        Variant((10, 0),
            "SELECT (SELECT count(*) FROM pg_stat_wal_receiver WHERE status = 'streaming'),"
            " CASE WHEN pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() THEN 0"
            " ELSE floor(extract(epoch FROM now() - pg_last_xact_replay_timestamp()))::bigint END,"
            " round(pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn()) / 1048576.0, 2),"
            " (SELECT floor(extract(epoch FROM now() - max(last_msg_receipt_time)))::bigint"
            " FROM pg_stat_wal_receiver)",
            [M("WAL Receiver Connected", "flag", "Replication"),
             M("Replay Lag", "s", "Replication"),
             M("Replay Backlog", "MB", "Replication", float),
             M("Last WAL Message Age", "s", "Replication")]),
        Variant((9, 6),
            "SELECT (SELECT count(*) FROM pg_stat_wal_receiver WHERE status = 'streaming'),"
            " CASE WHEN pg_last_xlog_receive_location() = pg_last_xlog_replay_location() THEN 0"
            " ELSE floor(extract(epoch FROM now() - pg_last_xact_replay_timestamp()))::bigint END,"
            " round(pg_xlog_location_diff(pg_last_xlog_receive_location(),"
            " pg_last_xlog_replay_location()) / 1048576.0, 2),"
            " (SELECT floor(extract(epoch FROM now() - max(last_msg_receipt_time)))::bigint"
            " FROM pg_stat_wal_receiver)",
            [M("WAL Receiver Connected", "flag", "Replication"),
             M("Replay Lag", "s", "Replication"),
             M("Replay Backlog", "MB", "Replication", float),
             M("Last WAL Message Age", "s", "Replication")])],
        role=STANDBY),

    Query("slots", [
        Variant((10, 0),
            "SELECT count(*), count(*) FILTER (WHERE NOT active),"
            " round(coalesce(max(pg_wal_lsn_diff(CASE WHEN pg_is_in_recovery()"
            " THEN pg_last_wal_receive_lsn() ELSE pg_current_wal_lsn() END, restart_lsn)), 0)"
            " / 1048576.0, 2)"
            " FROM pg_replication_slots",
            [M("Replication Slots", "slots", "Replication"),
             M("Inactive Replication Slots", "slots", "Replication"),
             M("Max Slot Retained WAL", "MB", "Replication", float)])]),
]

RATES = [
    Rate("Transactions Per Sec", "Total Commits", "transactions/s", SUMMARY),
    Rate("Rollbacks Per Sec", "Total Rollbacks", "transactions/s", "Transactions and Sessions"),
    Rate("Rows Inserted Per Sec", "Total Rows Inserted", "rows/s", "DB and IO stats"),
    Rate("Rows Updated Per Sec", "Total Rows Updated", "rows/s", "DB and IO stats"),
    Rate("Rows Deleted Per Sec", "Total Rows Deleted", "rows/s", "DB and IO stats"),
    Rate("Rows Fetched Per Sec", "Total Rows Fetched", "rows/s", "DB and IO stats"),
    Rate("Rows Returned Per Sec", "Total Rows Returned", "rows/s", "DB and IO stats"),
    Rate("Block Reads Per Sec", "Total Block Reads", "blocks/s", "DB and IO stats"),
    Rate("Sequential Scans Per Sec", "Sequential Scans", "scans/s", "DB and IO stats"),
    Rate("Index Scans Per Sec", "Index Scans", "scans/s", "DB and IO stats"),
    Rate("Temp Data Per Sec", "Total Temp Data", "MB/s", "DB and IO stats"),
    Rate("WAL Generated Per Sec", "WAL Written", "MB/s", "WAL and Archiving"),
    Rate("New Deadlocks", "Total Deadlocks", "deadlocks", "Transactions and Sessions", delta=True),
    Rate("New Conflicts", "Total Conflicts", "conflicts", "Transactions and Sessions", delta=True),
    Rate("New Requested Checkpoints", "Checkpoints Req", "checkpoints", "BG Writer", delta=True),
    Rate("New Archive Failures", "Archive Failed Count", "files", "WAL and Archiving", delta=True),
    Rate("New Checksum Failures", "Checksum Failures", "failures", "DB and IO stats", delta=True),
]

# Metrics computed in derive_metrics() rather than read from a query.
DERIVED = [
    M("Node Role", tab="Activity", kind=str),
    M("Connection Utilization", "%", SUMMARY, float),
    M("Buffer Cache Hit Percent", "%", SUMMARY, float),
    M("Collection Time", "ms", "Plugin"),
    M("Failed Queries", "queries", "Plugin"),
]

TABLES = [
    Table("Stats_per_DB", "DB and IO stats", [((9, 6),
        "SELECT d.datname AS name, s.numbackends AS active_connections,"
        " round(CASE WHEN has_database_privilege(d.oid, 'CONNECT')"
        " THEN pg_database_size(d.oid) ELSE 0 END / 1048576.0, 2) AS size_in_mb,"
        " s.tup_inserted AS rows_inserted, s.tup_updated AS rows_updated,"
        " s.tup_deleted AS rows_deleted, s.tup_fetched AS rows_fetched,"
        " s.tup_returned AS rows_returned, s.blks_read AS block_reads, s.blks_hit AS block_hits,"
        " CASE WHEN s.blks_hit + s.blks_read = 0 THEN NULL"
        " ELSE round(100.0 * s.blks_hit / (s.blks_hit + s.blks_read), 2) END AS cache_hit_percent,"
        " s.deadlocks AS deadlocks, s.temp_files AS temp_files"
        " FROM pg_database d JOIN pg_stat_database s ON d.oid = s.datid"
        " WHERE d.datname NOT IN ('template0', 'template1')"
        " ORDER BY size_in_mb DESC, d.datname")],
        {"active_connections": "connections", "size_in_mb": "MB", "rows_inserted": "rows",
         "rows_updated": "rows", "rows_deleted": "rows", "rows_fetched": "rows",
         "rows_returned": "rows", "block_reads": "blocks", "block_hits": "blocks",
         "cache_hit_percent": "%", "deadlocks": "deadlocks", "temp_files": "files"}),

    Table("Tranasctions_and_Session_per_Database", "Transactions and Sessions", [
        ((14, 0),
         "SELECT datname AS name, xact_commit AS commits, xact_rollback AS rollbacks,"
         " conflicts, sessions, sessions_abandoned, sessions_fatal, sessions_killed,"
         " round(session_time::numeric, 2) AS session_time,"
         " round(active_time::numeric, 2) AS sessions_active_time,"
         " round(idle_in_transaction_time::numeric, 2) AS session_idle_in_transaction_time"
         " FROM pg_stat_database WHERE datname IS NOT NULL"
         " AND datname NOT IN ('template0', 'template1') ORDER BY xact_commit DESC, datname"),
        ((9, 6),
         "SELECT datname AS name, xact_commit AS commits, xact_rollback AS rollbacks, conflicts"
         " FROM pg_stat_database WHERE datname IS NOT NULL"
         " AND datname NOT IN ('template0', 'template1') ORDER BY xact_commit DESC, datname")],
        {"commits": "transactions", "rollbacks": "transactions", "conflicts": "conflicts",
         "sessions": "sessions", "sessions_abandoned": "sessions", "sessions_fatal": "sessions",
         "sessions_killed": "sessions", "session_time": "ms", "sessions_active_time": "ms",
         "session_idle_in_transaction_time": "ms"}),

    Table("Wait_Events", "Activity", [
        ((10, 0),
         "SELECT coalesce(wait_event_type, 'CPU') || ':' || coalesce(wait_event, 'running') AS name,"
         " count(*) AS sessions FROM pg_stat_activity WHERE state = 'active' AND " + _CLIENTS_10 +
         " GROUP BY 1 ORDER BY 2 DESC, 1"),
        ((9, 6),
         "SELECT coalesce(wait_event_type, 'CPU') || ':' || coalesce(wait_event, 'running') AS name,"
         " count(*) AS sessions FROM pg_stat_activity WHERE state = 'active' AND " + _CLIENTS_96 +
         " GROUP BY 1 ORDER BY 2 DESC, 1")],
        {"sessions": "sessions"}),

    Table("Replication_Slots", "Replication", [
        ((13, 0),
         "SELECT slot_name AS name, slot_type, active::int AS active,"
         " round(coalesce(pg_wal_lsn_diff(CASE WHEN pg_is_in_recovery()"
         " THEN pg_last_wal_receive_lsn() ELSE pg_current_wal_lsn() END, restart_lsn), 0)"
         " / 1048576.0, 2) AS retained_mb, coalesce(wal_status, 'unknown') AS wal_status"
         " FROM pg_replication_slots ORDER BY retained_mb DESC, slot_name"),
        ((10, 0),
         "SELECT slot_name AS name, slot_type, active::int AS active,"
         " round(coalesce(pg_wal_lsn_diff(CASE WHEN pg_is_in_recovery()"
         " THEN pg_last_wal_receive_lsn() ELSE pg_current_wal_lsn() END, restart_lsn), 0)"
         " / 1048576.0, 2) AS retained_mb"
         " FROM pg_replication_slots ORDER BY retained_mb DESC, slot_name")],
        {"slot_type": "", "active": "flag", "retained_mb": "MB", "wal_status": ""}),
]

# Tables kept for continuity with version 1 monitors.
CHILD_DISCOVERY = ["Tranasctions_and_Session_per_Database", "Stats_per_DB"]


def all_metric_defs():
    """Every metric the catalogue can emit, in a stable order, without duplicates."""
    seen = {}
    for q in QUERIES:
        for v in q.variants:
            for f in v.fields:
                seen.setdefault(f.name, f)
    for r in RATES:
        seen.setdefault(r.name, M(r.name, r.unit, r.tab, float))
    for d in DERIVED:
        seen.setdefault(d.name, d)
    return list(seen.values())


def build_tabs_and_units():
    """`tabs` and `units` generated from the catalogue, so they cannot drift apart."""
    tabs = {}
    for i, name in enumerate(TAB_ORDER, start=1):
        tabs[name] = {"order": str(i), "tablist": []}
    units = {}
    for t in TABLES:
        tabs[t.tab]["tablist"].append(t.name)
        units[t.name] = {c: u for c, u in t.units.items() if u}
    for m in all_metric_defs():
        if m.tab:
            tabs[m.tab]["tablist"].append(m.name)
        if m.kind is not str and m.unit:
            units[m.name] = m.unit
    return tabs, units


# =============================================================================
# 2. HELPERS
# =============================================================================

def clean_quotes(value):
    """cfg values may arrive wrapped in quotes (host="localhost")."""
    if value is None:
        return value
    s = str(value).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def parse_bool(value, default=True):
    if value is None or str(value).strip() == "":
        return default
    return str(clean_quotes(value)).strip().lower() in ("1", "true", "yes", "on")


def to_number(value, kind):
    """Converts a database value to int/float/str; returns None for NULL or non-finite."""
    if value is None:
        return None
    if kind is str:
        return str(value)[:MAX_STRING_CHARS]
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return int(round(num)) if kind is int else round(num, 4)


def table_cell(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value if not (isinstance(value, float) and (math.isnan(value) or math.isinf(value))) else None
    try:
        num = float(value)
        return int(num) if num.is_integer() and "." not in str(value) else round(num, 4)
    except (TypeError, ValueError):
        return str(value)[:MAX_STRING_CHARS]


def safe_row_name(value):
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", str(value))[:MAX_NAME_CHARS] or "unknown"


def scrub(text):
    """Keeps passwords and connection strings out of anything shown to the user."""
    text = re.sub(r"(password\s*=\s*)\S+", r"\1***", str(text), flags=re.IGNORECASE)
    return " ".join(text.split())


# =============================================================================
# 3. CONNECTION
# =============================================================================

class Node(object):
    """One PostgreSQL server connection with per-query failure isolation."""

    def __init__(self, host, port, user, password, dbname, sslmode="", sslrootcert="",
                 sslcert="", sslkey="", connect_timeout=CONNECT_TIMEOUT_S):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.dbname = dbname
        self.sslmode = sslmode
        self.sslrootcert = sslrootcert
        self.sslcert = sslcert
        self.sslkey = sslkey
        self.connect_timeout = connect_timeout
        self.conn = None
        self.version = (0, 0)
        self.is_recovery = False
        self.settings = {}
        self.identity = ""
        self.error = ""
        self.auth_failed = False
        self.failures = []

    @property
    def role(self):
        return ROLE_STANDBY if self.is_recovery else ROLE_PRIMARY

    def connect(self):
        kwargs = {
            "host": self.host, "port": self.port, "user": self.user, "dbname": self.dbname,
            "connect_timeout": self.connect_timeout,
            "application_name": "site24x7_postgres",
            "options": "-c statement_timeout=%d -c lock_timeout=2000"
                       " -c default_transaction_read_only=on" % STATEMENT_TIMEOUT_MS,
        }
        if self.password:
            kwargs["password"] = self.password
        for key in ("sslmode", "sslrootcert", "sslcert", "sslkey"):
            if getattr(self, key):
                kwargs[key] = getattr(self, key)
        try:
            self.conn = psycopg2.connect(**kwargs)
            self.conn.autocommit = True
        except Exception as e:
            text = str(e)
            self.auth_failed = getattr(e, "pgcode", None) in ("28000", "28P01") or \
                "authentication failed" in text.lower()
            self.error = scrub(text)
            return False
        num = getattr(self.conn, "server_version", 0) or 0
        # 10+: 160004 -> (16, 4); before 10: 90624 -> (9, 6)
        self.version = (num // 10000, num % 10000) if num >= 100000 else (num // 10000, (num // 100) % 100)
        row = self.query_one(
            "SELECT pg_is_in_recovery(), current_setting('archive_mode'),"
            " pg_postmaster_start_time()::text")
        if row:
            self.is_recovery = bool(row[0])
            self.settings["archive_mode"] = row[1]
            self.identity = "%s:%s|%s" % (self.host, self.port, row[2])
        return True

    def query_all(self, sql):
        if self.conn is None:
            return None
        cur = None
        try:
            cur = self.conn.cursor()
            cur.execute("/* site24x7 */ " + sql)
            return cur.fetchall()
        except Exception as e:
            self.failures.append(scrub(str(e).splitlines()[0] if str(e) else type(e).__name__))
            return None
        finally:
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass

    def query_one(self, sql):
        rows = self.query_all(sql)
        if rows is None:
            return None
        return rows[0] if rows else ()

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None


# =============================================================================
# 4. STATE (previous counters, for rates)
# =============================================================================

def state_path(host, port, dbname):
    key = "%s:%s/%s" % (host, port, dbname)
    return os.path.join(STATE_DIR, hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".json")


def load_state(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


# =============================================================================
# 5. COLLECTION
# =============================================================================

def applies(entry, node):
    if entry.role == PRIMARY and node.is_recovery:
        return False
    if entry.role == STANDBY and not node.is_recovery:
        return False
    return entry.when is None or bool(entry.when(node))


def collect_metrics(node, deadline):
    """Runs every applicable single-row query; returns {metric: value}."""
    out = {}
    for q in QUERIES:
        if time.time() > deadline:
            node.failures.append("cycle time budget exhausted before '%s'" % q.key)
            break
        if not applies(q, node):
            continue
        variant = q.pick(node.version)
        if variant is None:
            continue
        row = node.query_one(variant.sql)
        if not row:
            continue
        for field, value in zip(variant.fields, row):
            num = to_number(value, field.kind)
            if num is not None:
                out[field.name] = num
    return out


def collect_tables(node, deadline):
    """Runs every applicable table query; returns {table: [rows]}, at most MAX_ROWS each."""
    out = {}
    for t in TABLES:
        if time.time() > deadline:
            node.failures.append("cycle time budget exhausted before '%s'" % t.name)
            break
        if not applies(t, node):
            continue
        sql = t.pick(node.version)
        if sql is None or node.conn is None:
            continue
        cur = None
        try:
            cur = node.conn.cursor()
            cur.execute("/* site24x7 */ " + sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        except Exception as e:
            node.failures.append(scrub(str(e).splitlines()[0] if str(e) else type(e).__name__))
            continue
        finally:
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass
        table_rows = []
        seen = set()
        for r in rows:
            row = {}
            for c, v in zip(cols, r):
                if c == "name":
                    row["name"] = safe_row_name(v)
                else:
                    cell = table_cell(v)
                    if cell is not None:
                        row[c] = cell
            if row.get("name") and row["name"] not in seen:
                seen.add(row["name"])
                table_rows.append(row)
            if len(table_rows) >= MAX_ROWS:
                break
        out[t.name] = table_rows
    return out


def compute_rates(metrics, prev, now, identity):
    """Rates and deltas from the previous sample of the same server process."""
    out = {}
    prev_counters = prev.get("counters") or {}
    dt = now - float(prev.get("ts") or 0)
    if prev.get("identity") != identity or not (RATE_MIN_INTERVAL_S <= dt <= RATE_MAX_INTERVAL_S):
        return out
    for r in RATES:
        cur = metrics.get(r.source)
        old = prev_counters.get(r.source)
        if cur is None or old is None:
            continue
        diff = float(cur) - float(old)
        if diff < 0:          # statistics were reset; skip one poll
            continue
        out[r.name] = int(diff) if r.delta else round(diff * r.scale / dt, 2)
    return out


def derive_metrics(node, metrics):
    out = {"Node Role": node.role}
    conns, max_conns = metrics.get("Active Connections"), metrics.get("Max Connections")
    if conns is not None and max_conns:
        out["Connection Utilization"] = round(100.0 * conns / max_conns, 2)
    hits, reads = metrics.get("Total Block Hits"), metrics.get("Total Block Reads")
    if hits is not None and reads is not None and hits + reads > 0:
        out["Buffer Cache Hit Percent"] = round(100.0 * hits / (hits + reads), 2)
    return out


# =============================================================================
# 6. OUTPUT
# =============================================================================

def base_payload(args):
    tabs, units = build_tabs_and_units()
    return {
        "plugin_version": args.get("plugin_version", PLUGIN_VERSION),
        "heartbeat_required": args.get("heartbeat", HEARTBEAT),
        "status": 1,
        "tabs": tabs,
        "units": units,
        "s247config": {"childdiscovery": list(CHILD_DISCOVERY)},
    }


def finalize(payload):
    """Drops tab and unit entries for anything not emitted this poll."""
    emitted = {k for k in payload if k not in RESERVED_KEYS}
    for tab in payload.get("tabs", {}).values():
        tab["tablist"] = [m for m in tab["tablist"] if m in emitted]
    payload["tabs"] = {k: v for k, v in payload.get("tabs", {}).items() if v["tablist"]}
    payload["units"] = {k: v for k, v in payload.get("units", {}).items() if k in emitted}
    if "msg" in payload:
        payload["msg"] = str(payload["msg"])[:MAX_MSG_CHARS]
    return payload


def validate_output(payload):
    """Site24x7 platform limits, checked on every poll. Returns a list of violations."""
    problems = []
    if payload.get("status") not in (0, 1):
        problems.append("status must be 0 or 1")
    tables = {k: v for k, v in payload.items()
              if k not in RESERVED_KEYS and isinstance(v, list)}
    metrics = {k: v for k, v in payload.items()
               if k not in RESERVED_KEYS and not isinstance(v, list)}
    if len(tables) > MAX_TABLES:
        problems.append("%d tables > %d" % (len(tables), MAX_TABLES))
    if len(metrics) > MAX_METRICS:
        problems.append("%d metrics > %d" % (len(metrics), MAX_METRICS))
    for name, rows in tables.items():
        if len(rows) > MAX_ROWS:
            problems.append("%s: %d rows > %d" % (name, len(rows), MAX_ROWS))
        for row in rows:
            if "name" not in row:
                problems.append("%s: row without name" % name)
            if len(row) > MAX_COLUMNS:
                problems.append("%s: %d columns > %d" % (name, len(row), MAX_COLUMNS))
            strings = [c for c, v in row.items() if isinstance(v, str)]
            if len(strings) > MAX_STRING_COLS:
                problems.append("%s: %d string columns > %d" % (name, len(strings), MAX_STRING_COLS))
            for c, v in row.items():
                limit = MAX_NAME_CHARS if c == "name" else MAX_STRING_CHARS
                if isinstance(v, str) and len(v) > limit:
                    problems.append("%s.%s longer than %d" % (name, c, limit))
    for name, value in metrics.items():
        if isinstance(value, str) and len(value) > MAX_STRING_CHARS:
            problems.append("%s longer than %d" % (name, MAX_STRING_CHARS))
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            problems.append("%s is not finite" % name)
    units = payload.get("units", {})
    for tab, content in payload.get("tabs", {}).items():
        for item in content.get("tablist", []):
            if item not in payload:
                problems.append("tab %s lists %s, which is not emitted" % (tab, item))
            elif not isinstance(payload[item], (str, list)) and item not in units:
                problems.append("%s has no unit" % item)
    return problems


def down(payload, message):
    payload["status"] = 0
    payload["msg"] = message
    return finalize(payload)


# =============================================================================
# 7. ENTRY POINTS
# =============================================================================

def resolve_args(param):
    """Normalises cfg/CLI parameters. Unknown keys are ignored."""
    p = {k: clean_quotes(v) for k, v in (param or {}).items()}
    try:
        port = int(p.get("port") or 5432)
    except ValueError:
        port = 5432
    try:
        timeout = int(p.get("timeout") or CONNECT_TIMEOUT_S)
    except ValueError:
        timeout = CONNECT_TIMEOUT_S
    try:
        plugin_version = int(p.get("plugin_version") or PLUGIN_VERSION)
    except ValueError:
        plugin_version = PLUGIN_VERSION
    password = p.get("password") or ""
    return {
        "host": p.get("host") or "localhost",
        "port": port if 0 < port < 65536 else 5432,
        "username": p.get("username") or "postgres",
        "password": "" if password == "None" else password,
        "db": p.get("db") or "postgres",
        "sslmode": p.get("sslmode") or "",
        "sslrootcert": p.get("sslrootcert") or "",
        "sslcert": p.get("sslcert") or "",
        "sslkey": p.get("sslkey") or "",
        "timeout": min(max(timeout, 1), 30),
        "plugin_version": plugin_version,
        "heartbeat": parse_bool(p.get("heartbeat"), HEARTBEAT),
    }


def run(param):
    """Collects one poll. `param` is the cfg section as a dict; returns the payload."""
    t0 = time.time()
    args = resolve_args(param)
    payload = base_payload(args)
    if not HAVE_PSYCOPG2:
        return down(payload, DRIVER_MISSING_MSG)

    node = Node(args["host"], args["port"], args["username"], args["password"], args["db"],
                args["sslmode"], args["sslrootcert"], args["sslcert"], args["sslkey"],
                args["timeout"])
    if not node.connect():
        reason = "authentication failed for user %s" % args["username"] if node.auth_failed \
            else "cannot connect to %s:%s (%s)" % (args["host"], args["port"], node.error)
        return down(payload, reason)
    try:
        if node.version < VERSION_FLOOR:
            return down(payload, "PostgreSQL %d.%d is not supported; version %d.%d or later is required"
                        % (node.version + VERSION_FLOOR))
        deadline = t0 + CYCLE_BUDGET_S
        metrics = collect_metrics(node, deadline)
        tables = collect_tables(node, deadline)
    finally:
        node.close()

    path = state_path(args["host"], args["port"], args["db"])
    prev = load_state(path)
    metrics.update(compute_rates(metrics, prev, t0, node.identity))
    metrics.update(derive_metrics(node, metrics))
    save_state(path, {
        "ts": t0, "identity": node.identity,
        "counters": {r.source: metrics[r.source] for r in RATES if r.source in metrics},
    })

    metrics["Failed Queries"] = len(node.failures)
    metrics["Collection Time"] = int((time.time() - t0) * 1000)
    payload.update(metrics)
    payload.update(tables)
    if node.failures:
        payload["msg"] = "%d queries failed: %s" % (len(node.failures), node.failures[0])
    payload = finalize(payload)
    problems = validate_output(payload)
    if problems:
        note = "schema: " + problems[0]
        payload["msg"] = (payload.get("msg", "") + " | " + note).strip(" |")[:MAX_MSG_CHARS]
    return payload


def parse_cli(argv=None):
    parser = argparse.ArgumentParser(description="Site24x7 PostgreSQL plugin")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default="5432")
    parser.add_argument("--username", default="postgres")
    parser.add_argument("--password", default="")
    parser.add_argument("--db", default="postgres")
    parser.add_argument("--sslmode", default="")
    parser.add_argument("--sslrootcert", default="")
    parser.add_argument("--sslcert", default="")
    parser.add_argument("--sslkey", default="")
    parser.add_argument("--timeout", default=str(CONNECT_TIMEOUT_S))
    parser.add_argument("--plugin_version", default=str(PLUGIN_VERSION))
    parser.add_argument("--heartbeat", default="true")
    return vars(parser.parse_args(argv))


if __name__ == "__main__":
    try:
        result = run(parse_cli())
    except Exception as exc:  # the agent must always receive valid JSON
        result = {"plugin_version": PLUGIN_VERSION, "heartbeat_required": HEARTBEAT,
                  "status": 0, "msg": scrub("plugin error: %s" % exc)[:MAX_MSG_CHARS]}
    print(json.dumps(result, indent=4, sort_keys=True))
