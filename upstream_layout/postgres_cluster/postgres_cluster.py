#!/usr/bin/python3

### This plugin is used for monitoring PostgreSQL Cluster
### Monitors multiple nodes, detects primary/standby roles, health, replication lag,
### replication slots, cluster manager type, per-node activity/throughput/checkpoints,
### and collects PostgreSQL performance metrics across all nodes.
###
### Language : Python
### Compatible with Site24x7 Linux and Windows Agents.

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

# Default cluster configuration
NODES = '127.0.0.1:5441:8001,127.0.0.1:5442:8002,127.0.0.1:5443:8003'  # host:port or alias=host:port:patroni_port
USERNAME = 'site24x7'                                                    # Monitoring username
PASSWORD = 'site24x7'                                                    # Monitoring password
DB = 'postgres'                                                          # Database name to connect to
PATRONI_PORT = '8008'                                                    # Optional Patroni REST API port or mapping
CLUSTER_TYPE = 'auto'                                                    # 'auto' or explicit override
DISCOVER = 'auto'                                                        # 'auto' finds the other cluster nodes from the configured address(es); 'off' monitors only the listed nodes
DISCOVERY_DEADLINE_S = 4                                                 # Max seconds spent discovering cluster members
MAX_NODES = 25                                                           # Site24x7 allows at most 25 rows per table
CONNECT_TIMEOUT = 2                                                      # Timeout for connecting to each node (seconds)
STATEMENT_TIMEOUT_MS = 3000                                              # Per-query statement timeout in PostgreSQL (ms)
NODE_COLLECT_DEADLINE_S = 15                                             # Maximum seconds allowed for all nodes collection

PLUGIN_VERSION = 1
HEARTBEAT = True

# Standard 5-Tab Layout for Site24x7 Console
tabs = {
    "tabs": {
        "Cluster": {"order": "1", "tablist": [
            "Cluster_Info", "Cluster_Nodes", "Nodes Total", "Primary Count", "Primary Timeline",
            "No Primary Flag", "Split Brain Flag", "Timeline Mismatch Flag", "Server PID"]},
        "Replication": {"order": "2", "tablist": [
            "Replication_Standbys", "Replication_Slots", "Standbys Expected", "Standbys Streaming",
            "Standby Disconnect Flag", "Sync Standby Count", "Cascading Standby Count",
            "Max Replay Backlog", "Max Replay Delay", "Replication Slots Total",
            "Replication Slots Active", "Replication Slots Inactive", "Max Slot Lag Bytes",
            "Logical Replication In Use"]},
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
    "Logical Replication In Use": "flag",
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
        "status": "status"
    },
    "Replication_Standbys": {
        "replay_lag_bytes": "bytes",
        "write_lag_bytes": "bytes",
        "flush_lag_bytes": "bytes",
        "replay_lag_s": "s",
        "is_sync": "flag",
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
        queries['bg_stats'] = "SELECT c.num_timed AS checkpoints_timed, c.num_requested AS checkpoints_req, c.write_time AS checkpoint_write_time, c.sync_time AS checkpoint_sync_time, c.buffers_written AS buffers_checkpoint, b.buffers_clean, b.maxwritten_clean, b.buffers_alloc FROM pg_stat_checkpointer c, pg_stat_bgwriter b;"
    else:
        queries['bg_stats'] = "SELECT checkpoints_timed,checkpoints_req,checkpoint_write_time,checkpoint_sync_time,buffers_checkpoint,buffers_clean,maxwritten_clean,buffers_backend,buffers_backend_fsync,buffers_alloc FROM pg_stat_bgwriter;"

    if major_version >= 14:
        queries['session'] = "SELECT SUM(sessions) as total_sessions, SUM(sessions_abandoned) as total_sessions_abandoned, SUM(sessions_fatal) as total_sessions_fatal, SUM(sessions_killed) as total_sessions_killed FROM pg_stat_database;"

    return queries


def evaluate_cluster_health(
    nodes_total, nodes_up, primary_count, no_primary_flag, split_brain_flag,
    standbys_expected, standbys_streaming, max_replay_delay_s, max_replay_backlog,
    slots_inactive, timeline_mismatch_flag, delay_threshold_s=60.0, backlog_threshold_bytes=104857600,
    cluster_type=None
):
    """
    Pure health evaluation function for unit testing and live monitoring.
    Returns (status_code: int, reason: str < 100 chars).
      0 = healthy
      1 = degraded
      2 = critical
    Rule precedence:
      Critical: No primary, split-brain (except multi-master), or zero streaming standbys when expected.
      Degraded: Node down, standby disconnected, lag over threshold, inactive slot, timeline mismatch.
      Healthy: All criteria satisfied.
    """
    is_multimaster = False
    if cluster_type:
        c_lower = str(cluster_type).lower()
        if "multi-master" in c_lower or "multimaster" in c_lower or "active-active" in c_lower or "bdr" in c_lower or "citus" in c_lower:
            is_multimaster = True

    # 1. Critical rules
    if primary_count == 0 or no_primary_flag == 1:
        return 2, "Critical: No active primary node detected"
    if not is_multimaster and (split_brain_flag == 1 or primary_count > 1):
        return 2, f"Critical: Split brain detected ({primary_count} primary nodes active)"
    if not is_multimaster and standbys_expected > 0 and standbys_streaming == 0:
        return 2, f"Critical: No streaming standbys connected ({standbys_expected} expected)"

    # 2. Degraded rules
    if nodes_up < nodes_total:
        return 1, f"Degraded: {nodes_total - nodes_up} of {nodes_total} node(s) offline"
    if not is_multimaster and standbys_streaming < standbys_expected:
        return 1, f"Degraded: {standbys_expected - standbys_streaming} of {standbys_expected} standby(s) not streaming"
    if max_replay_delay_s > delay_threshold_s:
        return 1, f"Degraded: Replay delay {max_replay_delay_s:.1f}s exceeds threshold ({delay_threshold_s:.0f}s)"
    if max_replay_backlog > backlog_threshold_bytes:
        mb = max_replay_backlog / (1024 * 1024)
        thresh_mb = backlog_threshold_bytes / (1024 * 1024)
        return 1, f"Degraded: Replay backlog {mb:.1f}MB exceeds threshold ({thresh_mb:.0f}MB)"
    if slots_inactive > 0:
        return 1, f"Degraded: {slots_inactive} inactive replication slot(s) found"
    if not is_multimaster and timeline_mismatch_flag == 1:
        return 1, "Degraded: Timeline mismatch detected across cluster nodes"

    # 3. Healthy rule
    if is_multimaster:
        return 0, f"Multi-master cluster healthy: {nodes_up}/{nodes_total} active master nodes replicating"
    return 0, f"Cluster healthy: {nodes_up}/{nodes_total} nodes active, {primary_count} primary, {standbys_streaming} standbys streaming"


def detect_cluster_type(evidence):
    """
    Pure evidence-based cluster type detection supporting all major architectures.
    Returns (detected_type: str, evidence_summary: str < 100 chars).
    """
    managers = []
    manager_evidences = []

    # 1. Patroni check
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
    app_names = evidence.get("app_names", [])

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
    if "bdr" in exts or ("pglogical" in exts and evidence.get("primary_count", 0) >= 2):
        found_ext = [e for e in exts if e in ("pglogical", "bdr")]
        managers.append("multi-master (pglogical/BDR)")
        manager_evidences.append(f"multi-master extension {found_ext} (Active-Active)")
    elif evidence.get("primary_count", 0) >= 2 and (
        evidence.get("logical_replication_count", 0) > 0 or
        any("logical" in str(s).lower() for s in evidence.get("slot_types", []))
    ):
        managers.append("Multi-Master (Active-Active)")
        manager_evidences.append(f"Active-Active logical replication mesh ({evidence.get('primary_count')} concurrent primaries)")

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

    # Fallbacks:
    has_standbys = evidence.get("has_standbys", False)
    has_slots = evidence.get("has_replication_slots", False)
    is_in_recovery = evidence.get("is_in_recovery", False)
    total_nodes = evidence.get("total_nodes", 1)

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
    def __init__(self, name, host, port, username, password, db, patroni_port=None, has_explicit_alias=False):
        self.name = name                               # Display name / alias in tables
        self.has_explicit_alias = has_explicit_alias
        self.raw_host = host
        self.hostname = "127.0.0.1" if host in ("localhost", "127.0.0.1") else host
        self.port = int(port)
        self.username = username
        self.password = password
        self.db = db
        self.patroni_port = patroni_port
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
            cur.execute("SHOW server_version;")
            self.server_version_str = cur.fetchone()[0]

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

                if self.is_primary:
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
            "app_names": [],
            "is_in_recovery": not self.is_primary,
            "upstream": "N/A",
            "is_cascading": 0
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
                        # repmgr usually keeps its catalog in its own database named 'repmgr'
                        cur.execute("SELECT 1 FROM pg_database WHERE datname = 'repmgr';")
                        if cur.fetchone() and _repmgr_via_database(self.hostname, self.port, self.username, self.password):
                            evidence["repmgr_table"] = True
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

                try:
                    cur.execute("SELECT slot_name, COALESCE(slot_type, 'physical') FROM pg_replication_slots;")
                    slot_rows = cur.fetchall()
                    evidence["slot_names"] = [r[0] for r in slot_rows]
                    evidence["slot_types"] = [r[1] for r in slot_rows]
                except Exception:
                    pass

                try:
                    cur.execute("SELECT (SELECT count(*) FROM pg_publication) + (SELECT count(*) FROM pg_subscription);")
                    evidence["logical_replication_count"] = int(cur.fetchone()[0] or 0)
                except Exception:
                    evidence["logical_replication_count"] = 0

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

                try:
                    cur.execute("SELECT application_name FROM pg_stat_replication;")
                    apps = [r[0] for r in cur.fetchall()]
                    evidence["app_names"] = apps
                    if not self.is_primary and len(apps) > 0:
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


def discover_via_patroni(host, patroni_port):
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
        members.append({"alias": safe_name(name), "member": str(name), "host": str(h), "port": int(p),
                        "patroni_port": pp, "source": "Patroni REST API"})
    return members, data.get("scope")


def _pg_connect(host, port, user, pw, db):
    import psycopg2
    conn = psycopg2.connect(dbname=db, user=user, password=pw, host=_norm_host(host) if _norm_host(host) == "127.0.0.1" else host,
                            port=int(port), connect_timeout=2, options="-c statement_timeout=2000")
    conn.autocommit = True
    return conn


def _conninfo_hostport(conninfo, default_port=5432):
    h = re.search(r"host=([^\s']+)", conninfo or "")
    p = re.search(r"port=(\d+)", conninfo or "")
    return (h.group(1) if h else None), int(p.group(1)) if p else default_port


def _alias_for(host, app, taken):
    """Readable alphanumeric name for a node found without an explicit name."""
    host = str(host)
    if app and str(app) not in ("walreceiver", "") and safe_name(app):
        base = safe_name(app)
    elif re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host):
        base = "node" + "".join(host.split(".")[-2:])
    else:
        base = safe_name(host.split(".")[0]) or "node"
    name, k = base, 2
    while name.lower() in taken:
        name, k = f"{base}{k}", k + 1
    taken.add(name.lower())
    return name


def _repmgr_via_database(host, port, user, pw):
    """repmgr keeps its catalog in a separate database (default name 'repmgr'). Returns its node list."""
    out = []
    try:
        conn = _pg_connect(host, port, user, pw, "repmgr")
    except Exception:
        return out
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT node_name, conninfo FROM repmgr.nodes ORDER BY node_id;")
            for name, conninfo in cur.fetchall():
                h, p = _conninfo_hostport(conninfo)
                if h:
                    out.append({"alias": safe_name(name), "member": str(name), "host": h, "port": p, "patroni_port": "none", "source": "repmgr.nodes"})
    except Exception:
        pass
    finally:
        try:
            conn.close()
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


def discover_via_sql(seeds, user, pw, db, deadline):
    """Walks the replication topology from the seeds. Returns (members, source)."""
    queue = [(h, int(p), None) for h, p in seeds]
    visited, visited_canon, found = set(), set(), OrderedDict()
    while queue and time.time() < deadline and len(found) < MAX_NODES:
        host, port, app = queue.pop(0)
        key = (_norm_host(host), port)
        if key in visited:
            continue
        visited.add(key)
        try:
            conn = _pg_connect(host, port, user, pw, db)
        except Exception:
            continue
        try:
            with conn.cursor() as cur:
                managed = _managed_members(cur, port)
                if not managed:
                    try:
                        cur.execute("SELECT 1 FROM pg_database WHERE datname = 'repmgr';")
                        if cur.fetchone():
                            managed = _repmgr_via_database(host, port, user, pw)
                    except Exception:
                        pass
                if managed:
                    return managed, managed[0]["source"]
                # The same server can be reached by hostname and by IP: identify it by its real address.
                try:
                    cur.execute("SELECT host(inet_server_addr()), inet_server_port();")
                    ra, rp = cur.fetchone()
                except Exception:
                    ra, rp = None, None
                canon = (ra or _norm_host(host), int(rp or port))
                if canon in visited_canon:
                    continue
                visited_canon.add(canon)
                alias = _alias_for(host, app, {v["alias"].lower() for v in found.values()})
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
                try:
                    cur.execute("SELECT host(client_addr), application_name FROM pg_stat_replication WHERE client_addr IS NOT NULL;")
                    for ca, an in cur.fetchall():
                        queue.append((ca, port, an))
                except Exception:
                    pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return list(found.values()), "streaming replication topology"


def discover_cluster_members(seeds, user, pw, db, deadline_s):
    """seeds: list of (host, pg_port, patroni_port). Returns (members, source, seed_names).
    seed_names maps (host, pg_port) of each Patroni seed to its Patroni member alias."""
    deadline = time.time() + deadline_s
    seed_names = {}
    pat_seeds = [(h, p, pat) for h, p, pat in seeds if pat and str(pat) != "none"]
    if pat_seeds:
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(pat_seeds) * 2))
        f_cluster = [(ex.submit(discover_via_patroni, h, pat), h, p) for h, p, pat in pat_seeds]
        f_name = [(ex.submit(_patroni_member_name, h, pat), h, p) for h, p, pat in pat_seeds]
        concurrent.futures.wait([f for f, _, _ in f_cluster + f_name], timeout=max(0.5, min(2.5, deadline - time.time())))
        for f, h, p in f_name:
            if f.done() and not f.exception() and f.result():
                seed_names[(_norm_host(h), int(p))] = safe_name(f.result())
        found = []
        for f, h, p in f_cluster:
            if f.done() and not f.exception() and f.result()[0]:
                found = f.result()[0]
                break
        ex.shutdown(wait=False, cancel_futures=True)
        if found:
            return found, "Patroni REST API", seed_names
    members, source = discover_via_sql([(h, p) for h, p, _ in seeds], user, pw, db, deadline)
    return members, source, seed_names


def _patroni_member_name(host, patroni_port):
    data = _http_json(f"http://{host}:{patroni_port}/patroni", timeout=1.0)
    return str(((data or {}).get("patroni") or {}).get("name") or "") or None



class PostgresClusterCollector:
    """
    Main collector coordinating concurrent node probes, cluster-level metrics,
    per-node tables, cluster type detection, and Site24x7 JSON packaging.
    """
    def __init__(self, nodes_str, username, password, db, patroni_port=PATRONI_PORT, cluster_type=CLUSTER_TYPE, discover=DISCOVER):
        self.nodes_str = nodes_str
        self.username = username
        self.password = password
        self.db = db
        self.patroni_port = patroni_port
        self.cluster_type_override = cluster_type
        self.discover = discover
        self.discovery_added = 0
        self.discovery_source = ""
        self.msg_notes = []

    def _add_note(self, text):
        clean = str(text).strip()
        if clean and clean not in self.msg_notes:
            self.msg_notes.append(clean)

    def _parse_nodes(self):
        parsed = []
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
                h, p, pat = parts[0], 5432, self.patroni_port

            display_name = safe_name(alias) if alias else f"node{len(parsed) + 1}"
            base_name, dup = display_name, 2
            while any(p_[0] == display_name for p_ in parsed):
                display_name = f"{base_name}{dup}"
                dup += 1
            if display_name != base_name:
                self._add_note(f"Duplicate node alias {base_name} renamed to {display_name}")
            parsed.append((display_name, h, p, pat, has_explicit_alias))
        return parsed

    def _cache_path(self, seeds):
        import hashlib, tempfile
        key = hashlib.md5((",".join(f"{h}:{p}" for h, p, _ in seeds) + "|" + str(self.username)).encode()).hexdigest()[:12]
        return os.path.join(tempfile.gettempdir(), f"s247_pgcluster_{key}.json")

    def _apply_discovery(self, node_defs):
        """Adds cluster members found from the configured address(es) that are not configured yet."""
        if str(self.discover).strip().lower() in ("off", "false", "0", "no") or not node_defs:
            return node_defs
        seeds = [(h, p, pat) for (_n, h, p, pat, _a) in node_defs]
        cache_file = self._cache_path(seeds)
        extra = []
        try:
            with open(cache_file, "r") as fh:
                extra = [tuple(x) for x in json.load(fh) if (x[0], x[1]) not in {(h, p) for h, p, _ in seeds}]
        except Exception:
            pass
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            fut = ex.submit(discover_cluster_members, seeds + extra, self.username, self.password, self.db, DISCOVERY_DEADLINE_S)
            members, source, seed_names = fut.result(timeout=DISCOVERY_DEADLINE_S + 1)
        except Exception:
            members, source, seed_names = [], "", {}
        ex.shutdown(wait=False, cancel_futures=True)
        if not members:
            return node_defs
        try:
            with open(cache_file, "w") as fh:
                json.dump([[m["host"], m["port"], m["patroni_port"]] for m in members], fh)
        except Exception:
            pass

        known_addr = {(_norm_host(h), int(p)) for (_n, h, p, _pat, _a) in node_defs}
        known_alias = {n.lower() for (n, *_rest) in node_defs}
        # Configured nodes may use their own aliases: also recognise them by their Patroni member name.
        known_member = set()
        for i, (n, h, p, pat, a) in enumerate(list(node_defs)):
            mname = seed_names.get((_norm_host(h), int(p)))
            if mname:
                known_member.add(mname.lower())
                if not a:
                    # An address given without an alias is named after its Patroni member.
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
        added = 0
        for m in members:
            key = (_norm_host(m["host"]), int(m["port"]))
            if key in known_addr or m["alias"].lower() in known_alias or m["alias"].lower() in known_member:
                continue
            if len(node_defs) >= MAX_NODES:
                self._add_note(f"Cluster has more than {MAX_NODES} nodes; extra nodes are not shown")
                break
            name, k = m["alias"] or "node", 2
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
        for dname, h, p, pat, has_alias in node_defs:
            clients.append(PostgresNodeClient(dname, h, p, self.username, self.password, self.db, pat, has_explicit_alias=has_alias))

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
                if c.is_up and c.timeline is not None and c.timeline != primary_timeline:
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

        # Cluster Type Detection
        if self.cluster_type_override and self.cluster_type_override != 'auto':
            detected_type = self.cluster_type_override
            detected_evidence = f"Explicit override via cluster_type parameter ({self.cluster_type_override})"
        else:
            detected_type, detected_evidence = detect_cluster_type(agg_evidence)

        # In multi-master / active-active topologies, multiple concurrent primaries are expected
        c_lower = str(detected_type).lower()
        if "multi-master" in c_lower or "multimaster" in c_lower or "active-active" in c_lower or "bdr" in c_lower or "citus" in c_lower:
            split_brain_flag = 0

        # Build Cluster_Nodes child table
        cluster_nodes = []
        for c in clients:
            role_str = "offline"
            if c.is_up:
                role_str = "primary" if c.is_primary else "standby"

            upstream_val = str(c.upstream if c.upstream else "none")
            if c.is_cascading and "cascading" not in upstream_val.lower():
                upstream_val = f"{upstream_val} (cascading)" if upstream_val != "none" else "cascading"

            node_row = {
                "name": c.name,
                "role": role_str,
                "is_primary": 1 if (c.is_up and c.is_primary) else 0,
                "status": 1 if c.is_up else 0,
                "timeline": int(c.timeline) if c.timeline is not None else 0,
                "connections": int(c.connections) if c.connections is not None else 0,
                "response_time_ms": float(c.response_time_ms),
                "upstream": upstream_val,
                "patroni_state": str(c.patroni_state if c.patroni_state else "none")
            }
            if c.is_up and not c.is_primary:
                if c.replay_backlog_bytes is not None:
                    node_row["replay_backlog_bytes"] = max(0, int(c.replay_backlog_bytes))
                if c.replay_delay_s is not None:
                    node_row["replay_delay_s"] = max(0.0, float(c.replay_delay_s))

            cluster_nodes.append(node_row)

        node_io_table = [c.io_row for c in clients if c.io_row is not None]
        node_checkpoints_table = [c.checkpoints_row for c in clients if c.checkpoints_row is not None]
        node_activity_table = [c.activity_row for c in clients if c.activity_row is not None]
        node_transactions_table = [c.transactions_row for c in clients if c.transactions_row is not None]
        standby_conflicts_table = [c.conflicts_row for c in clients if c.conflicts_row is not None]

        # Primary queries
        replication_standbys = []
        replication_slots = []
        sync_standbys_count = 0
        cascading_standbys_count = sum(c.is_cascading for c in clients if c.is_up and not c.is_primary)
        max_replay_backlog = 0
        max_replay_delay_s = 0.0
        slots_total = 0
        slots_active = 0
        slots_inactive = 0
        max_slot_lag_bytes = 0

        member_to_name = {c.patroni_member: c.name for c in clients if c.patroni_member}

        if active_primary and active_primary.conn:
            # 1. Replication standbys
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
                        client_ip = str(r[1] or "").strip()
                        standby_name = member_to_name.get(app_name) or safe_name(app_name) or "standby"

                        replication_standbys.append({
                            "name": standby_name,
                            "client_addr": client_ip,
                            "state": str(r[2]),
                            "sync_state": str(r[3]),
                            "replay_lag_bytes": rep_lag_bytes,
                            "write_lag_bytes": w_lag_bytes,
                            "flush_lag_bytes": f_lag_bytes,
                            "replay_lag_s": rep_lag_s,
                            "is_sync": is_sync,
                            "status": 1
                        })
                agg_evidence["has_standbys"] = len(replication_standbys) > 0
                agg_evidence["standby_count"] = len(replication_standbys)
            except Exception as e:
                self._add_note(f"Standbys query error: {e}")

            # 2. Replication slots
            try:
                with active_primary.conn.cursor() as cur:
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

                        replication_slots.append({
                            "name": safe_name(str(r[0])) or str(r[0]),
                            "plugin": str(r[1]),
                            "slot_type": str(r[2]),
                            "active": is_act,
                            "wal_retained_bytes": retained,
                            "status": 1
                        })
                agg_evidence["has_replication_slots"] = slots_total > 0
            except Exception as e:
                self._add_note(f"Slots query error: {e}")

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
                    cur.execute(std_queries['uptime'])
                    results["Uptime"] = int(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"Uptime: {e}")

            # Checkpoints / BG writer
            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute(std_queries['bg_stats'])
                    r = cur.fetchone()
                    if r:
                        results["Checkpoints Timed"] = int(r[0] or 0)
                        results["Checkpoints Req"] = int(r[1] or 0)
                        results["Checkpoint Write Time"] = int(r[2] or 0)
                        results["Checkpoint Sync Time"] = int(r[3] or 0)
                        results["Buffers Checkpoint"] = int(r[4] or 0)
                        results["Buffers Clean"] = int(r[5] or 0)
                        results["Maxwritten Clean"] = int(r[6] or 0)
                        if major_v >= 17:
                            results["Buffers Alloc"] = int(r[7] or 0)
                        else:
                            results["Buffers Backend"] = int(r[7] or 0)
                            results["Buffers Backend Fsync"] = int(r[8] or 0)
                            results["Buffers Alloc"] = int(r[9] or 0)
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
                    results["WAL Write Position"] = float(cur.fetchone()[0])
                    cur.execute("SELECT ROUND(pg_wal_lsn_diff(pg_current_wal_insert_lsn(), '0/0') / 1024.0 / 1024.0, 2);")
                    results["WAL Insert Position"] = float(cur.fetchone()[0])
                    cur.execute("SELECT ROUND(pg_wal_lsn_diff(pg_current_wal_flush_lsn(), '0/0') / 1024.0 / 1024.0, 2);")
                    results["WAL Flush Position"] = float(cur.fetchone()[0])
            except Exception as e:
                self._add_note(f"WAL positions: {e}")

            try:
                with active_primary.conn.cursor() as cur:
                    cur.execute("SELECT count(*), COALESCE(ROUND(SUM(size) / 1024.0 / 1024.0, 2), 0) FROM pg_ls_waldir() WHERE name ~ '^[0-9A-Fa-f]{24}$';")
                    r = cur.fetchone()
                    if r and r[0] is not None:
                        results["WAL Files Count"] = int(r[0])
                        results["WAL Total Size"] = float(r[1])
            except Exception as e:
                self._add_note(f"pg_ls_waldir: {e}")

            # Recovery Conflicts totals from standbys
            if standby_conflicts_table:
                conf_ts = sum(r.get("confl_tablespace", 0) for r in standby_conflicts_table)
                conf_lock = sum(r.get("confl_lock", 0) for r in standby_conflicts_table)
                conf_snap = sum(r.get("confl_snapshot", 0) for r in standby_conflicts_table)
                conf_pin = sum(r.get("confl_bufferpin", 0) for r in standby_conflicts_table)
                conf_dead = sum(r.get("confl_deadlock", 0) for r in standby_conflicts_table)
                results["Conflicts Tablespace"] = conf_ts
                results["Conflicts Lock"] = conf_lock
                results["Conflicts Snapshot"] = conf_snap
                results["Conflicts Buffer Pin"] = conf_pin
                results["Conflicts Deadlock"] = conf_dead
                results["Recovery Conflicts Total"] = conf_ts + conf_lock + conf_snap + conf_pin + conf_dead

            # Standalone childdiscovery tables: Stats_per_DB and Tranasctions_and_Session_per_Database
            try:
                with active_primary.conn.cursor() as cur:
                    db_details_sql = "SELECT d.datname AS name, s.numbackends as active_connections, ROUND(pg_database_size(d.datname) / 1024 / 1024,2) AS size_in_mb,tup_inserted as rows_inserted, tup_updated as rows_updated, tup_deleted as rows_deleted, tup_fetched as rows_fetched , tup_returned as rows_returned, blks_read as block_reads , blks_hit as block_hits FROM pg_database d JOIN pg_stat_database s ON d.oid = s.datid;"
                    cur.execute(db_details_sql)
                    db_stats_rows = []
                    for row in cur.fetchall():
                        db_stats_rows.append({
                            "name": str(row[0]),
                            "active_connections": int(row[1] or 0),
                            "size_in_mb": float(row[2] or 0.0),
                            "rows_inserted": int(row[3] or 0),
                            "rows_updated": int(row[4] or 0),
                            "rows_deleted": int(row[5] or 0),
                            "rows_fetched": int(row[6] or 0),
                            "rows_returned": int(row[7] or 0),
                            "block_reads": int(row[8] or 0),
                            "block_hits": int(row[9] or 0)
                        })
                    results["Stats_per_DB"] = db_stats_rows[:25]
            except Exception as e:
                self._add_note(f"Stats_per_DB: {e}")

            try:
                with active_primary.conn.cursor() as cur:
                    if major_v >= 14:
                        conn_details_sql = "SELECT datname as name,xact_commit as commits, xact_rollback as rollbacks, conflicts, sessions, sessions_abandoned, sessions_fatal, sessions_killed, session_time, active_time as sessions_active_time, idle_in_transaction_time as session_idle_in_transaction_time FROM pg_stat_database;"
                    else:
                        conn_details_sql = "SELECT datname as name,xact_commit as commits, xact_rollback as rollbacks, conflicts FROM pg_stat_database;"
                    cur.execute(conn_details_sql)
                    tx_stats_rows = []
                    for row in cur.fetchall():
                        if row[0] is None:
                            continue
                        r_dict = {
                            "name": str(row[0]),
                            "commits": int(row[1] or 0),
                            "rollbacks": int(row[2] or 0),
                            "conflicts": int(row[3] or 0)
                        }
                        if len(row) > 4:
                            r_dict["sessions"] = int(row[4] or 0)
                            r_dict["sessions_abandoned"] = int(row[5] or 0)
                            r_dict["sessions_fatal"] = int(row[6] or 0)
                            r_dict["sessions_killed"] = int(row[7] or 0)
                            r_dict["session_time"] = float(row[8] or 0.0)
                            r_dict["sessions_active_time"] = float(row[9] or 0.0)
                            r_dict["session_idle_in_transaction_time"] = float(row[10] or 0.0)
                        tx_stats_rows.append(r_dict)
                    results["Tranasctions_and_Session_per_Database"] = tx_stats_rows[:25]
            except Exception as e:
                self._add_note(f"Tranasctions_and_Session_per_Database: {e}")

        else:
            self._add_note("Cluster alert: No reachable primary node detected")

        # Close all client connections
        for cli in clients:
            cli.close()

        # Standbys counts
        standbys_expected = max(0, nodes_total - primary_count)
        standbys_streaming = len(replication_standbys) + cascading_standbys_count
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
            cluster_type=detected_type
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

        # Tabular Data (Enforce Site24x7 25-row limit)
        results["Cluster_Info"] = [{
            "name": safe_name(str(patroni_scope_discovered or "postgrescluster")) or "cluster",
            "cluster_type": str(detected_type)[:99],
            "type_evidence": (str(detected_evidence)[:58] + f" | {self.discovery_added} node(s) found via {self.discovery_source}")[:99] if self.discovery_added else str(detected_evidence)[:99],
            "server_version": str(server_version_str)[:99],
            "primary_node": active_primary.name if active_primary else "none",
            "health_reason": str(health_reason)[:99],
            "nodes_total": int(nodes_total),
            "nodes_up": int(nodes_up),
            "primary_timeline": int(primary_timeline),
            "status": 1 if nodes_up else 0,
        }]
        results["Cluster_Nodes"] = cluster_nodes[:25]
        results["Replication_Standbys"] = replication_standbys[:25]
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
        nodes = param.get("nodes") if param and param.get("nodes") is not None else NODES
        username = param.get("username") if param and param.get("username") else USERNAME
        password = param.get("password") if param and param.get("password") else PASSWORD
        db = param.get("db") if param and param.get("db") else DB
        patroni_port = param.get("patroni_port") if param and param.get("patroni_port") else PATRONI_PORT
        cluster_type = param.get("cluster_type") if param and param.get("cluster_type") else CLUSTER_TYPE
        discover = param.get("discover") if param and param.get("discover") else DISCOVER

        collector = PostgresClusterCollector(nodes, username, password, db, patroni_port, cluster_type, discover)
        return collector.collect()
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
    parser.add_argument('--nodes', help='Comma-separated nodes (host:port, name=host:port, or host:port:patroni_port)', default=NODES)
    parser.add_argument('--username', help='PostgreSQL username', default=USERNAME)
    parser.add_argument('--password', help='PostgreSQL password', default=PASSWORD)
    parser.add_argument('--db', help='Database name', default=DB)
    parser.add_argument('--patroni_port', help='Patroni REST API port', default=PATRONI_PORT)
    parser.add_argument('--cluster_type', help='Cluster manager type (auto, Patroni, repmgr, etc.)', default=CLUSTER_TYPE)
    parser.add_argument('--discover', help="'auto' finds the other cluster nodes from the configured address(es); 'off' monitors only the listed nodes", default=DISCOVER)
    args = parser.parse_args()

    param = {
        "nodes": args.nodes,
        "username": args.username,
        "password": args.password,
        "db": args.db,
        "patroni_port": args.patroni_port,
        "cluster_type": args.cluster_type,
        "discover": args.discover
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
