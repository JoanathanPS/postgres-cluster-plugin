#!/usr/bin/python3

### This plugin is used for monitoring PostgreSQL Cluster
### For monitoring the health, replication and performance metrics of all the nodes of your PostgreSQL cluster using Site24x7 Server Monitoring Plugins.
###
### Language : Python
### Tested with Patroni, repmgr, Stolon, Citus, pg_auto_failover, CloudNativePG and multi-master clusters (Windows agent verified with Patroni)

import os
import sys
import json
import time
import copy
import re
import urllib.request
import urllib.error
import concurrent.futures
from collections import OrderedDict

def safe_name(raw):
    return re.sub(r'[^A-Za-z0-9]', '', str(raw))


class PluginError(Exception):
    """Base exception for postgres_cluster plugin."""
    pass

class ConfigError(PluginError):
    """Configuration missing or invalid."""
    pass

class AuthError(PluginError):
    """PostgreSQL or Patroni authentication failure."""
    pass

class UnreachableError(PluginError):
    """Host or port unreachable / connection refused / timeout."""
    pass

class DiscoveryError(PluginError):
    """Cluster discovery failed (e.g. seed down with no cache)."""
    pass

class UnsupportedClusterError(PluginError):
    """Cluster type detected but unsupported by this plugin version."""
    def __init__(self, cluster_type, evidence=""):
        super().__init__(f"Detected {cluster_type}: not supported by this plugin version")
        self.cluster_type = cluster_type
        self.evidence = evidence

class MetricUnavailable(PluginError):
    """Specific metric query failed due to permissions or missing views."""
    pass

def _table_readable(cur, qualified):
    """True only if the table exists and the current user may read it, so querying it can never raise a server-side error."""
    try:
        cur.execute("SELECT CASE WHEN to_regclass(%s) IS NULL THEN false ELSE has_table_privilege(to_regclass(%s), 'SELECT') END;", (qualified, qualified))
        r = cur.fetchone()
        return bool(r and r[0])
    except Exception:
        return False


def _column_readable(cur, qualified, column):
    """Same as _table_readable for one column (pg_subscription.subconninfo is readable by superusers or after a GRANT only)."""
    try:
        cur.execute("SELECT CASE WHEN to_regclass(%s) IS NULL THEN false ELSE has_column_privilege(to_regclass(%s), %s, 'SELECT') END;", (qualified, qualified, column))
        r = cur.fetchone()
        return bool(r and r[0])
    except Exception:
        return False


def check_for_pooler(conn):
    """Detects if the endpoint is a connection pooler like PgBouncer.
    Raises ConfigError if a pooler is detected."""
    try:
        with conn.cursor() as cur:
            #A real PostgreSQL answers this, so we stop here and no failing command is written to its log
            try:
                cur.execute("SELECT current_setting('server_version_num');")
                r0 = cur.fetchone()
                if r0 and str(r0[0]).strip().isdigit():
                    return
            except Exception:
                pass
            try:
                cur.execute("SHOW VERSION;")
                row = cur.fetchone()
                if row and "pgbouncer" in str(row[0]).lower():
                    raise ConfigError("Seed looks like a connection pooler: point nodes at a PostgreSQL node")
            except ConfigError:
                raise
            except Exception as e:
                err_str = str(e).lower()
                if "show help" in err_str or "pgbouncer" in err_str:
                    raise ConfigError("Seed looks like a connection pooler: point nodes at a PostgreSQL node")

            try:
                cur.execute("SELECT pg_is_in_recovery();")
            except Exception as e:
                err_str = str(e).lower()
                if "show help" in err_str or "invalid command" in err_str:
                    raise ConfigError("Seed looks like a connection pooler: point nodes at a PostgreSQL node")
    except ConfigError:
        raise
    except Exception:
        pass

def classify(e):
    """Classifies an exception into typed PluginError hierarchy."""
    try:
        import psycopg2
        if isinstance(e, psycopg2.OperationalError):
            msg = str(e).lower()
            if "authentication failed" in msg or "password authentication" in msg or "pg_hba.conf" in msg:
                return AuthError(str(e))
            return UnreachableError(str(e))
        pgcode = getattr(e, 'pgcode', None)
        if pgcode in ('42501', '42P01', '42883', '42703', '57014'):
            return MetricUnavailable(str(e))
        name = type(e).__name__
        if name in ('InsufficientPrivilege', 'UndefinedTable', 'UndefinedFunction', 'UndefinedColumn', 'QueryCanceled'):
            return MetricUnavailable(str(e))
    except ImportError:
        pass
    if isinstance(e, PluginError):
        return e
    return e

SUPPORTED_CLUSTER_TYPES = {
    "Patroni",
    "repmgr",
    "streaming replication (no HA manager detected)",
    "standalone",
    "Multi-Master (native logical)",
    "Multi-Master (pglogical)",
}

def parse_address_map(raw_map):
    mapping = {}
    if not raw_map:
        return mapping
    for entry in str(raw_map).split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" in entry:
            src, dst = entry.split("=", 1)
        elif "->" in entry:
            src, dst = entry.split("->", 1)
        else:
            continue
        src = src.strip()
        dst = dst.strip()
        mapping[src.lower()] = dst
        if ":" in src:
            shost, sport = src.split(":", 1)
            try:
                mapping[(shost.strip().lower(), int(sport.strip()))] = dst
            except ValueError:
                pass
    return mapping

def map_address(host, port, address_map):
    if not address_map:
        return host, int(port)
    h_norm = str(host).strip().lower()
    p_int = int(port)
    if (h_norm, p_int) in address_map:
        target = address_map[(h_norm, p_int)]
        if ":" in target:
            th, tp = target.split(":", 1)
            return th.strip(), int(tp.strip())
        return target.strip(), p_int
    key_str = f"{h_norm}:{p_int}"
    if key_str in address_map:
        target = address_map[key_str]
        if ":" in target:
            th, tp = target.split(":", 1)
            return th.strip(), int(tp.strip())
        return target.strip(), p_int
    if h_norm in address_map:
        target = address_map[h_norm]
        if ":" in target:
            th, tp = target.split(":", 1)
            return th.strip(), int(tp.strip())
        return target.strip(), p_int
    return host, p_int

def parse_conninfo_hostport(conninfo):
    if not conninfo:
        return None, None
    host, port = None, None
    if "://" in conninfo:
        from urllib.parse import urlparse
        try:
            u = urlparse(conninfo)
            return u.hostname, u.port
        except Exception:
            pass
    for token in conninfo.split():
        if "=" in token:
            k, v = token.split("=", 1)
            k = k.strip().lower()
            v = v.strip().strip("'\"")
            if k == "host":
                host = v
            elif k == "port":
                try:
                    port = int(v)
                except ValueError:
                    pass
    return host, port


#These settings come from postgres_cluster.cfg. There are no built-in defaults for the first four.
NODES = ''                        #Change the node address here: host:port[:patroni_port], one address is enough
USERNAME = ''                     #Change the username here
PASSWORD = ''                     #Change the authentication method
DB = ''                           #Change the DB name here
PATRONI_PORT = ''                 #Change the Patroni REST port here (leave empty if it is not a Patroni cluster)
ADDRESS_MAP = ''                  #Optional, for Docker/NAT: internal_host:port=reachable_host:port, comma separated
CLUSTER_TYPE = 'auto'             #auto detects the cluster type, or write the type here
DISCOVER = 'auto'                 #auto finds the other nodes from the address above, off monitors only the nodes listed

#Limits of this plugin, change them only if you know why
DISCOVERY_DEADLINE_S = 2.0        #Seconds allowed for finding the nodes of the cluster
MAX_NODES = 25                    #Site24x7 allows at most 25 rows in a table
CONNECT_TIMEOUT = 2               #Seconds to wait when connecting to a node
STATEMENT_TIMEOUT_MS = 3000       #Milliseconds a single query may run
NODE_COLLECT_DEADLINE_S = 5.0     #Seconds allowed for collecting from all the nodes

#Alert levels used in the health reason
FAILOVER_WARN_SECONDS = 900       #A failover newer than this many seconds is reported
SLOT_WARN_BYTES = 1073741824      #Replication slot retaining more WAL than this is a warning
SLOT_CRITICAL_BYTES = 10737418240 #Replication slot retaining more WAL than this is critical

#if any impacting changes to this plugin kindly increment the plugin version here.
PLUGIN_VERSION = 2

#Setting this to true will alert you when there is a communication problem while posting plugin data to server
HEARTBEAT = True

#Tabs shown in the console. A numeric metric that is in no tab is charted on the Summary page
tabs = {
    "tabs": {
        "Cluster": {"order": "1", "tablist": [
            "Cluster_Info", "Cluster_Nodes", "Nodes Total", "Primary Count", "Primary Timeline",
            "No Primary Flag", "Split Brain Flag", "Timeline Mismatch Flag", "Server PID",
            "Seconds Since Last Failover", "Failovers Last 24h", "Last Failover To", "Last Failover Timeline"]},
        "Replication": {"order": "2", "tablist": [
            "Replication_Links", "Replication_Slots", "Standbys Expected", "Standbys Streaming",
            "Standby Disconnect Flag", "Sync Standby Count", "Cascading Standby Count",
            "Max Replay Backlog", "Max Replay Delay", "Replication Slots Total",
            "Replication Slots Active", "Replication Slots Inactive", "Max Slot Lag Bytes",
            "Slot Wal Status Risk",
            "Logical Replication In Use", "Mesh Links Declared", "Mesh Links Active", "Mesh Disconnect Flag", "Max Logical Lag Bytes", "Max Logical Lag Seconds", "Subscription Apply Errors", "Subscription Conflicts"]},
        "Node Performance": {"order": "3", "tablist": [
            "Node_IO", "Node_Checkpoints", "Stats_per_DB", "Total Rows Inserted", "Total Rows Updated",
            "Total Rows Deleted", "Total Rows Fetched", "Total Rows Returned", "Total Block Reads",
            "Total Block Hits", "Checkpoints Timed", "Checkpoints Req", "Checkpoint Write Time",
            "Checkpoint Sync Time", "Buffers Checkpoint", "Buffers Clean", "Maxwritten Clean",
            "Buffers Backend", "Buffers Backend Fsync", "Buffers Alloc", "Dead Tuples"]},
        "Transactions and Sessions": {"order": "4", "tablist": [
            "Node_Activity", "Node_Transactions", "Tranasctions_and_Session_per_Database",
            "Total Commits", "Total Rollbacks", "Total Conflicts", "Total Sessions",
            "Total Sessions Abandoned", "Total Sessions Fatal", "Total Sessions Killed",
            "Transactions Open", "Transactions Idle In Transaction", "Connection Utilization Percent",
            "Oldest Transaction ID Age", "Oldest Running Transaction Age"]},
        "WAL and Recovery": {"order": "5", "tablist": [
            "WAL Write Position", "WAL Insert Position", "WAL Flush Position", "WAL Files Count",
            "WAL Total Size", "Archive Mode", "Archive Status Success", "Archive Status Failed",
            "Archive Ready Files Count", "Last Archived WAL File", "Recovery Conflicts Total",
            "Conflicts Tablespace", "Conflicts Lock", "Conflicts Snapshot", "Conflicts Buffer Pin",
            "Conflicts Deadlock"]}
    }
}
#Units of the metrics and of the table columns
units = {
    # Cluster tab
    "Cluster Health": "status",
    "Nodes Total": "nodes",
    "Server PID": "pid",
    "Nodes Up": "nodes",
    "Primary Count": "nodes",
    "No Primary Flag": "flag",
    "Split Brain Flag": "flag",
    "Primary Timeline": "timeline",
    "Timeline Mismatch Flag": "flag",
    "Seconds Since Last Failover": "s",
    "Failovers Last 24h": "failovers",
    "Last Failover Timeline": "timeline",

    # Replication tab
    "Standbys Expected": "standbys",
    "Standbys Streaming": "standbys",
    "Standby Disconnect Flag": "flag",
    "Sync Standby Count": "standbys",
    "Cascading Standby Count": "standbys",
    "Max Replay Backlog": "bytes",
    "Max Replay Delay": "s",
    "Replication Slots Total": "slots",
    "Replication Slots Active": "slots",
    "Replication Slots Inactive": "slots",
    "Max Slot Lag Bytes": "bytes",
    "Slot Wal Status Risk": "risk",
    "Logical Replication In Use": "flag",
    "Mesh Links Declared": "links",
    "Mesh Links Active": "links",
    "Mesh Disconnect Flag": "flag",
    "Max Logical Lag Bytes": "bytes",
    "Max Logical Lag Seconds": "s",
    "Subscription Apply Errors": "errors",
    "Subscription Conflicts": "conflicts",
    "WAL Write Position": "MB",
    "WAL Insert Position": "MB",
    "WAL Flush Position": "MB",
    "WAL Files Count": "files",
    "WAL Total Size": "MB",
    "Archive Status Success": "files",
    "Archive Status Failed": "files",
    "Archive Ready Files Count": "files",
    "Recovery Conflicts Total": "conflicts",
    "Conflicts Tablespace": "conflicts",
    "Conflicts Lock": "conflicts",
    "Conflicts Snapshot": "conflicts",
    "Conflicts Buffer Pin": "conflicts",
    "Conflicts Deadlock": "conflicts",
    "Oldest Running Transaction Age": "s",

    # Node Performance tab
    "Total Rows Inserted": "rows",
    "Total Rows Updated": "rows",
    "Total Rows Deleted": "rows",
    "Total Rows Fetched": "rows",
    "Total Rows Returned": "rows",
    "Total Block Reads": "blocks",
    "Total Block Hits": "blocks",
    "Heap Blocks Read": "blocks",
    "Heap Blocks Hit": "blocks",
    "Cache Hit Ratio": "ratio",
    "Index Scans": "scans",
    "Index Rows Read": "rows",
    "Index Rows Fetched": "rows",
    "Checkpoints Timed": "checkpoints",
    "Checkpoints Req": "checkpoints",
    "Checkpoint Write Time": "ms",
    "Checkpoint Sync Time": "ms",
    "Buffers Checkpoint": "buffers",
    "Buffers Clean": "buffers",
    "Maxwritten Clean": "buffers",
    "Buffers Backend": "buffers",
    "Buffers Backend Fsync": "calls",
    "Buffers Alloc": "buffers",
    "Dead Tuples": "tuples",

    # Transactions and Sessions tab
    "Active Connections": "connections",
    "Max Connections": "connections",
    "Connection Utilization Percent": "%",
    "Active Queries": "queries",
    "Active Waiting Queries": "queries",
    "Locks Count": "locks",
    "Oldest Transaction ID Age": "xids",
    "Total Commits": "transactions",
    "Total Rollbacks": "transactions",
    "Total Conflicts": "conflicts",
    "Transactions Open": "transactions",
    "Transactions Idle In Transaction": "transactions",
    "Total Sessions": "sessions",
    "Total Sessions Abandoned": "sessions",
    "Total Sessions Fatal": "sessions",
    "Total Sessions Killed": "sessions",
    "Uptime": "s",
    "Table Count": "tables",
    "Database Count": "databases",

    # Nested Table Units
    "Cluster_Info": {
        "nodes_total": "nodes",
        "nodes_up": "nodes",
        "primary_timeline": "timeline",
        "status": "status"
    },
    "Cluster_Nodes": {
        "is_primary": "flag",
        "timeline": "timeline",
        "response_time_ms": "ms",
        "connections": "connections",
        "replay_backlog_bytes": "bytes",
        "replay_delay_s": "s",
        "monitored": "flag",
        "status": "status"
    },
    "Replication_Links": {
        "replay_lag_bytes": "bytes",
        "write_lag_bytes": "bytes",
        "flush_lag_bytes": "bytes",
        "replay_lag_s": "s",
        "is_sync": "flag",
        "active": "flag",
        "status": "status"
    },
    "Replication_Slots": {
        "active": "flag",
        "wal_retained_bytes": "bytes",
        "status": "status"
    },
    "Node_IO": {
        "rows_inserted": "rows",
        "rows_updated": "rows",
        "rows_deleted": "rows",
        "rows_fetched": "rows",
        "rows_returned": "rows",
        "block_reads": "blocks",
        "block_hits": "blocks",
        "heap_blocks_read": "blocks",
        "heap_blocks_hit": "blocks",
        "cache_hit_ratio": "ratio",
        "index_scans": "scans",
        "index_rows_read": "rows",
        "index_rows_fetched": "rows",
        "status": "status"
    },
    "Node_Checkpoints": {
        "checkpoints_timed": "checkpoints",
        "checkpoints_req": "checkpoints",
        "checkpoint_write_time": "ms",
        "checkpoint_sync_time": "ms",
        "buffers_checkpoint": "buffers",
        "buffers_clean": "buffers",
        "maxwritten_clean": "buffers",
        "buffers_backend": "buffers",
        "buffers_backend_fsync": "calls",
        "buffers_alloc": "buffers",
        "status": "status"
    },
    "Node_Activity": {
        "active_connections": "connections",
        "max_connections": "connections",
        "active_queries": "queries",
        "active_waiting_queries": "queries",
        "transactions_open": "transactions",
        "transactions_idle_in_transaction": "transactions",
        "locks_count": "locks",
        "oldest_xact_age_s": "s",
        "uptime": "s",
        "status": "status"
    },
    "Node_Transactions": {
        "commits": "transactions",
        "rollbacks": "transactions",
        "conflicts": "conflicts",
        "sessions": "sessions",
        "sessions_abandoned": "sessions",
        "sessions_fatal": "sessions",
        "sessions_killed": "sessions",
        "status": "status"
    }
}


def get_standalone_queries(major_version, middle_version=0):
    """
    Returns the exact SQL queries used by standalone postgres.py for parameter parity.
    Matches postgres.py query definitions character-for-character.
    """
    #Add your queries here
    queries = {
        'table_count': "SELECT COUNT(*) AS table_count FROM pg_stat_all_tables;",
        'transactions_open': "SELECT count(*) as transactions_open FROM pg_stat_activity WHERE xact_start IS NOT NULL;",
        'version': "SHOW server_version;",
        'locks_count': "SELECT COUNT(*) as locks_count FROM pg_locks;",
        'max_conn': "select setting::int max_connections from pg_settings where name=$$max_connections$$;",
        'db_stats': "SELECT sum(numbackends) as active_connections, sum(xact_commit) as total_commits, sum(xact_rollback) as total_rollbacks, sum(conflicts) as total_conflicts FROM pg_stat_database;",
        'io_stats': "SELECT sum(tup_inserted) as total_rows_inserted, sum(tup_updated) as total_rows_updated ,sum(tup_deleted) as total_rows_deleted, sum(tup_fetched) as total_rows_fetched ,sum(tup_returned) as total_rows_returned,sum(blks_read) as total_block_reads , sum(blks_hit) as total_block_hits FROM pg_stat_database;",
        'idx_stats': "SELECT sum(idx_scan) as index_scans,sum(idx_tup_read) as index_rows_read, sum(idx_tup_fetch) as index_rows_fetched FROM pg_stat_user_indexes;",
        'uptime': "SELECT FLOOR(EXTRACT(EPOCH FROM current_timestamp - pg_postmaster_start_time())) as uptime;",
        'no of databases': "SELECT COUNT(*) AS database_count FROM pg_database WHERE datname <> 'template0' AND datname <> 'template1';",
        'heap_and_cache': "SELECT sum(heap_blks_read) as heap_blocks_read, sum(heap_blks_hit)  as heap_blocks_hit, CASE WHEN (sum(heap_blks_hit) + sum(heap_blks_read)) = 0 THEN 0 ELSE sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) END as cache_hit_ratio FROM pg_statio_user_tables;",
    }
    if (major_version >= 9 and middle_version >= 2) or (major_version >= 10):
        queries['active_queries'] = "SELECT count(*) - ( SELECT count(*) FROM pg_stat_activity WHERE state = 'idle' ) as active_queries FROM pg_stat_activity;"
        queries['active_waiting_queries'] = "SELECT count(*) as active_waiting_queries FROM pg_stat_activity WHERE state = 'active' AND wait_event IS NOT NULL;"
        queries['transacttions_idle'] = "SELECT COUNT(*) as transactions_idle_in_transaction FROM pg_stat_activity WHERE state = 'idle in transaction';"
    else:
        queries['active_queries'] = "SELECT count(*) - ( SELECT count(*) FROM pg_stat_activity WHERE current_query = '<IDLE>' ) as active_queries FROM pg_stat_activity;"
        queries['transacttions_idle'] = "SELECT COUNT(*) as transactions_idle_in_transaction FROM pg_stat_activity WHERE state = '<IDLE> in transaction';"

    if major_version >= 17:
        queries['checkpoints'] = "SELECT num_timed, num_requested, write_time, sync_time, buffers_written FROM pg_stat_checkpointer;"
        queries['bg_stats'] = "SELECT buffers_clean, maxwritten_clean, 0 as buffers_backend, 0 as buffers_backend_fsync, buffers_alloc FROM pg_stat_bgwriter;"
    else:
        queries['checkpoints'] = "SELECT checkpoints_timed, checkpoints_req, checkpoint_write_time, checkpoint_sync_time, buffers_checkpoint FROM pg_stat_bgwriter;"
        queries['bg_stats'] = "SELECT buffers_clean, maxwritten_clean, buffers_backend, buffers_backend_fsync, buffers_alloc FROM pg_stat_bgwriter;"

    queries['per_db_stats'] = "SELECT d.datname AS name, s.numbackends as active_connections, ROUND(pg_database_size(d.datname) / 1024 / 1024,2) AS size_in_mb, tup_inserted as rows_inserted, tup_updated as rows_updated, tup_deleted as rows_deleted, tup_fetched as rows_fetched, tup_returned as rows_returned, blks_read as block_reads, blks_hit as block_hits FROM pg_database d JOIN pg_stat_database s ON d.oid = s.datid;"
    if major_version >= 14:
        queries['per_db_trans'] = "SELECT datname as name, xact_commit as commits, xact_rollback as rollbacks, conflicts, sessions, sessions_abandoned, sessions_fatal, sessions_killed, session_time, active_time as sessions_active_time, idle_in_transaction_time as session_idle_in_transaction_time FROM pg_stat_database WHERE datname IS NOT NULL;"
    else:
        queries['per_db_trans'] = "SELECT datname as name, xact_commit as commits, xact_rollback as rollbacks, conflicts FROM pg_stat_database WHERE datname IS NOT NULL;"

    if major_version >= 14:
        queries['session'] = "SELECT SUM(sessions) as total_sessions, SUM(sessions_abandoned) as total_sessions_abandoned, SUM(sessions_fatal) as total_sessions_fatal, SUM(sessions_killed) as total_sessions_killed FROM pg_stat_database;"

    #Please add any new query designed above to this dictionary also with an appropriate key name
    return queries


def evaluate_cluster_health(
    nodes_total, nodes_up, primary_count, no_primary_flag, split_brain_flag,
    standbys_expected, standbys_streaming, max_replay_delay_s, max_replay_backlog,
    slots_inactive, timeline_mismatch_flag, delay_threshold_s=60.0, backlog_threshold_bytes=104857600,
    cluster_type=None, mesh_disconnect_flag=0, subscription_apply_errors=0,
    slots_info=None, slot_warn_bytes=1073741824, slot_critical_bytes=10737418240,
    seconds_since_last_failover=None, last_failover_to=None, last_failover_timeline=None, failover_warn_seconds=900
):
    """
    Pure health evaluation function for unit testing and live monitoring.
    Returns (status_code: int, reason: str < 100 chars).
      0 = healthy
      1 = degraded
      2 = critical
    Rule precedence:
      Critical: No primary, split-brain (except multi-master), zero streaming standbys,
                inactive slot > slot_critical_bytes or wal_status lost.
      Degraded: Node down, standby disconnected, lag over threshold, inactive slot,
                slot > slot_warn_bytes, timeline mismatch, recent failover within window.
      Healthy: All criteria satisfied.
    """
    is_multimaster = False
    if cluster_type:
        c_lower = str(cluster_type).lower()
        if "multi-master" in c_lower or "multimaster" in c_lower or "active-active" in c_lower or "bdr" in c_lower or "citus" in c_lower:
            is_multimaster = True

    # Multi-Master Health Rules
    if is_multimaster:
        if nodes_up == 0:
            return 2, "Critical: No active master nodes reachable"
        # Check slot critical in multi-master
        if slots_info:
            for s in slots_info:
                if not s.get("active"):
                    ret = s.get("wal_retained_bytes", 0) or 0
                    w_st = str(s.get("wal_status") or "").lower()
                    sn = s.get("name", "unknown")
                    if ret > slot_critical_bytes or w_st == "lost":
                        gb = round(ret / (1024**3), 1)
                        return 2, f"Critical: Slot {sn} retains {gb:.1f} GB WAL"
        if nodes_up < nodes_total:
            return 1, f"Degraded: {nodes_total - nodes_up} of {nodes_total} master(s) offline"
        if mesh_disconnect_flag == 1:
            return 1, "Degraded: Multi-master mesh disconnected (one or more links inactive)"
        if subscription_apply_errors > 0:
            return 1, f"Degraded: {subscription_apply_errors} subscription apply error(s) detected"
        # Check slot warn in multi-master
        if slots_info:
            for s in slots_info:
                if not s.get("active"):
                    ret = s.get("wal_retained_bytes", 0) or 0
                    w_st = str(s.get("wal_status") or "").lower()
                    sn = s.get("name", "unknown")
                    if ret > slot_warn_bytes or w_st == "unreserved":
                        gb = round(ret / (1024**3), 1)
                        return 1, f"Degraded: Slot {sn} retains {gb:.1f} GB WAL"
        if slots_inactive > 0:
            return 1, f"Degraded: {slots_inactive} inactive replication slot(s) found"
        return 0, f"Multi-master cluster healthy: {nodes_up}/{nodes_total} active master nodes replicating"

    # Physical Cluster Rules
    # 1. Critical rules
    if primary_count == 0 or no_primary_flag == 1:
        return 2, "Critical: No active primary node detected"
    if split_brain_flag == 1 or primary_count > 1:
        return 2, f"Critical: Split brain detected ({primary_count} primary nodes active)"
    if standbys_expected > 0 and standbys_streaming == 0:
        return 2, f"Critical: No streaming standbys connected ({standbys_expected} expected)"

    # Critical slot severity: inactive slot retaining > slot_critical_bytes or wal_status == 'lost'
    if slots_info:
        for s in slots_info:
            if not s.get("active"):
                ret = s.get("wal_retained_bytes", 0) or 0
                w_st = str(s.get("wal_status") or "").lower()
                sn = s.get("name", "unknown")
                if ret > slot_critical_bytes or w_st == "lost":
                    gb = round(ret / (1024**3), 1)
                    return 2, f"Critical: Slot {sn} retains {gb:.1f} GB WAL"

    # 2. Degraded rules
    if nodes_up < nodes_total:
        return 1, f"Degraded: {nodes_total - nodes_up} of {nodes_total} node(s) offline"
    if standbys_streaming < standbys_expected:
        return 1, f"Degraded: {standbys_expected - standbys_streaming} of {standbys_expected} standby(s) not streaming"
    if max_replay_delay_s > delay_threshold_s:
        return 1, f"Degraded: Replay delay {max_replay_delay_s:.1f}s exceeds threshold ({delay_threshold_s:.0f}s)"
    if max_replay_backlog > backlog_threshold_bytes:
        mb = max_replay_backlog / (1024 * 1024)
        thresh_mb = backlog_threshold_bytes / (1024 * 1024)
        return 1, f"Degraded: Replay backlog {mb:.1f}MB exceeds threshold ({thresh_mb:.0f}MB)"

    # Slot warn severity: inactive slot retaining > slot_warn_bytes or wal_status == 'unreserved'
    slot_warn_found = None
    if slots_info:
        for s in slots_info:
            if not s.get("active"):
                ret = s.get("wal_retained_bytes", 0) or 0
                w_st = str(s.get("wal_status") or "").lower()
                sn = s.get("name", "unknown")
                if ret > slot_warn_bytes or w_st == "unreserved":
                    gb = round(ret / (1024**3), 1)
                    slot_warn_found = f"Degraded: Slot {sn} retains {gb:.1f} GB WAL"
                    break
    if slot_warn_found:
        return 1, slot_warn_found
    if slots_inactive > 0:
        return 1, f"Degraded: {slots_inactive} inactive replication slot(s) found"

    if timeline_mismatch_flag == 1:
        return 1, "Degraded: Timeline mismatch detected across cluster nodes"

    # Failover warning check: recent failover within failover_warn_seconds
    if failover_warn_seconds > 0 and seconds_since_last_failover is not None and seconds_since_last_failover <= failover_warn_seconds:
        mins = max(1, seconds_since_last_failover // 60)
        to_node = last_failover_to or "primary"
        tl = last_failover_timeline or 1
        prev_tl = tl - 1 if tl > 1 else 1
        return 1, f"Failover {mins} min ago: primary now {to_node} (timeline {prev_tl} to {tl})"

    # 3. Healthy rule
    return 0, f"Cluster healthy: {nodes_up}/{nodes_total} nodes active, {primary_count} primary, {standbys_streaming} standbys streaming"


def detect_cluster_type(evidence):
    """
    Pure evidence-based cluster type detection supporting all major architectures.
    Returns (detected_type: str, evidence_summary: str < 100 chars).
    """
    managers = []
    manager_evidences = []

    # 1. Patroni check - Patroni always takes priority if active
    patroni_info = evidence.get("patroni") or {}
    if patroni_info.get("is_patroni"):
        scope = patroni_info.get("scope", "patroni")
        ver = patroni_info.get("version", "")
        ver_str = f", v{ver}" if ver else ""
        managers.append("Patroni")
        manager_evidences.append(f"Patroni REST API response (scope: {scope}{ver_str})")

    exts = evidence.get("extensions", [])
    has_repmgr_table = evidence.get("repmgr_table", False)
    slot_names = evidence.get("slot_names", [])
    slot_types = evidence.get("slot_types", [])
    app_names = evidence.get("app_names", [])
    primary_count = evidence.get("primary_count", 0)
    total_nodes = evidence.get("total_nodes", 1)

    # 2. repmgr check
    is_repmgr = (
        ("repmgr" in exts) or has_repmgr_table or
        any(s.startswith("repmgr_slot_") for s in slot_names) or
        any(a.startswith("repmgr_") for a in app_names)
    )
    if is_repmgr:
        managers.append("repmgr")
        manager_evidences.append("repmgr extension / repmgr.nodes catalog found")

    # 3. pg_auto_failover check
    is_pgautofailover = (
        ("pgautofailover" in exts) or
        any(s.startswith("pgautofailover_standby_") for s in slot_names) or
        any(a.startswith("pgautofailover_") for a in app_names)
    )
    if is_pgautofailover:
        managers.append("pg_auto_failover")
        manager_evidences.append("pgautofailover extension / standby slot found")

    # 4. CloudNativePG (_cnpg_*)
    is_cnpg = (
        any(s.startswith("_cnpg_") for s in slot_names) or
        any(a.startswith("_cnpg_") or a.startswith("cnpg_") for a in app_names)
    )
    if is_cnpg:
        managers.append("CloudNative-PG")
        manager_evidences.append("CloudNative-PG replication slot pattern _cnpg_* found")

    # 5. Stolon
    is_stolon = (
        any(s.startswith("stolon_") for s in slot_names) or
        any(a.startswith("stolon_") for a in app_names)
    )
    if is_stolon:
        managers.append("Stolon")
        manager_evidences.append("Stolon replication slot / app pattern found")

    # 6. Citus Distributed
    if "citus" in exts:
        managers.append("Citus Distributed")
        manager_evidences.append("citus distributed extension installed")

    # 7. Multi-master (pglogical / BDR / Native Active-Active)
    if "bdr" in exts:
        managers.append("BDR")
        manager_evidences.append("BDR multi-master extension detected")
    elif "pglogical" in exts and primary_count >= 2:
        managers.append("Multi-Master (pglogical)")
        manager_evidences.append(f"pglogical active-active mesh ({primary_count} writable nodes)")
    elif primary_count >= 2:
        has_logical_slots = any(t == "logical" for t in slot_types) or any("logical" in str(s).lower() for s in slot_types)
        subscriptions_count = evidence.get("subscriptions_count", 0)
        logical_count = evidence.get("logical_replication_count", 0)
        all_up_sub = evidence.get("all_up_subscribe", False)
        all_up_pub = evidence.get("all_up_publish", False)
        if (all_up_sub and all_up_pub) or (subscriptions_count >= primary_count and (has_logical_slots or logical_count > 0)):
            managers.append("Multi-Master (native logical)")
            manager_evidences.append(f"Active-Active logical replication mesh ({primary_count} concurrent primaries)")
        else:
            managers.append("streaming replication (no HA manager detected)")
            manager_evidences.append(f"Split Brain: {primary_count} concurrent primary nodes without logical mesh")

    # 8. Managed cloud services
    if evidence.get("aurora_version"):
        managers.append("AWS Aurora")
        manager_evidences.append("aurora_version() function detected")
    elif "rds_superuser" in evidence.get("managed_roles", []):
        managers.append("AWS RDS")
        manager_evidences.append("rds_superuser role detected")
    elif "azure_pg_admin" in evidence.get("managed_roles", []):
        managers.append("Azure Database for PostgreSQL")
        manager_evidences.append("azure_pg_admin role detected")
    elif "cloudsqlsuperuser" in evidence.get("managed_roles", []):
        managers.append("GCP Cloud SQL")
        manager_evidences.append("cloudsqlsuperuser role detected")

    if sorted(managers) == ["Citus Distributed", "Patroni"]:
        return ("Patroni + Citus", "Patroni REST API plus citus extension installed")

    if len(managers) > 1:
        conflicts_str = " and ".join(managers)
        return ("mixed/unknown", f"Conflicting evidence: {conflicts_str} detected"[:99])

    if len(managers) == 1:
        return (managers[0], manager_evidences[0][:99])

    # Check for one-way logical replication
    has_logical_slots = any(t == "logical" for t in slot_types) or any("logical" in str(s).lower() for s in slot_types)
    subscriptions_count = evidence.get("subscriptions_count", 0)
    publications_count = evidence.get("publications_count", 0)
    logical_count = evidence.get("logical_replication_count", 0)
    has_logical = has_logical_slots or subscriptions_count > 0 or publications_count > 0 or logical_count > 0 or ("pglogical" in exts)

    if has_logical and not evidence.get("has_standbys", False) and not evidence.get("is_in_recovery", False):
        return ("logical replication (one-way)", "One-way logical replication detected (not active-active)"[:99])

    # Fallback to physical streaming replication
    has_standbys = evidence.get("has_standbys", False)
    has_slots = evidence.get("has_replication_slots", False)
    is_in_recovery = evidence.get("is_in_recovery", False)

    if has_standbys or has_slots or is_in_recovery or total_nodes > 1:
        st_count = evidence.get("standby_count", 0)
        return ("streaming replication (no HA manager detected)", f"PostgreSQL physical streaming replication ({st_count} standbys)"[:99])

    return ("standalone", "Single PostgreSQL instance without active streaming standbys"[:99])


class PostgresNodeClient:
    """
    Per-instance, thread-safe PostgreSQL client.
    Encapsulates all node-specific connection state, version detection, query preparation,
    evidence, and per-node table collection without any module-level global variables.
    """
    def __init__(self, name, host, port, username, password, db, patroni_port=None, has_explicit_alias=False, discovered_role=None):
        self.name = name                               # Display name / alias in tables
        self.has_explicit_alias = has_explicit_alias
        self.raw_host = host
        self.hostname = "127.0.0.1" if host in ("localhost", "127.0.0.1") else host
        self.port = int(port)
        self.username = username
        self.password = password
        self.db = db
        self.patroni_port = patroni_port
        self.discovered_role = str(discovered_role).strip().lower() if discovered_role else None
        self.is_witness = (self.discovered_role == "witness")
        self.endpoint_str = f"{host}:{port}"
        if patroni_port and patroni_port != "none":
            self.endpoint_str += f":{patroni_port}"

        self.conn = None
        self.server_version_num = 0
        self.server_version_str = ""
        self.is_primary = False
        self.timeline = None
        self.response_time_ms = 0.0
        self.is_up = False
        self.patroni_state = "N/A"
        self.patroni_info = None
        self.patroni_member = None
        self.notes = []

        # Per-node lag & connection counts
        self.connections = None
        self.replay_backlog_bytes = None
        self.replay_delay_s = None
        self.is_cascading = 0
        self.upstream = "N/A"

        # Pre-collected per-node rows
        self.subscriptions = []
        self.logical_slots = []
        self.logical_walsenders = []
        self.publications = []

        self.evidence = {}
        self.activity_row = None
        self.io_row = None
        self.transactions_row = None
        self.checkpoints_row = None
        self.conflicts_row = None

    def connect(self):
        """Establishes connection to the PostgreSQL node with sub-second timeout."""
        import psycopg2
        t0 = time.time()
        self.conn = psycopg2.connect(
            dbname=self.db,
            user=self.username,
            password=self.password,
            host=self.hostname,
            port=self.port,
            connect_timeout=CONNECT_TIMEOUT,
            options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"
        )
        self.conn.autocommit = True
        self.response_time_ms = round((time.time() - t0) * 1000.0, 2)
        self.is_up = True
        self.server_version_num = self.conn.server_version
        with self.conn.cursor() as cur:
            try:
                cur.execute("SHOW server_version;")
                self.server_version_str = cur.fetchone()[0]
            except Exception as e:
                err_str = str(e).lower()
                if "show help" in err_str or "pgbouncer" in err_str or "invalid command" in err_str:
                    raise ConfigError("Seed looks like a connection pooler: point nodes at a PostgreSQL node")
                raise
        check_for_pooler(self.conn)

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def query_patroni(self):
        """Best-effort Patroni REST API query."""
        if not self.patroni_port or self.patroni_port == "none":
            return
        url = f"http://{self.hostname}:{self.patroni_port}/patroni"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Site24x7-PGCluster'})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    self.patroni_info = {
                        "is_patroni": True,
                        "state": data.get("state", "unknown"),
                        "role": data.get("role", "unknown"),
                        "scope": data.get("patroni", {}).get("scope", "cluster"),
                        "version": data.get("patroni", {}).get("version", ""),
                        "timeline": data.get("timeline")
                    }
                    self.patroni_state = data.get("state", "N/A")
                    member = data.get("patroni", {}).get("name")
                    if member:
                        self.patroni_member = str(member).strip()
        except Exception:
            self.patroni_state = "N/A"

    def collect_full(self):
        """
        Executes complete node probing, evidence, per-node tables, and lag calculations
        inside the node worker thread. Enforces thread safety and returns self.
        """
        try:
            # 1. Best-effort Patroni probe
            self.query_patroni()

            # 2. Database connection
            self.connect()

            # 3. Role, timeline & lag probing
            with self.conn.cursor() as cur:
                cur.execute("SELECT pg_is_in_recovery();")
                in_rec = cur.fetchone()[0]
                self.is_primary = not in_rec

                if self.is_witness or self.discovered_role == "witness":
                    self.is_primary = False
                    self.is_witness = True
                elif self.is_primary:
                    try:
                        if _table_readable(cur, 'repmgr.nodes'):
                            cur.execute("SELECT type FROM repmgr.nodes WHERE node_name = %s OR conninfo LIKE %s LIMIT 1;", (self.name, f"%host={self.hostname}%"))
                            r = cur.fetchone()
                            if r and str(r[0]).strip().lower() == "witness":
                                self.is_primary = False
                                self.is_witness = True
                    except Exception:
                        pass

                if self.is_witness:
                    self.timeline = 0
                elif self.is_primary:
                    try:
                        cur.execute("SELECT ('x' || substring(pg_walfile_name(pg_current_wal_lsn()) from 1 for 8))::bit(32)::int;")
                        r = cur.fetchone()
                        if r and r[0] is not None:
                            self.timeline = int(r[0])
                    except Exception as e:
                        self.notes.append(f"Primary timeline query error: {e}")
                else:
                    # Standby timeline: use pg_stat_wal_receiver.received_tli first, then pg_control_checkpoint()
                    try:
                        cur.execute("SELECT received_tli FROM pg_stat_wal_receiver WHERE received_tli IS NOT NULL LIMIT 1;")
                        r = cur.fetchone()
                        if r and r[0] is not None:
                            self.timeline = int(r[0])
                    except Exception as e:
                        self.notes.append(f"Standby wal_receiver timeline error on {self.name}: {e}")

                    if self.timeline is None:
                        try:
                            cur.execute("SELECT timeline_id FROM pg_control_checkpoint();")
                            r = cur.fetchone()
                            if r and r[0] is not None:
                                self.timeline = int(r[0])
                        except Exception as e:
                            self.notes.append(f"Standby checkpoint timeline error on {self.name}: {e}")

                # Real per-node active connections count from sum(numbackends)
                try:
                    cur.execute("SELECT sum(numbackends) FROM pg_stat_database;")
                    r = cur.fetchone()
                    self.connections = int(r[0] or 0)
                except Exception:
                    try:
                        cur.execute("SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend';")
                        self.connections = int(cur.fetchone()[0])
                    except Exception as e:
                        self.notes.append(f"Connections count error on {self.name}: {e}")
                        self.connections = None

                # Standby replay lag and backlog (omit cells on primary)
                if not self.is_primary:
                    try:
                        cur.execute("SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn();")
                        r_lsns = cur.fetchone()
                        recv_lsn = r_lsns[0] if r_lsns else None
                        rep_lsn = r_lsns[1] if r_lsns else None
                        if recv_lsn and rep_lsn:
                            cur.execute("SELECT pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn());")
                            diff = cur.fetchone()[0]
                            self.replay_backlog_bytes = max(0, int(diff)) if diff is not None else 0
                            if recv_lsn == rep_lsn or self.replay_backlog_bytes == 0:
                                self.replay_delay_s = 0.0
                            else:
                                cur.execute("SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()));")
                                delay = cur.fetchone()[0]
                                self.replay_delay_s = max(0.0, round(float(delay), 2)) if delay is not None else 0.0
                        else:
                            self.replay_backlog_bytes = 0
                            self.replay_delay_s = 0.0
                    except Exception as e:
                        self.notes.append(f"Standby lag query error on {self.name}: {e}")

            # 4. Evidence collection
            self.collect_evidence()

            # 5. Per-node tables
            self.activity_row = self.collect_node_activity()
            self.io_row = self.collect_node_io()
            self.transactions_row = self.collect_node_transactions()
            self.checkpoints_row = self.collect_node_checkpoints()
            if not self.is_primary:
                self.conflicts_row = self.collect_standby_conflicts()
            else:
                self.conflicts_row = None

        except Exception as e:
            self.is_up = False
            self.notes.append(f"Node probe error on {self.name}: {e}")
        return self

    def collect_node_activity(self):
        """Builds a row for Node_Activity table using standalone parameter aliases."""
        row = {"name": self.name, "status": 1}
        if not self.is_up:
            row["status"] = 0
            return row

        try:
            with self.conn.cursor() as cur:
                row["active_connections"] = self.connections if self.connections is not None else 0

                cur.execute("select setting::int max_connections from pg_settings where name=$$max_connections$$;")
                row["max_connections"] = int(cur.fetchone()[0])

                cur.execute("SELECT count(*) - ( SELECT count(*) FROM pg_stat_activity WHERE state = 'idle' ) as active_queries FROM pg_stat_activity;")
                row["active_queries"] = int(cur.fetchone()[0])

                cur.execute("SELECT count(*) as active_waiting_queries FROM pg_stat_activity WHERE state = 'active' AND wait_event IS NOT NULL;")
                row["active_waiting_queries"] = int(cur.fetchone()[0])

                cur.execute("SELECT count(*) as transactions_open FROM pg_stat_activity WHERE xact_start IS NOT NULL;")
                row["transactions_open"] = int(cur.fetchone()[0])

                cur.execute("SELECT COUNT(*) as transactions_idle_in_transaction FROM pg_stat_activity WHERE state = 'idle in transaction';")
                row["transactions_idle_in_transaction"] = int(cur.fetchone()[0])

                cur.execute("SELECT COUNT(*) as locks_count FROM pg_locks;")
                row["locks_count"] = int(cur.fetchone()[0])

                cur.execute("SELECT COALESCE(MAX(EXTRACT(EPOCH FROM (now() - xact_start)))::bigint, 0) FROM pg_stat_activity WHERE state <> 'idle';")
                row["oldest_xact_age_s"] = int(cur.fetchone()[0])

                cur.execute("SELECT FLOOR(EXTRACT(EPOCH FROM current_timestamp - pg_postmaster_start_time())) as uptime;")
                row["uptime"] = int(cur.fetchone()[0])
        except Exception as e:
            self.notes.append(f"Node_Activity error on {self.name}: {e}")
            row["status"] = 0
        return row

    def collect_node_io(self):
        """Builds a row for Node_IO table (15 columns max, strictly within limits)."""
        row = {"name": self.name, "status": 1}
        if not self.is_up:
            row["status"] = 0
            return row

        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT sum(tup_inserted), sum(tup_updated), sum(tup_deleted), sum(tup_fetched), sum(tup_returned), sum(blks_read), sum(blks_hit) FROM pg_stat_database;")
                r = cur.fetchone()
                row["rows_inserted"] = int(r[0] or 0)
                row["rows_updated"] = int(r[1] or 0)
                row["rows_deleted"] = int(r[2] or 0)
                row["rows_fetched"] = int(r[3] or 0)
                row["rows_returned"] = int(r[4] or 0)
                row["block_reads"] = int(r[5] or 0)
                row["block_hits"] = int(r[6] or 0)

                cur.execute("SELECT sum(heap_blks_read) as heap_blocks_read, sum(heap_blks_hit) as heap_blocks_hit, CASE WHEN (sum(heap_blks_hit) + sum(heap_blks_read)) = 0 THEN 0 ELSE sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) END as cache_hit_ratio FROM pg_statio_user_tables;")
                r = cur.fetchone()
                row["heap_blocks_read"] = int(r[0] or 0)
                row["heap_blocks_hit"] = int(r[1] or 0)
                row["cache_hit_ratio"] = float(round(float(r[2] or 0.0), 4))

                cur.execute("SELECT sum(idx_scan) as index_scans, sum(idx_tup_read) as index_rows_read, sum(idx_tup_fetch) as index_rows_fetched FROM pg_stat_user_indexes;")
                r = cur.fetchone()
                row["index_scans"] = int(r[0] or 0)
                row["index_rows_read"] = int(r[1] or 0)
                row["index_rows_fetched"] = int(r[2] or 0)
        except Exception as e:
            self.notes.append(f"Node_IO error on {self.name}: {e}")
            row["status"] = 0
        return row

    def collect_node_transactions(self):
        """Builds a row for Node_Transactions table using standalone aliases."""
        row = {"name": self.name, "status": 1}
        if not self.is_up:
            row["status"] = 0
            return row

        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT sum(xact_commit), sum(xact_rollback), sum(conflicts) FROM pg_stat_database;")
                r = cur.fetchone()
                row["commits"] = int(r[0] or 0)
                row["rollbacks"] = int(r[1] or 0)
                row["conflicts"] = int(r[2] or 0)

                major_version = int(self.server_version_num % 1000000 / 10000)
                if major_version >= 14:
                    cur.execute("SELECT SUM(sessions), SUM(sessions_abandoned), SUM(sessions_fatal), SUM(sessions_killed) FROM pg_stat_database;")
                    r = cur.fetchone()
                    row["sessions"] = int(r[0] or 0)
                    row["sessions_abandoned"] = int(r[1] or 0)
                    row["sessions_fatal"] = int(r[2] or 0)
                    row["sessions_killed"] = int(r[3] or 0)
                else:
                    row["sessions"] = 0
                    row["sessions_abandoned"] = 0
                    row["sessions_fatal"] = 0
                    row["sessions_killed"] = 0
        except Exception as e:
            self.notes.append(f"Node_Transactions error on {self.name}: {e}")
            row["status"] = 0
        return row

    def collect_node_checkpoints(self):
        """Builds a row for Node_Checkpoints table supporting PG 17+ and PG <= 16."""
        row = {"name": self.name, "status": 1}
        if not self.is_up:
            row["status"] = 0
            return row

        try:
            with self.conn.cursor() as cur:
                is_pg17 = self.server_version_num >= 170000
                if is_pg17:
                    cur.execute("""
                        SELECT c.num_timed AS checkpoints_timed, c.num_requested AS checkpoints_req,
                               c.write_time AS checkpoint_write_time, c.sync_time AS checkpoint_sync_time,
                               c.buffers_written AS buffers_checkpoint, b.buffers_clean, b.maxwritten_clean, b.buffers_alloc
                        FROM pg_stat_checkpointer c, pg_stat_bgwriter b;
                    """)
                    r = cur.fetchone()
                    row["checkpoints_timed"] = int(r[0] or 0)
                    row["checkpoints_req"] = int(r[1] or 0)
                    row["checkpoint_write_time"] = int(r[2] or 0)
                    row["checkpoint_sync_time"] = int(r[3] or 0)
                    row["buffers_checkpoint"] = int(r[4] or 0)
                    row["buffers_clean"] = int(r[5] or 0)
                    row["maxwritten_clean"] = int(r[6] or 0)
                    row["buffers_alloc"] = int(r[7] or 0)
                else:
                    cur.execute("""
                        SELECT checkpoints_timed, checkpoints_req, checkpoint_write_time, checkpoint_sync_time,
                               buffers_checkpoint, buffers_clean, maxwritten_clean,
                               buffers_backend, buffers_backend_fsync, buffers_alloc
                        FROM pg_stat_bgwriter;
                    """)
                    r = cur.fetchone()
                    row["checkpoints_timed"] = int(r[0] or 0)
                    row["checkpoints_req"] = int(r[1] or 0)
                    row["checkpoint_write_time"] = int(r[2] or 0)
                    row["checkpoint_sync_time"] = int(r[3] or 0)
                    row["buffers_checkpoint"] = int(r[4] or 0)
                    row["buffers_clean"] = int(r[5] or 0)
                    row["maxwritten_clean"] = int(r[6] or 0)
                    row["buffers_backend"] = int(r[7] or 0)
                    row["buffers_backend_fsync"] = int(r[8] or 0)
                    row["buffers_alloc"] = int(r[9] or 0)
        except Exception as e:
            self.notes.append(f"Node_Checkpoints error on {self.name}: {e}")
            row["status"] = 0
        return row

    def collect_standby_conflicts(self):
        """Builds a row for Standby_Conflicts table for a standby node."""
        row = {"name": self.name, "status": 1}
        if not self.is_up:
            row["status"] = 0
            return row

        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT sum(confl_tablespace), sum(confl_lock), sum(confl_snapshot),
                           sum(confl_bufferpin), sum(confl_deadlock)
                    FROM pg_stat_database_conflicts;
                """)
                r = cur.fetchone()
                row["confl_tablespace"] = int(r[0] or 0)
                row["confl_lock"] = int(r[1] or 0)
                row["confl_snapshot"] = int(r[2] or 0)
                row["confl_bufferpin"] = int(r[3] or 0)
                row["confl_deadlock"] = int(r[4] or 0)
                row["total_conflicts"] = sum([row["confl_tablespace"], row["confl_lock"], row["confl_snapshot"], row["confl_bufferpin"], row["confl_deadlock"]])
        except Exception as e:
            self.notes.append(f"Standby_Conflicts error on {self.name}: {e}")
            row["status"] = 0
        return row

    def collect_evidence(self):
        """Best-effort cluster manager evidence collection."""
        evidence = {
            "extensions": [],
            "repmgr_table": False,
            "managed_roles": [],
            "aurora_version": False,
            "slot_names": [],
            "slot_types": [],
            "app_names": [],
            "is_in_recovery": not self.is_primary,
            "upstream": "N/A",
            "is_cascading": 0,
            "subscriptions_count": 0,
            "publications_count": 0,
            "has_sub": False,
            "has_pub": False
        }
        if not self.is_up:
            return evidence

        try:
            with self.conn.cursor() as cur:
                try:
                    cur.execute("SELECT extname FROM pg_extension WHERE extname IN ('repmgr', 'pgautofailover', 'citus', 'pglogical', 'bdr');")
                    evidence["extensions"] = [r[0] for r in cur.fetchall()]
                except Exception:
                    pass

                try:
                    cur.execute("SELECT to_regclass('repmgr.nodes');")
                    r = cur.fetchone()
                    if r and r[0]:
                        evidence["repmgr_table"] = True
                    else:
                        cur.execute("SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate AND datname != current_database();")
                        for db_cand in [row[0] for row in cur.fetchall()]:
                            try:
                                c = _pg_connect(self.hostname, self.port, self.username, self.password, db_cand)
                                with c.cursor() as c_cur:
                                    c_cur.execute("SELECT to_regclass('repmgr.nodes');")
                                    cr = c_cur.fetchone()
                                    if cr and cr[0]:
                                        evidence["repmgr_table"] = True
                                c.close()
                                if evidence.get("repmgr_table"):
                                    break
                            except Exception:
                                continue
                except Exception:
                    pass

                try:
                    cur.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('rds_superuser', 'azure_pg_admin', 'cloudsqlsuperuser');")
                    evidence["managed_roles"] = [r[0] for r in cur.fetchall()]
                except Exception:
                    pass

                try:
                    cur.execute("SELECT to_regprocedure('aurora_version()');")
                    r = cur.fetchone()
                    if r and r[0]:
                        evidence["aurora_version"] = True
                except Exception:
                    pass

                # Replication slots
                try:
                    cur.execute("""
                        SELECT slot_name,
                               COALESCE(plugin, 'none'),
                               COALESCE(slot_type, 'physical'),
                               CASE WHEN active = true THEN 1 ELSE 0 END,
                               ROUND(COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn), 0)::numeric, 0)
                        FROM pg_replication_slots;
                    """)
                    for r in cur.fetchall():
                        s_name = str(r[0])
                        s_plug = str(r[1])
                        s_type = str(r[2])
                        s_act = int(r[3] or 0)
                        s_ret = max(0, int(r[4] or 0))
                        evidence["slot_names"].append(s_name)
                        evidence["slot_types"].append(s_type)
                        self.logical_slots.append({
                            "slot_name": s_name,
                            "plugin": s_plug,
                            "slot_type": s_type,
                            "active": s_act,
                            "wal_retained_bytes": s_ret
                        })
                except Exception:
                    pass

                # Publications
                try:
                    cur.execute("SELECT pubname FROM pg_publication;")
                    self.publications = [str(r[0]) for r in cur.fetchall()]
                except Exception:
                    self.publications = []

                # Subscriptions & subscription stats
                try:
                    cur.execute("""
                        SELECT s.subname,
                               s.subenabled,
                               COALESCE(s.subconninfo, ''),
                               st.pid,
                               COALESCE(st.received_lsn::text, ''),
                               ROUND(COALESCE(EXTRACT(EPOCH FROM (now() - st.last_msg_receipt_time)), 0)::numeric, 2),
                               COALESCE(stats.apply_error_count, 0),
                               COALESCE(stats.sync_error_count, 0)
                        FROM pg_subscription s
                        LEFT JOIN pg_stat_subscription st ON s.oid = st.subid
                        LEFT JOIN pg_stat_subscription_stats stats ON s.oid = stats.subid;
                    """)
                    for r in cur.fetchall():
                        sname, senabled, sconn, spid, s_rlsn, s_delay, a_err, s_err = r
                        is_act = 1 if (senabled and spid and int(spid) > 0) else 0
                        self.subscriptions.append({
                            "subname": str(sname),
                            "enabled": bool(senabled),
                            "conninfo": str(sconn),
                            "pid": int(spid) if spid else None,
                            "active": is_act,
                            "received_lsn": str(s_rlsn),
                            "receipt_delay_s": float(s_delay or 0.0),
                            "apply_error_count": int(a_err or 0),
                            "sync_error_count": int(s_err or 0)
                        })
                except Exception:
                    try:
                        cur.execute("""
                            SELECT st.subname,
                                   st.pid,
                                   COALESCE(st.received_lsn::text, ''),
                                   ROUND(COALESCE(EXTRACT(EPOCH FROM (now() - st.last_msg_receipt_time)), 0)::numeric, 2)
                            FROM pg_stat_subscription st;
                        """)
                        for r in cur.fetchall():
                            sname, spid, s_rlsn, s_delay = r
                            is_act = 1 if (spid and int(spid) > 0) else 0
                            self.subscriptions.append({
                                "subname": str(sname),
                                "enabled": True,
                                "conninfo": "",
                                "pid": int(spid) if spid else None,
                                "active": is_act,
                                "received_lsn": str(s_rlsn),
                                "receipt_delay_s": float(s_delay or 0.0),
                                "apply_error_count": 0,
                                "sync_error_count": 0
                            })
                    except Exception:
                        pass

                # Logical count
                evidence["logical_replication_count"] = len(self.publications) + len(self.subscriptions)
                evidence["subscriptions_count"] = len(self.subscriptions)
                evidence["publications_count"] = len(self.publications)
                evidence["has_sub"] = len(self.subscriptions) > 0
                evidence["has_pub"] = len(self.publications) > 0 or any(s["slot_type"] == "logical" for s in self.logical_slots)

                if not self.is_primary:
                    try:
                        cur.execute("SELECT status, sender_host, sender_port, slot_name FROM pg_stat_wal_receiver;")
                        r = cur.fetchone()
                        if r:
                            evidence["wal_receiver_status"] = r[0]
                            evidence["upstream"] = f"{r[1]}:{r[2]}" if r[1] else "primary"
                            self.upstream = evidence["upstream"]
                    except Exception:
                        pass

                # Walsenders
                try:
                    cur.execute("""
                        SELECT application_name,
                               COALESCE(client_addr::text, 'unknown'),
                               COALESCE(state, 'unknown'),
                               ROUND(COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn), 0)::numeric, 0),
                               ROUND(COALESCE(EXTRACT(EPOCH FROM replay_lag), 0)::numeric, 2)
                        FROM pg_stat_replication;
                    """)
                    for r in cur.fetchall():
                        app_name = str(r[0] or "")
                        evidence["app_names"].append(app_name)
                        self.logical_walsenders.append({
                            "application_name": app_name,
                            "client_addr": str(r[1]),
                            "state": str(r[2]),
                            "replay_lag_bytes": max(0, int(r[3] or 0)),
                            "replay_lag_s": max(0.0, float(r[4] or 0.0))
                        })
                    if not self.is_primary and len(evidence["app_names"]) > 0:
                        evidence["is_cascading"] = 1
                        self.is_cascading = 1
                except Exception:
                    pass

        except Exception:
            pass

        self.evidence = evidence
        return evidence


# ---------------------------------------------------------------------------
# Node discovery: give one address, find every node of the cluster.
#   1. Patroni      -> GET /cluster on any member (exact: names, hosts, ports, roles)
#   2. repmgr       -> repmgr.nodes
#   3. Citus        -> pg_dist_node
#   4. pg_auto_failover monitor -> pgautofailover.node
#   5. anything else with streaming replication (plain, Stolon, CloudNativePG, ...)
#                   -> walk pg_stat_wal_receiver (upstream) and pg_stat_replication (downstream)
# Standbys found through pg_stat_replication only expose an IP, so the primary's port is assumed.
# ---------------------------------------------------------------------------
def _norm_host(h):
    h = str(h).strip().lower()
    return "127.0.0.1" if h in ("localhost", "::1", "127.0.0.1") else h


def _http_json(url, timeout=1.5):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Site24x7-PGCluster'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode('utf-8'))
    except Exception:
        pass
    return None


def discover_via_patroni(host, patroni_port, address_map=None):
    """Returns (members, scope) from the Patroni REST API of one member, or ([], None)."""
    data = _http_json(f"http://{host}:{patroni_port}/cluster")
    if not data or not isinstance(data.get("members"), list):
        return [], None
    members = []
    for m in data["members"]:
        name, h, p = m.get("name"), m.get("host"), m.get("port")
        if not (name and h and p):
            continue
        pp = str(patroni_port)
        mm = re.match(r"https?://[^:/]+:(\d+)", str(m.get("api_url") or ""))
        if mm:
            pp = mm.group(1)
        if address_map:
            mh, mp = map_address(h, p, address_map)
            h, p = mh, mp
            m_pat_h, m_pat_p = map_address(str(m.get("host")), pp, address_map)
            if m_pat_p:
                pp = str(m_pat_p)
        members.append({"alias": safe_name(name), "member": str(name), "host": str(h), "port": int(p),
                        "patroni_port": pp, "source": "Patroni REST API"})
    return members, data.get("scope")


def _pg_connect(host, port, user, pw, db):
    import psycopg2
    conn = psycopg2.connect(dbname=db, user=user, password=pw, host=_norm_host(host) if _norm_host(host) == "127.0.0.1" else host,
                            port=int(port), connect_timeout=2, options="-c statement_timeout=2000")
    conn.autocommit = True
    return conn


def _conninfo_hostport(conninfo, default_port=None):
    h = re.search(r"host=([^\s']+)", conninfo or "")
    p = re.search(r"port=(\d+)", conninfo or "")
    port_val = int(p.group(1)) if p else default_port
    return (h.group(1) if h else None), port_val


def _default_node_name(host, port):
    """Name for a node that has no alias: its host name (pg-mm1 gives pgmm1), or host and port when it is an IP address."""
    h = str(host).strip()
    try:
        import ipaddress
        ipaddress.ip_address(h.strip("[]"))
        is_ip = True
    except ValueError:
        is_ip = False
    if not is_ip and h.lower() != "localhost":
        name = safe_name(h.split(".")[0])
        if name:
            return name
    return safe_name(f"{h}_{port}")


def _name_from_address_map(host, port, address_map):
    """If this reachable address is the target of an address_map entry, name the node after that entry's own host
    (pg-mm1:5432=127.0.0.1:5451 gives pgmm1)."""
    if not address_map:
        return None
    try:
        h, p = str(host).strip().lower(), int(port)
    except (TypeError, ValueError):
        return None
    for key, target in address_map.items():
        if not isinstance(key, tuple):
            continue
        th, _, tp = str(target).partition(":")
        try:
            tp_i = int(tp) if tp.strip() else int(key[1])
        except ValueError:
            continue
        if th.strip().lower() == h and tp_i == p:
            name = safe_name(str(key[0]).split(".")[0])
            if name:
                return name
    return None


def _alias_for(host, port, app, taken, address_map=None):
    """Readable alphanumeric name for a node found without an explicit name."""
    host = str(host)
    app_str = str(app or "").strip()
    mapped = _name_from_address_map(host, port, address_map)
    if mapped:
        base = mapped
    elif app_str and app_str not in ("walreceiver", "") and not app_str.startswith("sub_") and safe_name(app_str):
        base = safe_name(app_str)
    else:
        base = _default_node_name(host, port)
    name, k = base, 2
    while name.lower() in taken:
        name, k = f"{base}{k}", k + 1
    taken.add(name.lower())
    return name


def _discover_repmgr_members(conn, host, port, user, pw, address_map=None):
    """
    Dynamically finds the database containing the repmgr schema by searching pg_database
    (to_regnamespace or catalog query per database), never by a hard-coded name.
    Reads repmgr.nodes (node_name, type, conninfo, active) safely without printing/leaking passwords.
    """
    repmgr_conn = None
    close_needed = False

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('repmgr.nodes') IS NOT NULL;")
            r = cur.fetchone()
            if r and r[0]:
                repmgr_conn = conn
    except Exception:
        pass

    if not repmgr_conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate AND datname != current_database();")
                candidates = [row[0] for row in cur.fetchall()]
            for db_cand in candidates:
                try:
                    c = _pg_connect(host, port, user, pw, db_cand)
                    with c.cursor() as cur:
                        cur.execute("SELECT to_regclass('repmgr.nodes') IS NOT NULL;")
                        r = cur.fetchone()
                        if r and r[0]:
                            repmgr_conn = c
                            close_needed = True
                            break
                    c.close()
                except Exception:
                    continue
        except Exception:
            pass

    if not repmgr_conn:
        return []

    out = []
    try:
        with repmgr_conn.cursor() as cur:
            cur.execute("SELECT node_id, node_name, type, conninfo, active FROM repmgr.nodes ORDER BY node_id;")
            for _nid, name, ntype, conninfo, active in cur.fetchall():
                h, p = parse_conninfo_hostport(conninfo)
                p = p or port
                if h:
                    mph, mpp = map_address(h, p, address_map)
                    role = str(ntype).strip().lower()
                    out.append({
                        "alias": safe_name(name),
                        "member": str(name),
                        "host": mph,
                        "port": int(mpp),
                        "patroni_port": "none",
                        "role": role,
                        "active": bool(active),
                        "source": "repmgr.nodes"
                    })
    except Exception:
        pass
    finally:
        if close_needed and repmgr_conn:
            try:
                repmgr_conn.close()
            except Exception:
                pass
    return out


def _managed_members(cur, port):
    """Exact member lists kept in the catalogs of repmgr, Citus and the pg_auto_failover monitor."""
    out = []
    try:
        cur.execute("SELECT to_regclass('repmgr.nodes');")
        if cur.fetchone()[0]:
            cur.execute("SELECT node_name, conninfo FROM repmgr.nodes ORDER BY node_id;")
            for name, conninfo in cur.fetchall():
                h, p = _conninfo_hostport(conninfo)
                if h:
                    out.append({"alias": safe_name(name), "member": str(name), "host": h, "port": p, "patroni_port": "none", "source": "repmgr.nodes"})
            if out:
                return out
    except Exception:
        pass
    try:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'citus';")
        if cur.fetchone():
            cur.execute("SELECT nodename, nodeport, noderole FROM pg_dist_node WHERE isactive ORDER BY nodeid;")
            for i, (h, p, role) in enumerate(cur.fetchall(), 1):
                out.append({"alias": safe_name(str(h).split(".")[0]) or safe_name(f"{role}{i}"), "member": f"{role}{i}", "host": str(h), "port": int(p), "patroni_port": "none", "source": "Citus pg_dist_node"})
            if out:
                return out
    except Exception:
        pass
    try:
        cur.execute("SELECT to_regclass('pgautofailover.node');")
        if cur.fetchone()[0]:
            cur.execute("SELECT nodename, nodehost, nodeport FROM pgautofailover.node ORDER BY nodeid;")
            for name, h, p in cur.fetchall():
                out.append({"alias": safe_name(name), "member": str(name), "host": str(h), "port": int(p), "patroni_port": "none", "source": "pgautofailover.node"})
            if out:
                return out
    except Exception:
        pass
    return out


def discover_via_sql(seeds, user, pw, db, deadline, address_map=None):
    """Walks the replication topology from the seeds. Returns (members, source)."""
    queue = [(h, int(p), None) for h, p in seeds]
    visited, visited_canon, found = set(), set(), OrderedDict()
    is_logical = False
    is_pglogical = False

    while queue and time.time() < deadline and len(found) < MAX_NODES:
        host, port, app = queue.pop(0)
        key = (_norm_host(host), port)
        if key in visited:
            continue
        visited.add(key)
        try:
            conn = _pg_connect(host, port, user, pw, db)
            check_for_pooler(conn)
        except ConfigError:
            raise
        except Exception:
            alias = _alias_for(host, port, app, {v["alias"].lower() for v in found.values()}, address_map)
            found[key] = {"alias": alias, "member": alias, "host": host, "port": port, "patroni_port": "none", "source": "streaming replication topology"}
            continue
        try:
            with conn.cursor() as cur:
                managed = _discover_repmgr_members(conn, host, port, user, pw, address_map=address_map)
                if not managed:
                    managed = _managed_members(cur, port)
                if managed:
                    return managed, managed[0]["source"]

                try:
                    cur.execute("SELECT host(inet_server_addr()), inet_server_port();")
                    ra, rp = cur.fetchone()
                except Exception:
                    ra, rp = None, None
                canon = (ra or _norm_host(host), int(rp or port))
                if canon in visited_canon:
                    continue
                visited_canon.add(canon)
                alias = _alias_for(host, port, app, {v["alias"].lower() for v in found.values()}, address_map)
                found[key] = {"alias": alias, "member": alias, "host": host, "port": port, "patroni_port": "none", "source": "streaming replication topology"}

                try:
                    cur.execute("SELECT pg_is_in_recovery();")
                    if cur.fetchone()[0]:
                        cur.execute("SELECT sender_host, sender_port FROM pg_stat_wal_receiver WHERE sender_host IS NOT NULL LIMIT 1;")
                        r = cur.fetchone()
                        if r and r[0]:
                            queue.append((r[0], int(r[1] or port), None))
                except Exception:
                    pass

                # Per rule 1: Standbys found via pg_stat_replication cannot be probed (client_addr has no port).
                # Do not append client_addr to discovery queue.

                # Native logical replication subscriptions discovery
                try:
                    if _column_readable(cur, 'pg_catalog.pg_subscription', 'subconninfo'):
                        cur.execute("SELECT subname, subconninfo FROM pg_subscription WHERE subconninfo IS NOT NULL;")
                        for subname, conninfo in cur.fetchall():
                            is_logical = True
                            ph, pp = parse_conninfo_hostport(conninfo)
                            if ph:
                                mph, mpp = map_address(ph, pp or port, address_map)
                                queue.append((mph, mpp, subname))
                except Exception:
                    pass

                # pglogical topology discovery
                try:
                    if _table_readable(cur, 'pglogical.node_interface'):
                        cur.execute("SELECT if_name, if_dsn FROM pglogical.node_interface;")
                        for if_name, dsn in cur.fetchall():
                            is_pglogical = True
                            ph, pp = parse_conninfo_hostport(dsn)
                            if ph:
                                mph, mpp = map_address(ph, pp or port, address_map)
                                queue.append((mph, mpp, if_name))
                except Exception:
                    pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    source = "streaming replication topology"
    if is_pglogical:
        source = "pglogical topology"
    elif is_logical:
        source = "native logical replication subscriptions"
    for item in found.values():
        item["source"] = source
    return list(found.values()), source


def discover_cluster_members(seeds, user, pw, db, deadline_s, address_map=None):
    """seeds: list of (host, pg_port, patroni_port). Returns (members, source, seed_names).
    seed_names maps (host, pg_port) of each Patroni seed to its Patroni member alias."""
    deadline = time.time() + deadline_s
    seed_names = {}
    pat_seeds = [(h, p, pat) for h, p, pat in seeds if pat and str(pat) != "none"]
    if pat_seeds:
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(pat_seeds) * 2))
        f_cluster = [(ex.submit(discover_via_patroni, h, pat, address_map), h, p) for h, p, pat in pat_seeds]
        f_name = [(ex.submit(_patroni_member_name, h, pat), h, p) for h, p, pat in pat_seeds]
        end = time.time() + max(0.5, min(2.5, deadline - time.time()))
        pending = {f for f, _, _ in f_cluster + f_name}
        found = []
        while pending and time.time() < end and not found:
            _done, pending = concurrent.futures.wait(pending, timeout=max(0.05, end - time.time()), return_when=concurrent.futures.FIRST_COMPLETED)
            for f, h, p in f_cluster:
                if f.done() and not f.exception() and f.result()[0]:
                    found = f.result()[0]
                    break
        if found:
            # short grace so the seeds' own member names can arrive too
            concurrent.futures.wait([f for f, _, _ in f_name], timeout=0.4)
        for f, h, p in f_name:
            if f.done() and not f.exception() and f.result():
                seed_names[(_norm_host(h), int(p))] = safe_name(f.result())
        ex.shutdown(wait=False, cancel_futures=True)
        if found:
            return found, "Patroni REST API", seed_names
    members, source = discover_via_sql([(h, p) for h, p, _ in seeds], user, pw, db, deadline, address_map=address_map)
    return members, source, seed_names


def _patroni_member_name(host, patroni_port):
    data = _http_json(f"http://{host}:{patroni_port}/patroni", timeout=1.0)
    return str(((data or {}).get("patroni") or {}).get("name") or "") or None



def _evidence_with_discovery(evidence, nodes_total, added, source):
    """Appends how many nodes were listed in the config and how many discovery found, within 99 characters."""
    suffix = f" | {int(nodes_total) - int(added)} listed, {int(added)} found"
    if added and source:
        suffix += f" via {str(source)[:24]}"
    return (str(evidence)[:max(0, 99 - len(suffix))] + suffix)[:99]


class PostgresClusterCollector:
    """
    Main collector coordinating concurrent node probes, cluster-level metrics,
    per-node tables, cluster type detection, and Site24x7 JSON packaging.
    """
    def __init__(self, nodes_str, username, password, db, patroni_port=PATRONI_PORT, cluster_type=CLUSTER_TYPE, discover=DISCOVER, address_map=ADDRESS_MAP, failover_warn_seconds=FAILOVER_WARN_SECONDS, slot_warn_bytes=SLOT_WARN_BYTES, slot_critical_bytes=SLOT_CRITICAL_BYTES):
        self.nodes_str = nodes_str
        self.username = username
        self.password = password
        self.db = db
        self.patroni_port = patroni_port
        self.cluster_type_override = cluster_type
        self.discover = discover
        self.address_map_str = address_map
        self.address_map = parse_address_map(address_map)
        self.failover_warn_seconds = int(failover_warn_seconds) if failover_warn_seconds is not None else FAILOVER_WARN_SECONDS
        self.slot_warn_bytes = int(slot_warn_bytes) if slot_warn_bytes is not None else SLOT_WARN_BYTES
        self.slot_critical_bytes = int(slot_critical_bytes) if slot_critical_bytes is not None else SLOT_CRITICAL_BYTES
        self.discovery_added = 0
        self.discovery_source = ""
        self.msg_notes = []

    def _add_note(self, text):
        clean = str(text).strip()
        if clean and clean not in self.msg_notes:
            self.msg_notes.append(clean)

    def _cache_path(self):
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(plugin_dir, "topology_cache.json")

    def _load_cache(self):
        cache_file = self._cache_path()
        if not os.path.exists(cache_file):
            return None
        try:
            with open(cache_file, "r") as f:
                data = json.load(f)
            ts = data.get("timestamp", 0)
            if time.time() - ts > 86400:  # 24 hours expiry
                return None
            return data
        except Exception:
            return None

    def _save_cache(self, members, source="", seed_names=None):
        cache_file = self._cache_path()
        try:
            existing = self._load_cache() or {}
            endpoints = existing.get("endpoints", {})
            if seed_names:
                for k, v in seed_names.items():
                    if isinstance(k, tuple):
                        h, p = k
                        endpoints[f"{h}:{p}"] = str(v)
                        endpoints[str(p)] = str(v)
                    else:
                        endpoints[str(k)] = str(v)
            data = {
                "timestamp": int(time.time()),
                "source": str(source),
                "endpoints": endpoints,
                "members": [
                    {
                        "name": str(m.get("alias") or m.get("member") or m.get("name")),
                        "host": str(m.get("host")),
                        "port": int(m.get("port")),
                        "patroni_port": str(m.get("patroni_port", "none")),
                        "role": str(m.get("role", ""))
                    }
                    for m in members if (m.get("alias") or m.get("member") or m.get("name"))
                ]
            }
            with open(cache_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _parse_nodes(self):
        parsed = []
        cache = self._load_cache()
        cached_endpoints = (cache or {}).get("endpoints", {})
        cached_map = {}
        if cache and "members" in cache:
            for m in cache["members"]:
                mname = safe_name(m.get("name"))
                if mname:
                    h_norm = str(m.get("host")).strip().lower()
                    p_val = int(m.get("port", 0))
                    pat_val = str(m.get("patroni_port", "none"))
                    cached_map[(h_norm, p_val)] = mname
                    cached_map[str(p_val)] = mname
                    if pat_val != "none":
                        cached_map[(h_norm, pat_val)] = mname
                        cached_map[pat_val] = mname

        for raw in self.nodes_str.split(','):
            entry = raw.strip()
            if not entry:
                continue
            alias = None
            has_explicit_alias = False
            if "=" in entry:
                alias, entry = entry.split("=", 1)
                alias = alias.strip()
                entry = entry.strip()
                if alias:
                    has_explicit_alias = True

            parts = entry.split(':')
            if len(parts) >= 3:
                h, p, pat = parts[0], parts[1], parts[2]
            elif len(parts) == 2:
                h, p, pat = parts[0], parts[1], self.patroni_port
            else:
                self._add_note(f"Node '{entry}' has no port; write it as host:port (ignored)")
                continue

            h_norm = str(h).strip().lower()
            p_str = str(p).strip()
            pat_str = str(pat).strip()
            ep_key = f"{h}:{p}"
            ep_pat_key = f"{h}:{pat}" if pat_str and pat_str != "none" else None

            if alias:
                display_name = safe_name(alias)
            elif _name_from_address_map(h, p, self.address_map):
                display_name = _name_from_address_map(h, p, self.address_map)
            elif cached_endpoints.get(ep_key):
                display_name = safe_name(cached_endpoints[ep_key])
            elif ep_pat_key and cached_endpoints.get(ep_pat_key):
                display_name = safe_name(cached_endpoints[ep_pat_key])
            elif cached_endpoints.get(p_str):
                display_name = safe_name(cached_endpoints[p_str])
            elif pat_str and cached_endpoints.get(pat_str):
                display_name = safe_name(cached_endpoints[pat_str])
            elif (h_norm, int(p)) in cached_map:
                display_name = cached_map[(h_norm, int(p))]
            elif p_str in cached_map:
                display_name = cached_map[p_str]
            elif pat_str and pat_str in cached_map:
                display_name = cached_map[pat_str]
            else:
                display_name = _default_node_name(h, p)

            base_name, dup = display_name, 2
            while any(p_[0] == display_name for p_ in parsed):
                display_name = f"{base_name}{dup}"
                dup += 1
            if display_name != base_name:
                self._add_note(f"Duplicate node alias {base_name} renamed to {display_name}")
            parsed.append((display_name, h, p, pat, has_explicit_alias))
        return parsed

    def _apply_discovery(self, node_defs):
        """Adds cluster members found from the configured address(es) that are not configured yet."""
        if str(self.discover).strip().lower() in ("off", "false", "0", "no") or not node_defs:
            return node_defs
        seeds = [(h, p, pat) for (_n, h, p, pat, _a) in node_defs]
        cache = self._load_cache()
        cached_extra = []
        if cache and "members" in cache:
            known_seeds = {(str(h).strip().lower(), int(p)) for h, p, _ in seeds}
            for m in cache["members"]:
                m_h = str(m.get("host")).strip().lower()
                m_p = int(m.get("port", 0))
                m_pat = str(m.get("patroni_port", "none"))
                if (m_h, m_p) not in known_seeds:
                    cached_extra.append((m_h, m_p, m_pat))

        ex = concurrent.futures.ThreadPoolExecutor(max_workers=min(16, max(len(seeds), len(cached_extra)) * 2 + 1))
        t0_disc = time.monotonic()
        try:
            fut = ex.submit(discover_cluster_members, seeds, self.username, self.password, self.db, DISCOVERY_DEADLINE_S, address_map=self.address_map)
            members, source, seed_names = fut.result(timeout=DISCOVERY_DEADLINE_S)
        except Exception:
            members, source, seed_names = [], "", {}
        rem_disc = DISCOVERY_DEADLINE_S - (time.monotonic() - t0_disc)
        if not members and cached_extra and rem_disc > 0.5:
            try:
                fut = ex.submit(discover_cluster_members, cached_extra, self.username, self.password, self.db, rem_disc, address_map=self.address_map)
                members, source, seed_names = fut.result(timeout=rem_disc)
            except Exception:
                pass
        ex.shutdown(wait=False, cancel_futures=True)

        if not members and cache and "members" in cache:
            ts_str = time.strftime('%Y-%m-%d %H:%M:%S GMT', time.gmtime(cache.get('timestamp', time.time())))
            self._add_note(f"seed unreachable, members from {ts_str}")
            members = [
                {"alias": m["name"], "member": m["name"], "host": m["host"], "port": m["port"], "patroni_port": m.get("patroni_port", "none"), "role": m.get("role", ""), "source": "topology cache"}
                for m in cache["members"]
            ]
            source = "topology cache"
        elif members:
            self._save_cache(members, source, seed_names=seed_names)

        self.role_map = {}
        for m in members:
            alias = safe_name(m.get("alias") or m.get("member") or m.get("name"))
            if alias and m.get("role"):
                self.role_map[alias.lower()] = str(m.get("role")).strip().lower()

        if not members:
            return node_defs

        known_addr = {(_norm_host(h), int(p)) for (_n, h, p, _pat, _a) in node_defs}
        known_alias = {n.lower() for (n, *_rest) in node_defs}
        known_member = set()

        for i, (n, h, p, pat, a) in enumerate(list(node_defs)):
            h_norm = str(h).strip().lower()
            p_int = int(p)
            pat_str = str(pat).strip()
            mname = seed_names.get((_norm_host(h), p_int)) or seed_names.get(p_int)
            if not mname and pat_str and pat_str != "none":
                mname = seed_names.get((h_norm, pat_str)) or seed_names.get(pat_str)
            if not mname:
                for m in members:
                    if int(m.get("port", 0)) == p_int:
                        mname = safe_name(m.get("alias") or m.get("name"))
                        break
                    if pat_str and pat_str != "none" and str(m.get("patroni_port")) == pat_str:
                        mname = safe_name(m.get("alias") or m.get("name"))
                        break
            if not mname and cache and "members" in cache:
                for m in cache["members"]:
                    if int(m.get("port", 0)) == p_int:
                        mname = safe_name(m.get("name"))
                        break
                    if pat_str and pat_str != "none" and str(m.get("patroni_port")) == pat_str:
                        mname = safe_name(m.get("name"))
                        break
            if mname:
                known_member.add(mname.lower())
                if not a:
                    node_defs[i] = (mname, h, p, pat, a)
                    known_alias.discard(n.lower())
                    known_alias.add(mname.lower())

        by_addr = {(_norm_host(m["host"]), int(m["port"])): m["alias"] for m in members if m.get("alias")}
        for i, (n, h, p, pat, a) in enumerate(list(node_defs)):
            nm = by_addr.get((_norm_host(h), int(p)))
            if nm and not a and n.lower() != nm.lower() and nm.lower() not in known_alias:
                node_defs[i] = (nm, h, p, pat, a)
                known_alias.discard(n.lower())
                known_alias.add(nm.lower())

        if len(node_defs) >= len(members):
            return node_defs

        added = 0
        for m in members:
            key = (_norm_host(m["host"]), int(m["port"]))
            if key in known_addr or m["alias"].lower() in known_alias or m["alias"].lower() in known_member:
                continue
            if len(node_defs) >= MAX_NODES:
                self._add_note(f"Cluster has more than {MAX_NODES} nodes; extra nodes are not shown")
                break
            name, k = m["alias"] or _name_from_address_map(m["host"], m["port"], self.address_map) or _default_node_name(m['host'], m['port']), 2
            while name.lower() in known_alias:
                name = f"{m['alias']}{k}"
                k += 1
            node_defs.append((name, m["host"], m["port"], m["patroni_port"], False))
            known_alias.add(name.lower())
            known_addr.add(key)
            added += 1
        self.discovery_added = added
        self.discovery_source = source
        return node_defs

    def collect(self):
        results = OrderedDict()
        results["plugin_version"] = PLUGIN_VERSION
        results["heartbeat_required"] = HEARTBEAT
        results["status"] = 1

        try:
            return self._collect_internal(results)
        except ConfigError as e:
            results["status"] = 0
            results["msg"] = str(e)
            results["Cluster_Info"] = []
            results["Cluster_Nodes"] = []
            results["Replication_Links"] = []
            results["Replication_Slots"] = []
            results["Node_IO"] = []
            results["Node_Checkpoints"] = []
            results["Node_Activity"] = []
            results["Node_Transactions"] = []
            if "tabs" not in results:
                results.update(copy.deepcopy(tabs))
            if "units" not in results:
                results["units"] = units
            return results
        except UnsupportedClusterError as e:
            results["status"] = 0
            results["msg"] = f"Detected {e.cluster_type}: not supported by this plugin version"
            results["Cluster_Info"] = [{
                "name": "cluster",
                "cluster_type": str(e.cluster_type)[:99],
                "type_evidence": str(e.evidence)[:99],
                "server_version": "unknown",
                "primary_node": "none",
                "health_reason": f"Unsupported: {e.cluster_type}",
                "nodes_total": 0,
                "nodes_up": 0,
                "primary_timeline": 0,
                "status": 0
            }]
            results["Cluster_Nodes"] = []
            results["Replication_Links"] = []
            results["Replication_Slots"] = []
            results["Node_IO"] = []
            results["Node_Checkpoints"] = []
            results["Node_Activity"] = []
            results["Node_Transactions"] = []
            if "tabs" not in results:
                results.update(copy.deepcopy(tabs))
            if "units" not in results:
                results["units"] = units
            return results
        except Exception as e:
            results["status"] = 0
            err_msg = f"Unexpected collector exception: {type(e).__name__}: {str(e)}"
            if self.msg_notes:
                results["msg"] = "; ".join(self.msg_notes) + f"; {err_msg}"
            else:
                results["msg"] = err_msg
            if "tabs" not in results:
                results.update(copy.deepcopy(tabs))
            if "units" not in results:
                results["units"] = units
            return results

    def _collect_internal(self, results):
        server_version_str = "unknown"

        node_defs = self._apply_discovery(self._parse_nodes())
        nodes_total = len(node_defs)
        if nodes_total == 0:
            results["status"] = 0
            results["msg"] = "No nodes configured in NODES parameter"
            results.update(copy.deepcopy(tabs))
            results["units"] = units
            return results

        clients = []
        role_map = getattr(self, "role_map", {})
        for dname, h, p, pat, has_alias in node_defs:
            d_role = role_map.get(dname.lower())
            clients.append(PostgresNodeClient(dname, h, p, self.username, self.password, self.db, pat, has_explicit_alias=has_alias, discovered_role=d_role))

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(16, nodes_total))
        future_to_client = {executor.submit(cli.collect_full): cli for cli in clients}
        done, not_done = concurrent.futures.wait(future_to_client.keys(), timeout=NODE_COLLECT_DEADLINE_S)
        executor.shutdown(wait=False, cancel_futures=True)
        for fut in not_done:
            cli = future_to_client[fut]
            cli.is_up = False
            cli.notes.append(f"Node probe timed out after {NODE_COLLECT_DEADLINE_S}s")
            self._add_note(f"Node {cli.name} exceeded collection deadline ({NODE_COLLECT_DEADLINE_S}s)")

        for cli in clients:
            if cli.notes:
                for n in cli.notes:
                    self._add_note(n)
            # A down node must still emit a status 0 row in every per-node table,
            # otherwise the console keeps its last (green) row for that node.
            if not cli.is_up:
                cli.activity_row = {"name": cli.name, "status": 0}
                cli.io_row = {"name": cli.name, "status": 0}
                cli.transactions_row = {"name": cli.name, "status": 0}
                cli.checkpoints_row = {"name": cli.name, "status": 0}
                cli.conflicts_row = None

        nodes_up = sum(1 for c in clients if c.is_up)
        primary_candidates = [c for c in clients if c.is_up and c.is_primary]
        primary_count = len(primary_candidates)
        no_primary_flag = 1 if primary_count == 0 else 0
        split_brain_flag = 1 if primary_count > 1 else 0

        active_primary = primary_candidates[0] if primary_count >= 1 else None
        primary_timeline = active_primary.timeline if (active_primary and active_primary.timeline is not None) else 0

        # Timeline Mismatch Flag: any up node has timeline differing from primary
        timeline_mismatch_flag = 0
        if primary_timeline > 0:
            for c in clients:
                if c.is_up and not getattr(c, 'is_witness', False) and getattr(c, 'discovered_role', '') != 'witness' and c.timeline is not None and c.timeline != primary_timeline:
                    timeline_mismatch_flag = 1
                    self._add_note(f"Timeline mismatch: node {c.name} (TL {c.timeline}) != primary (TL {primary_timeline})")
                    break

        # Evidence aggregation
        agg_evidence = {
            "extensions": [],
            "repmgr_table": False,
            "managed_roles": [],
            "aurora_version": False,
            "slot_names": [],
            "slot_types": [],
            "logical_replication_count": 0,
            "primary_count": primary_count,
            "app_names": [],
            "total_nodes": nodes_total,
            "is_in_recovery": any(not c.is_primary for c in clients if c.is_up),
            "has_standbys": False,
            "has_replication_slots": False,
            "standby_count": 0
        }
        patroni_scope_discovered = None
        for c in clients:
            if c.patroni_info and c.patroni_info.get("is_patroni"):
                agg_evidence["patroni"] = c.patroni_info
                patroni_scope_discovered = c.patroni_info.get("scope")
                break

        for c in clients:
            if c.is_up:
                ev = c.evidence
                agg_evidence["extensions"].extend(ev.get("extensions", []))
                agg_evidence["subscriptions_count"] = agg_evidence.get("subscriptions_count", 0) + ev.get("subscriptions_count", 0)
                agg_evidence["publications_count"] = agg_evidence.get("publications_count", 0) + ev.get("publications_count", 0)
                if ev.get("repmgr_table"):
                    agg_evidence["repmgr_table"] = True
                agg_evidence["managed_roles"].extend(ev.get("managed_roles", []))
                if ev.get("aurora_version"):
                    agg_evidence["aurora_version"] = True
                agg_evidence["slot_names"].extend(ev.get("slot_names", []))
                agg_evidence["slot_types"].extend(ev.get("slot_types", []))
                agg_evidence["logical_replication_count"] += ev.get("logical_replication_count", 0)
                agg_evidence["app_names"].extend(ev.get("app_names", []))

        agg_evidence["extensions"] = list(set(agg_evidence["extensions"]))
        agg_evidence["managed_roles"] = list(set(agg_evidence["managed_roles"]))
        agg_evidence["slot_names"] = list(set(agg_evidence["slot_names"]))
        agg_evidence["slot_types"] = list(set(agg_evidence["slot_types"]))
        agg_evidence["app_names"] = list(set(agg_evidence["app_names"]))
        agg_evidence["all_up_subscribe"] = all(c.evidence.get("has_sub", False) for c in clients if c.is_up) if nodes_up >= 2 else False
        agg_evidence["all_up_publish"] = all(c.evidence.get("has_pub", False) for c in clients if c.is_up) if nodes_up >= 2 else False

        # Cluster Type Detection
        if self.cluster_type_override and self.cluster_type_override != 'auto':
            detected_type = self.cluster_type_override
            detected_evidence = f"Explicit override via cluster_type parameter ({self.cluster_type_override})"
        else:
            detected_type, detected_evidence = detect_cluster_type(agg_evidence)

        if detected_type not in SUPPORTED_CLUSTER_TYPES:
            raise UnsupportedClusterError(detected_type, detected_evidence)

        # In multi-master / active-active topologies, multiple concurrent primaries are expected
        c_lower = str(detected_type).lower()
        if "multi-master" in c_lower or "multimaster" in c_lower or "active-active" in c_lower or "bdr" in c_lower or "citus" in c_lower:
            split_brain_flag = 0

        # Build Cluster_Nodes child table
        cluster_nodes = []
        is_mm = ("multi-master" in str(detected_type).lower())
        for c in clients:
            role_str = "offline"
            if getattr(c, 'is_witness', False) or getattr(c, 'discovered_role', '') == "witness":
                role_str = "witness" if c.is_up else "witness (offline)"
            elif c.is_up:
                if is_mm:
                    role_str = "master"
                else:
                    role_str = "primary" if c.is_primary else "standby"

            upstream_val = str(c.upstream if c.upstream else "none")
            if c.is_cascading and "cascading" not in upstream_val.lower():
                upstream_val = f"{upstream_val} (cascading)" if upstream_val != "none" else "cascading"

            node_row = {
                "name": c.name,
                "role": role_str,
                "is_primary": 1 if (c.is_up and (c.is_primary or is_mm) and not getattr(c, 'is_witness', False)) else 0,
                "status": 1 if c.is_up else 0,
                "timeline": int(c.timeline) if c.timeline is not None else 0,
                "connections": int(c.connections) if c.connections is not None else 0,
                "response_time_ms": float(c.response_time_ms),
                "upstream": upstream_val,
                "patroni_state": str(c.patroni_state if c.patroni_state else "none"),
                "replay_backlog_bytes": max(0, int(c.replay_backlog_bytes)) if (c.is_up and c.replay_backlog_bytes is not None) else 0,
                "replay_delay_s": max(0.0, float(c.replay_delay_s)) if (c.is_up and c.replay_delay_s is not None) else 0.0,
                "monitored": 1 if c.is_up else 0
            }
            if c.is_up and c.is_primary and not is_mm:
                node_row.pop("replay_backlog_bytes", None)
                node_row.pop("replay_delay_s", None)
            cluster_nodes.append(node_row)

        node_io_table = [c.io_row for c in clients if c.io_row is not None]
        node_checkpoints_table = [c.checkpoints_row for c in clients if c.checkpoints_row is not None]
        node_activity_table = [c.activity_row for c in clients if c.activity_row is not None]
        node_transactions_table = [c.transactions_row for c in clients if c.transactions_row is not None]

        # Replication links and slots
        replication_links = []
        replication_slots = []
        sync_standbys_count = 0
        cascading_standbys_count = sum(c.is_cascading for c in clients if c.is_up and not c.is_primary)
        max_replay_backlog = 0
        max_replay_delay_s = 0.0
        slots_total = 0
        slots_active = 0
        slots_inactive = 0
        max_slot_lag_bytes = 0
        max_wal_status_risk = 0
        has_wal_status = False

        # Multi-master top-level metrics
        mesh_links_declared = 0
        mesh_links_active = 0
        mesh_disconnect_flag = 0
        max_logical_lag_bytes = 0
        max_logical_lag_seconds = 0.0
        subscription_apply_errors = 0
        subscription_conflicts = 0

        member_to_name = {c.patroni_member: c.name for c in clients if c.patroni_member}

        if is_mm:
            # Multi-Master topology: links come from subscriptions on all up nodes
            split_brain_flag = 0
            no_primary_flag = 0 if nodes_up > 0 else 1
            active_primary = primary_candidates[0] if primary_candidates else (clients[0] if clients and clients[0].is_up else None)

            # 1. Collect Replication_Links
            for c in clients:
                if not c.is_up:
                    continue
                for sub in c.subscriptions:
                    mesh_links_declared += 1
                    is_act = sub["active"]
                    if is_act:
                        mesh_links_active += 1
                    state = "streaming" if is_act else ("disabled" if not sub["enabled"] else "stopped")
                    lag_s = max(0.0, float(sub.get("receipt_delay_s", 0.0)))
                    if lag_s > max_logical_lag_seconds:
                        max_logical_lag_seconds = lag_s
                    subscription_apply_errors += sub.get("apply_error_count", 0)
                    subscription_conflicts += sub.get("sync_error_count", 0)

                    source_node = "unknown"
                    if sub.get("conninfo"):
                        sh, sp = parse_conninfo_hostport(sub["conninfo"])
                        if sh:
                            source_node = safe_name(sh)
                    if source_node == "unknown" and "_from_" in sub["subname"]:
                        source_node = safe_name(sub["subname"].split("_from_")[-1])

                    replication_links.append({
                        "name": safe_name(sub["subname"]),
                        "link_type": "logical_subscription",
                        "source": source_node,
                        "target": c.name,
                        "state": state,
                        "sync_state": "async",
                        "client_addr": "unknown",
                        "replay_lag_bytes": 0,
                        "write_lag_bytes": 0,
                        "flush_lag_bytes": 0,
                        "replay_lag_s": lag_s,
                        "is_sync": 0,
                        "active": is_act,
                        "status": 1 if is_act else 0
                    })

                # Also aggregate walsender lag
                for ws in c.logical_walsenders:
                    wlag = ws["replay_lag_bytes"]
                    if wlag > max_logical_lag_bytes:
                        max_logical_lag_bytes = wlag
                    wlag_s = ws["replay_lag_s"]
                    if wlag_s > max_logical_lag_seconds:
                        max_logical_lag_seconds = wlag_s

            if mesh_links_active < mesh_links_declared:
                mesh_disconnect_flag = 1
                self._add_note(f"Mesh disconnect: {mesh_links_declared - mesh_links_active} link(s) inactive")

            # 2. Collect Replication_Slots across ALL up nodes
            for c in clients:
                if not c.is_up:
                    continue
                for sl in c.logical_slots:
                    slots_total += 1
                    is_act = sl["active"]
                    if is_act:
                        slots_active += 1
                    else:
                        slots_inactive += 1
                    retained = sl["wal_retained_bytes"]
                    if retained > max_slot_lag_bytes:
                        max_slot_lag_bytes = retained

                    unique_name = safe_name(f"{c.name}_{sl['slot_name']}")
                    replication_slots.append({
                        "name": unique_name,
                        "plugin": sl["plugin"],
                        "slot_type": sl["slot_type"],
                        "active": is_act,
                        "wal_retained_bytes": retained,
                        "status": 1
                    })

        elif active_primary and active_primary.conn:
            # Physical streaming replication: links from pg_stat_replication
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("""
                        SELECT COALESCE(application_name, 'unknown'),
                               COALESCE(client_addr::text, 'unknown'),
                               COALESCE(state, 'unknown'),
                               COALESCE(sync_state, 'unknown'),
                               sync_priority,
                               ROUND(COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn), 0)::numeric, 0),
                               ROUND(COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), write_lsn), 0)::numeric, 0),
                               ROUND(COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), flush_lsn), 0)::numeric, 0),
                               ROUND(COALESCE(EXTRACT(EPOCH FROM replay_lag), 0)::numeric, 2)
                        FROM pg_stat_replication;
                    """)
                    for r in cur.fetchall():
                        is_sync = 1 if r[3] in ('sync', 'quorum') else 0
                        if is_sync:
                            sync_standbys_count += 1
                        rep_lag_bytes = max(0, int(r[5] or 0))
                        w_lag_bytes = max(0, int(r[6] or 0))
                        f_lag_bytes = max(0, int(r[7] or 0))
                        rep_lag_s = max(0.0, float(r[8] or 0.0))
                        if rep_lag_bytes > max_replay_backlog:
                            max_replay_backlog = rep_lag_bytes
                        if rep_lag_s > max_replay_delay_s:
                            max_replay_delay_s = rep_lag_s

                        app_name = str(r[0] or "").strip()
                        standby_name = member_to_name.get(app_name) or safe_name(app_name) or "standby"

                        replication_links.append({
                            "name": standby_name,
                            "link_type": "physical_streaming",
                            "source": active_primary.name,
                            "target": standby_name,
                            "state": str(r[2]),
                            "sync_state": str(r[3] or "async"),
                            "replay_lag_bytes": rep_lag_bytes,
                            "write_lag_bytes": w_lag_bytes,
                            "flush_lag_bytes": f_lag_bytes,
                            "replay_lag_s": rep_lag_s,
                            "is_sync": is_sync,
                            "active": 1,
                            "status": 1
                        })
                agg_evidence["has_standbys"] = len(replication_links) > 0
                agg_evidence["standby_count"] = len(replication_links)
            except Exception as e:
                self._add_note(f"Standbys query error: {e}")

            # 2. Replication slots on primary
            try:
                with active_primary.conn.cursor() as cur:
                    try:
                        cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'pg_replication_slots' AND column_name = 'wal_status';")
                        has_wal_status = bool(cur.fetchone())
                    except Exception:
                        has_wal_status = False

                    if has_wal_status:
                        cur.execute("""
                            SELECT slot_name,
                                   COALESCE(plugin, 'none'),
                                   COALESCE(slot_type, 'physical'),
                                   CASE WHEN active = true THEN 1 ELSE 0 END,
                                   ROUND(COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn), 0)::numeric, 0),
                                   COALESCE(wal_status, 'none')
                            FROM pg_replication_slots;
                        """)
                    else:
                        cur.execute("""
                            SELECT slot_name,
                                   COALESCE(plugin, 'none'),
                                   COALESCE(slot_type, 'physical'),
                                   CASE WHEN active = true THEN 1 ELSE 0 END,
                                   ROUND(COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn), 0)::numeric, 0)
                            FROM pg_replication_slots;
                        """)
                    for r in cur.fetchall():
                        slots_total += 1
                        is_act = int(r[3] or 0)
                        if is_act:
                            slots_active += 1
                        else:
                            slots_inactive += 1
                        retained = int(r[4] or 0)
                        if retained > max_slot_lag_bytes:
                            max_slot_lag_bytes = retained

                        slot_row = {
                            "name": safe_name(str(r[0])) or str(r[0]),
                            "plugin": str(r[1]),
                            "slot_type": str(r[2]),
                            "active": is_act,
                            "wal_retained_bytes": retained,
                            "status": is_act
                        }
                        if has_wal_status and len(r) > 5:
                            w_st = str(r[5]).lower()
                            slot_row["wal_status"] = w_st
                            risk = 0
                            if w_st == "lost":
                                risk = 2
                            elif w_st == "unreserved":
                                risk = 1
                            if risk > max_wal_status_risk:
                                max_wal_status_risk = risk

                        replication_slots.append(slot_row)
                agg_evidence["has_replication_slots"] = slots_total > 0
            except Exception as e:
                self._add_note(f"Slots query error: {e}")

        # Common queries on primary / reference node
        if active_primary and active_primary.conn:
            # 3. Server PID & Uptime
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT pg_backend_pid();")
                    results["Server PID"] = int(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"Server PID query: {e}")

            server_version_str = active_primary.server_version_str
            if server_version_str:
                results["Server Version"] = str(server_version_str)

            # 4. Standalone queries execution
            major_v = int(active_primary.server_version_num % 1000000 / 10000)
            middle_v = int(active_primary.server_version_num % 10000 / 100)
            std_queries = get_standalone_queries(major_v, middle_v)

            # Table count
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['table_count'])
                    results["Table Count"] = int(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"Table count: {e}")

            # Database count
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['no of databases'])
                    results["Database Count"] = int(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"Database count: {e}")

            # Locks count
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['locks_count'])
                    results["Locks Count"] = int(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"Locks count: {e}")

            # Active queries
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['active_queries'])
                    results["Active Queries"] = int(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"Active queries: {e}")

            # Active waiting queries
            if 'active_waiting_queries' in std_queries:
                try:
                    with active_primary.conn.cursor() as cur:
                        cur.execute(std_queries['active_waiting_queries'])
                        results["Active Waiting Queries"] = int(cur.fetchone()[0])
                except Exception as e:
                    self._add_note(f"Active waiting queries: {e}")

            # Transactions open & idle
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['transactions_open'])
                    results["Transactions Open"] = int(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"Transactions open: {e}")

            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['transacttions_idle'])
                    results["Transactions Idle In Transaction"] = int(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"Transactions idle: {e}")

            # Max connections & active connections from db_stats
            act_conn = 0
            max_conn = None
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['max_conn'])
                    max_conn = int(cur.fetchone()[0])
                    results["Max Connections"] = max_conn
            except Exception as e:
                self._add_note(f"Max connections: {e}")

            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['db_stats'])
                    r = cur.fetchone()
                    act_conn = int(r[0] or 0)
                    results["Active Connections"] = act_conn
                    results["Total Commits"] = int(r[1] or 0)
                    results["Total Rollbacks"] = int(r[2] or 0)
                    results["Total Conflicts"] = int(r[3] or 0)
                    if max_conn:
                        results["Connection Utilization Percent"] = round((act_conn / max_conn) * 100.0, 2)
            except Exception as e:
                self._add_note(f"Database stats: {e}")

            # IO stats
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['io_stats'])
                    r = cur.fetchone()
                    results["Total Rows Inserted"] = int(r[0] or 0)
                    results["Total Rows Updated"] = int(r[1] or 0)
                    results["Total Rows Deleted"] = int(r[2] or 0)
                    results["Total Rows Fetched"] = int(r[3] or 0)
                    results["Total Rows Returned"] = int(r[4] or 0)
                    results["Total Block Reads"] = int(r[5] or 0)
                    results["Total Block Hits"] = int(r[6] or 0)
            except Exception as e:
                self._add_note(f"IO stats: {e}")

            # Heap and cache hit ratio (0-1 ratio as in postgres.py)
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['heap_and_cache'])
                    r = cur.fetchone()
                    results["Heap Blocks Read"] = int(r[0] or 0)
                    results["Heap Blocks Hit"] = int(r[1] or 0)
                    results["Cache Hit Ratio"] = float(round(float(r[2] or 0.0), 4))
            except Exception as e:
                self._add_note(f"Heap and cache: {e}")

            # Index stats
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['idx_stats'])
                    r = cur.fetchone()
                    results["Index Scans"] = int(r[0] or 0)
                    results["Index Rows Read"] = int(r[1] or 0)
                    results["Index Rows Fetched"] = int(r[2] or 0)
            except Exception as e:
                self._add_note(f"Index stats: {e}")

            # Uptime
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT FLOOR(EXTRACT(EPOCH FROM current_timestamp - pg_postmaster_start_time())) as uptime;")
                    results["Uptime"] = int(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"Uptime: {e}")

            # Checkpoints (PG 17 uses pg_stat_checkpointer, older uses pg_stat_bgwriter)
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['checkpoints'])
                    r = cur.fetchone()
                    results["Checkpoints Timed"] = int(r[0] or 0)
                    results["Checkpoints Req"] = int(r[1] or 0)
                    results["Checkpoint Write Time"] = int(r[2] or 0)
                    results["Checkpoint Sync Time"] = int(r[3] or 0)
                    results["Buffers Checkpoint"] = int(r[4] or 0)
            except Exception as e:
                self._add_note(f"Checkpoints: {e}")

            # BGWriter
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['bg_stats'])
                    r = cur.fetchone()
                    results["Buffers Clean"] = int(r[0] or 0)
                    results["Maxwritten Clean"] = int(r[1] or 0)
                    results["Buffers Backend"] = int(r[2] or 0)
                    results["Buffers Backend Fsync"] = int(r[3] or 0)
                    results["Buffers Alloc"] = int(r[4] or 0)
            except Exception as e:
                self._add_note(f"BG stats: {e}")

            # Sessions (PG 14+)
            if 'session' in std_queries:
                try:
                    with active_primary.conn.cursor() as cur:
                        cur.execute(std_queries['session'])
                        r = cur.fetchone()
                        results["Total Sessions"] = int(r[0] or 0)
                        results["Total Sessions Abandoned"] = int(r[1] or 0)
                        results["Total Sessions Fatal"] = int(r[2] or 0)
                        results["Total Sessions Killed"] = int(r[3] or 0)
                except Exception as e:
                    self._add_note(f"Sessions: {e}")

            # Oldest Running Transaction Age
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT COALESCE(MAX(EXTRACT(EPOCH FROM now() - xact_start))::bigint, 0) FROM pg_stat_activity WHERE state <> 'idle';")
                    results["Oldest Running Transaction Age"] = int(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"Oldest xact age: {e}")

            # Dead tuples
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT COALESCE(sum(n_dead_tup), 0) FROM pg_stat_user_tables;")
                    results["Dead Tuples"] = int(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"Dead tuples: {e}")

            # Oldest Transaction ID Age
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT COALESCE(max(age(datfrozenxid)), 0)::bigint FROM pg_database WHERE datallowconn = true;")
                    results["Oldest Transaction ID Age"] = int(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"Oldest TxID age: {e}")

            # Logical Replication In Use
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT (SELECT count(*) FROM pg_publication) + (SELECT count(*) FROM pg_subscription);")
                    results["Logical Replication In Use"] = 1 if (cur.fetchone()[0] or 0) > 0 else 0
            except Exception:
                try:
                    with active_primary.conn.cursor() as cur:
                        cur.execute("SELECT count(*) FROM pg_publication;")
                        results["Logical Replication In Use"] = 1 if (cur.fetchone()[0] or 0) > 0 else 0
                except Exception as e:
                    self._add_note(f"Logical replication query: {e}")

            # Archiving & WAL (Always emit Archive Mode)
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT current_setting('archive_mode');")
                    results["Archive Mode"] = str(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"Archive mode: {e}")

            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT archived_count, failed_count, last_archived_wal FROM pg_stat_archiver;")
                    r = cur.fetchone()
                    if r and r[0] is not None:
                        results["Archive Status Success"] = int(r[0] or 0)
                        results["Archive Status Failed"] = int(r[1] or 0)
                        results["Last Archived WAL File"] = str(r[2]) if r[2] else "none"
            except Exception as e:
                self._add_note(f"pg_stat_archiver: {e}")

            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM pg_ls_archive_statusdir() WHERE name LIKE '%.ready';")
                    results["Archive Ready Files Count"] = int(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"pg_ls_archive_statusdir: {e}")

            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT ROUND(pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0') / 1024.0 / 1024.0, 2);")
                    results["WAL Write Position"] = float(cur.fetchone()[0] or 0.0)
            except Exception as e:
                self._add_note(f"WAL Write Position: {e}")

            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT ROUND(pg_wal_lsn_diff(pg_current_wal_insert_lsn(), '0/0') / 1024.0 / 1024.0, 2);")
                    results["WAL Insert Position"] = float(cur.fetchone()[0] or 0.0)
            except Exception as e:
                self._add_note(f"WAL Insert Position: {e}")

            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT ROUND(pg_wal_lsn_diff(pg_current_wal_flush_lsn(), '0/0') / 1024.0 / 1024.0, 2);")
                    results["WAL Flush Position"] = float(cur.fetchone()[0] or 0.0)
            except Exception as e:
                self._add_note(f"WAL Flush Position: {e}")

            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT count(*), ROUND(COALESCE(sum(size), 0) / 1024.0 / 1024.0, 2) FROM pg_ls_waldir() WHERE name ~ '^[0-9A-Fa-f]{24}$';")
                    r = cur.fetchone()
                    results["WAL Files Count"] = int(r[0] or 0)
                    results["WAL Total Size"] = float(r[1] or 0.0)
            except Exception as e:
                self._add_note(f"pg_ls_waldir: {e}")

            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT sum(confl_tablespace), sum(confl_lock), sum(confl_snapshot), sum(confl_bufferpin), sum(confl_deadlock) FROM pg_stat_database_conflicts;")
                    r = cur.fetchone()
                    c_tsp = int(r[0] or 0)
                    c_lck = int(r[1] or 0)
                    c_snp = int(r[2] or 0)
                    c_buf = int(r[3] or 0)
                    c_ddl = int(r[4] or 0)
                    results["Conflicts Tablespace"] = c_tsp
                    results["Conflicts Lock"] = c_lck
                    results["Conflicts Snapshot"] = c_snp
                    results["Conflicts Buffer Pin"] = c_buf
                    results["Conflicts Deadlock"] = c_ddl
                    results["Recovery Conflicts Total"] = sum([c_tsp, c_lck, c_snp, c_buf, c_ddl])
            except Exception as e:
                self._add_note(f"pg_stat_database_conflicts: {e}")

            # Child discovery tables: Stats_per_DB and Tranasctions_and_Session_per_Database
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['per_db_stats'])
                    db_cols = [desc[0] for desc in cur.description]
                    db_stats_rows = []
                    for row in cur.fetchall():
                        r_dict = {}
                        for i, col in enumerate(db_cols):
                            r_dict[col] = safe_name(str(row[i])) if col == 'name' else (float(row[i] or 0.0) if col == 'size_in_mb' else int(row[i] or 0))
                        db_stats_rows.append(r_dict)
                    results["Stats_per_DB"] = db_stats_rows[:25]
            except Exception as e:
                self._add_note(f"Stats_per_DB: {e}")

            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['per_db_trans'])
                    tx_cols = [desc[0] for desc in cur.description]
                    tx_stats_rows = []
                    for row in cur.fetchall():
                        r_dict = {}
                        for i, col in enumerate(tx_cols):
                            if col == 'name':
                                r_dict[col] = safe_name(str(row[i]))
                            elif 'time' in col:
                                r_dict[col] = float(row[i] or 0.0)
                            else:
                                r_dict[col] = int(row[i] or 0)
                        tx_stats_rows.append(r_dict)
                    results["Tranasctions_and_Session_per_Database"] = tx_stats_rows[:25]
            except Exception as e:
                self._add_note(f"Tranasctions_and_Session_per_Database: {e}")

        else:
            self._add_note("Cluster alert: No reachable primary node detected")

        # Standbys counts
        witness_count = sum(1 for c in clients if getattr(c, 'is_witness', False) or getattr(c, 'discovered_role', '') == "witness")
        standbys_expected = max(0, nodes_total - primary_count - witness_count) if not is_mm else 0
        standbys_streaming = (len(replication_links) + cascading_standbys_count) if not is_mm else 0
        standby_disconnect_flag = 1 if standbys_expected > standbys_streaming else 0

        # Check all standbys' local backlog as well
        for c in clients:
            if c.is_up and not c.is_primary and c.replay_backlog_bytes is not None:
                if c.replay_backlog_bytes > max_replay_backlog:
                    max_replay_backlog = c.replay_backlog_bytes
                if c.replay_delay_s is not None and c.replay_delay_s > max_replay_delay_s:
                    max_replay_delay_s = c.replay_delay_s

        max_replay_backlog = max(0, max_replay_backlog)
        max_replay_delay_s = max(0.0, max_replay_delay_s)
        max_slot_lag_bytes = max(0, max_slot_lag_bytes)

        if nodes_up == 0:
            results["status"] = 0

        # Failover History (Part A)
        seconds_since_last_failover = None
        failovers_last_24h = 0
        last_failover_to = "none"
        last_failover_timeline = None

        if agg_evidence.get("patroni", {}).get("is_patroni"):
            for c in clients:
                if c.is_up and c.patroni_port and str(c.patroni_port) != "none":
                    hist_data = _http_json(f"http://{c.hostname}:{c.patroni_port}/history", timeout=1.5)
                    if isinstance(hist_data, list) and hist_data:
                        entries = [e for e in hist_data if isinstance(e, list) and len(e) >= 5]
                        if entries:
                            entries.sort(key=lambda x: int(x[0]))
                            last_tl, last_lsn, last_reason, last_ts, last_leader = entries[-1]
                            try:
                                from datetime import datetime, timezone
                                ts_clean = str(last_ts).replace("Z", "+00:00")
                                dt = datetime.fromisoformat(ts_clean)
                                now = datetime.now(timezone.utc)
                                seconds_since_last_failover = max(0, int((now - dt).total_seconds()))
                                last_failover_timeline = int(last_tl)

                                for e in entries:
                                    try:
                                        e_dt = datetime.fromisoformat(str(e[3]).replace("Z", "+00:00"))
                                        if (now - e_dt).total_seconds() <= 86400:
                                            failovers_last_24h += 1
                                    except Exception:
                                        pass
                            except Exception:
                                pass

                            matched_alias = None
                            for nd in node_defs:
                                if nd[0].lower() == str(last_leader).lower() or safe_name(last_leader).lower() == nd[0].lower():
                                    matched_alias = nd[0]
                                    break
                            last_failover_to = matched_alias or safe_name(last_leader) or "none"
                        break
        elif "repmgr" in str(detected_type).lower() or agg_evidence.get("repmgr_table"):
            # Query repmgr.events for promote / failover history
            repmgr_conn = None
            close_rc = False
            probe_clients = [c for c in clients if c.is_up and c.is_primary] + [c for c in clients if c.is_up and not c.is_primary]
            for pc in probe_clients:
                try:
                    with pc.conn.cursor() as cur:
                        cur.execute("SELECT to_regclass('repmgr.events') IS NOT NULL;")
                        r = cur.fetchone()
                        if r and r[0]:
                            repmgr_conn = pc.conn
                            break
                except Exception:
                    pass
                if not repmgr_conn:
                    try:
                        with pc.conn.cursor() as cur:
                            cur.execute("SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate AND datname != current_database();")
                            cands = [row[0] for row in cur.fetchall()]
                        for cand in cands:
                            try:
                                c = _pg_connect(pc.hostname, pc.port, self.username, self.password, cand)
                                with c.cursor() as cur:
                                    cur.execute("SELECT to_regclass('repmgr.events') IS NOT NULL;")
                                    r = cur.fetchone()
                                    if r and r[0]:
                                        repmgr_conn = c
                                        close_rc = True
                                        break
                                c.close()
                            except Exception:
                                continue
                        if repmgr_conn:
                            break
                    except Exception:
                        pass

            if repmgr_conn:
                try:
                    with repmgr_conn.cursor() as cur:
                        cur.execute("""
                            SELECT e.node_id, e.event, e.successful, e.event_timestamp, e.details, n.node_name
                            FROM repmgr.events e
                            LEFT JOIN repmgr.nodes n ON e.node_id = n.node_id
                            WHERE e.event IN ('repmgrd_failover_promote', 'standby_promote', 'standby_switchover')
                              AND e.successful = true
                            ORDER BY e.event_timestamp DESC;
                        """)
                        ev_rows = cur.fetchall()
                        if ev_rows:
                            from datetime import datetime, timezone
                            now = datetime.now(timezone.utc)
                            last_ts = ev_rows[0][3]
                            last_leader = ev_rows[0][5]
                            if hasattr(last_ts, 'tzinfo') and last_ts.tzinfo:
                                dt = last_ts.astimezone(timezone.utc)
                            else:
                                dt = datetime.fromisoformat(str(last_ts).replace("Z", "+00:00"))
                            seconds_since_last_failover = max(0, int((now - dt).total_seconds()))
                            last_failover_timeline = int(primary_timeline) if primary_timeline else 1

                            for er in ev_rows:
                                ets = er[3]
                                if hasattr(ets, 'tzinfo') and ets.tzinfo:
                                    edt = ets.astimezone(timezone.utc)
                                else:
                                    edt = datetime.fromisoformat(str(ets).replace("Z", "+00:00"))
                                if (now - edt).total_seconds() <= 86400:
                                    failovers_last_24h += 1

                            matched_alias = None
                            for nd in node_defs:
                                if nd[0].lower() == str(last_leader).lower() or safe_name(last_leader).lower() == nd[0].lower():
                                    matched_alias = nd[0]
                                    break
                            last_failover_to = matched_alias or safe_name(last_leader) or "none"
                except Exception as e:
                    self._add_note(f"repmgr.events failover history query: {e}")
                finally:
                    if close_rc and repmgr_conn:
                        try:
                            repmgr_conn.close()
                        except Exception:
                            pass

        # Close all client connections after all probes and failover queries complete
        for cli in clients:
            cli.close()

        # Health Evaluation
        health_code, health_reason = evaluate_cluster_health(
            nodes_total=nodes_total,
            nodes_up=nodes_up,
            primary_count=primary_count,
            no_primary_flag=no_primary_flag,
            split_brain_flag=split_brain_flag,
            standbys_expected=standbys_expected,
            standbys_streaming=standbys_streaming,
            max_replay_delay_s=max_replay_delay_s,
            max_replay_backlog=max_replay_backlog,
            slots_inactive=slots_inactive,
            timeline_mismatch_flag=timeline_mismatch_flag,
            cluster_type=detected_type,
            mesh_disconnect_flag=mesh_disconnect_flag,
            subscription_apply_errors=subscription_apply_errors,
            slots_info=replication_slots,
            slot_warn_bytes=self.slot_warn_bytes,
            slot_critical_bytes=self.slot_critical_bytes,
            seconds_since_last_failover=seconds_since_last_failover,
            last_failover_to=last_failover_to,
            last_failover_timeline=last_failover_timeline,
            failover_warn_seconds=self.failover_warn_seconds
        )
        results["Cluster Health"] = int(health_code)

        results["Nodes Total"] = int(nodes_total)
        results["Nodes Up"] = int(nodes_up)
        results["Primary Count"] = int(primary_count)
        results["No Primary Flag"] = int(no_primary_flag)
        results["Split Brain Flag"] = int(split_brain_flag)
        results["Primary Timeline"] = int(primary_timeline)
        results["Timeline Mismatch Flag"] = int(timeline_mismatch_flag)

        results["Standbys Expected"] = int(standbys_expected)
        results["Standbys Streaming"] = int(standbys_streaming)
        results["Standby Disconnect Flag"] = int(standby_disconnect_flag)
        results["Sync Standby Count"] = int(sync_standbys_count)
        results["Cascading Standby Count"] = int(cascading_standbys_count)
        results["Max Replay Backlog"] = int(max_replay_backlog)
        results["Max Replay Delay"] = float(round(max_replay_delay_s, 2))

        results["Replication Slots Total"] = int(slots_total)
        results["Replication Slots Active"] = int(slots_active)
        results["Replication Slots Inactive"] = int(slots_inactive)
        results["Max Slot Lag Bytes"] = int(max_slot_lag_bytes)
        if has_wal_status:
            results["Slot Wal Status Risk"] = int(max_wal_status_risk)

        if seconds_since_last_failover is not None:
            results["Seconds Since Last Failover"] = int(seconds_since_last_failover)
            results["Last Failover Timeline"] = int(last_failover_timeline)
        results["Failovers Last 24h"] = int(failovers_last_24h)
        results["Last Failover To"] = str(last_failover_to)

        # Multi-master metrics
        results["Mesh Links Declared"] = int(mesh_links_declared)
        results["Mesh Links Active"] = int(mesh_links_active)
        results["Mesh Disconnect Flag"] = int(mesh_disconnect_flag)
        results["Max Logical Lag Bytes"] = int(max_logical_lag_bytes)
        results["Max Logical Lag Seconds"] = float(round(max_logical_lag_seconds, 2))
        results["Subscription Apply Errors"] = int(subscription_apply_errors)
        results["Subscription Conflicts"] = int(subscription_conflicts)

        # Tabular Data (Enforce Site24x7 25-row limit)
        results["Cluster_Info"] = [{
            "name": safe_name(str(patroni_scope_discovered or "postgrescluster")) or "cluster",
            "cluster_type": str(detected_type)[:99],
            "type_evidence": _evidence_with_discovery(detected_evidence, nodes_total, self.discovery_added, self.discovery_source),
            "server_version": str(server_version_str)[:99],
            "primary_node": active_primary.name if active_primary else "none",
            "health_reason": str(health_reason)[:99],
            "nodes_total": int(nodes_total),
            "nodes_up": int(nodes_up),
            "primary_timeline": int(primary_timeline),
            "status": 1 if nodes_up else 0,
        }]
        results["Cluster_Nodes"] = cluster_nodes[:25]
        results["Replication_Links"] = replication_links[:25]
        results["Replication_Slots"] = replication_slots[:25]
        results["Node_IO"] = node_io_table[:25]
        results["Node_Checkpoints"] = node_checkpoints_table[:25]
        results["Node_Activity"] = node_activity_table[:25]
        results["Node_Transactions"] = node_transactions_table[:25]

        # Site24x7 Child Discovery
        results["s247config"] = {
            "childdiscovery": [
                "Tranasctions_and_Session_per_Database",
                "Stats_per_DB"
            ]
        }

        # Apply tabs and nested units
        results.update(copy.deepcopy(tabs))
        results["units"] = units

        if self.msg_notes:
            results["msg"] = "; ".join(self.msg_notes[:5])

        return results


def run(param):
    """Site24x7 agent Python plugin entrypoint."""
    try:
        param = param or {}
        nodes = str(param.get("nodes") or "").strip()
        username = str(param.get("username") or "").strip()
        password = str(param.get("password") or "")
        db = str(param.get("db") or "").strip()
        patroni_port = str(param.get("patroni_port") or "").strip()
        cluster_type = param.get("cluster_type") or CLUSTER_TYPE
        discover = param.get("discover") or DISCOVER
        address_map = str(param.get("address_map") or ADDRESS_MAP).strip()
        failover_warn_seconds = int(param.get("failover_warn_seconds") if param.get("failover_warn_seconds") is not None else FAILOVER_WARN_SECONDS)
        slot_warn_bytes = int(param.get("slot_warn_bytes") if param.get("slot_warn_bytes") is not None else SLOT_WARN_BYTES)
        slot_critical_bytes = int(param.get("slot_critical_bytes") if param.get("slot_critical_bytes") is not None else SLOT_CRITICAL_BYTES)

        missing = [k for k, v in (("nodes", nodes), ("username", username), ("db", db)) if not v]
        if missing:
            return {
                "plugin_version": PLUGIN_VERSION,
                "heartbeat_required": HEARTBEAT,
                "status": 0,
                "msg": "Missing required setting(s): " + ", ".join(missing) + ". Set them in postgres_cluster.cfg."
            }

        collector = PostgresClusterCollector(nodes, username, password, db, patroni_port, cluster_type, discover, address_map=address_map, failover_warn_seconds=failover_warn_seconds, slot_warn_bytes=slot_warn_bytes, slot_critical_bytes=slot_critical_bytes)
        return collector.collect()
    except ConfigError as e:
        return {
            "plugin_version": PLUGIN_VERSION,
            "heartbeat_required": HEARTBEAT,
            "status": 0,
            "msg": str(e)
        }
    except Exception as e:
        return {
            "plugin_version": PLUGIN_VERSION,
            "heartbeat_required": HEARTBEAT,
            "status": 0,
            "msg": f"Unexpected entrypoint exception: {type(e).__name__}: {str(e)}"
        }


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Site24x7 PostgreSQL Cluster Plugin")
    parser.add_argument('--nodes', help='Required. Comma-separated nodes (host:port, name=host:port, or host:port:patroni_port)', default=NODES)
    parser.add_argument('--username', help='Required. PostgreSQL monitoring username', default=USERNAME)
    parser.add_argument('--password', help='PostgreSQL password', default=PASSWORD)
    parser.add_argument('--db', help='Required. Database name', default=DB)
    parser.add_argument('--patroni_port', help='Patroni REST API port (empty if not Patroni)', default=PATRONI_PORT)
    parser.add_argument('--cluster_type', help='Cluster manager type (auto, Patroni, repmgr, etc.)', default=CLUSTER_TYPE)
    parser.add_argument('--discover', help="'auto' finds the other cluster nodes from the configured address(es); 'off' monitors only the listed nodes", default=DISCOVER)
    parser.add_argument('--address_map', help='Optional internal host:port=reachable host:port mappings for Docker/NAT', default=ADDRESS_MAP)
    parser.add_argument('--failover_warn_seconds', help='Failover warning window in seconds', type=int, default=FAILOVER_WARN_SECONDS)
    parser.add_argument('--slot_warn_bytes', help='Inactive slot warning threshold in bytes', type=int, default=SLOT_WARN_BYTES)
    parser.add_argument('--slot_critical_bytes', help='Inactive slot critical threshold in bytes', type=int, default=SLOT_CRITICAL_BYTES)
    args = parser.parse_args()

    param = {
        "nodes": args.nodes,
        "username": args.username,
        "password": args.password,
        "db": args.db,
        "patroni_port": args.patroni_port,
        "cluster_type": args.cluster_type,
        "discover": args.discover,
        "address_map": args.address_map,
        "failover_warn_seconds": args.failover_warn_seconds,
        "slot_warn_bytes": args.slot_warn_bytes,
        "slot_critical_bytes": args.slot_critical_bytes
    }

    try:
        result = run(param)
        print(json.dumps(result))
    except Exception as e:
        result = {
            "plugin_version": PLUGIN_VERSION,
            "heartbeat_required": HEARTBEAT,
            "status": 0,
            "msg": f"Unexpected execution exception: {type(e).__name__}: {str(e)}"
        }
        print(json.dumps(result))
    finally:
        sys.stdout.flush()
        os._exit(0)
