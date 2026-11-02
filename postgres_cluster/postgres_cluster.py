#!/usr/bin/python3

### This plugin is used for monitoring PostgreSQL Cluster
### Monitors multiple nodes, detects primary/standby roles, health, replication lag,
### replication slots, cluster manager type, per-node activity/throughput/checkpoints,
### and collects PostgreSQL performance metrics across all nodes.
###
### Language : Python
### Compatible with Site24x7 Linux and Windows Agents.

import json
import time
import copy
import urllib.request
import urllib.error
import concurrent.futures
from collections import OrderedDict

# Default cluster configuration
NODES = '127.0.0.1:5441:8001,127.0.0.1:5442:8002,127.0.0.1:5443:8003'  # host:port or host:port:patroni_port
USERNAME = 'site24x7'                                                    # Monitoring username
PASSWORD = 'site24x7'                                                    # Monitoring password
DB = 'postgres'                                                          # Database name to connect to
PATRONI_PORT = '8008'                                                    # Optional Patroni REST API port or mapping
CLUSTER_TYPE = 'auto'                                                    # 'auto' or explicit override
CONNECT_TIMEOUT = 2                                                      # Timeout for connecting to each node (seconds)
STATEMENT_TIMEOUT_MS = 5000                                              # Per-query statement timeout in PostgreSQL (ms)

PLUGIN_VERSION = 7
HEARTBEAT = True

# Standard 7-Tab Layout for Site24x7 Console
tabs = {
    "tabs": {
        "Cluster": {
            "order": "1",
            "tablist": [
                "Cluster_Nodes",
                "Cluster Type",
                "Cluster Type Evidence",
                "Nodes Total",
                "Nodes Up",
                "Primary Count",
                "No Primary Flag",
                "Split Brain Flag",
                "Primary Timeline",
                "Server Version",
                "Uptime",
                "Cluster Name",
                "Server PID"
            ]
        },
        "Replication": {
            "order": "2",
            "tablist": [
                "Replication_Standbys",
                "Replication_Slots",
                "Standbys Expected",
                "Standbys Streaming",
                "Standby Disconnect Flag",
                "Sync Standby Count",
                "Cascading Standby Count",
                "Max Replay Backlog",
                "Max Replay Delay",
                "Replication Slots Total",
                "Replication Slots Active",
                "Replication Slots Inactive",
                "Physical Slots",
                "Logical Slots",
                "Max Slot Lag Bytes"
            ]
        },
        "DB and IO stats": {
            "order": "3",
            "tablist": [
                "Stats_per_DB",
                "Node_Throughput",
                "Cache Hit Ratio",
                "Dead Tuples",
                "Total Block Reads",
                "Total Block Hits",
                "Heap Blocks Read",
                "Heap Blocks Hit",
                "Index Scans",
                "Index Rows Read",
                "Index Rows Fetched",
                "Total Rows Inserted",
                "Total Rows Updated",
                "Total Rows Deleted",
                "Total Rows Fetched",
                "Total Rows Returned",
                "Table Count",
                "Database Count"
            ]
        },
        "BG Writer": {
            "order": "4",
            "tablist": [
                "Node_Checkpoints",
                "Checkpoints Timed",
                "Checkpoints Req",
                "Checkpoint Write Time",
                "Checkpoint Sync Time",
                "Buffers Checkpoint",
                "Buffers Clean",
                "Maxwritten Clean",
                "Buffers Backend",
                "Buffers Backend Fsync",
                "Buffers Alloc"
            ]
        },
        "Transactions and Sessions": {
            "order": "5",
            "tablist": [
                "Tranasctions_and_Session_per_Database",
                "Node_Activity",
                "Oldest Transaction ID Age",
                "Total Commits",
                "Total Rollbacks",
                "Total Conflicts",
                "Transactions Open",
                "Transactions Idle In Transaction",
                "Total Sessions",
                "Total Sessions Abandoned",
                "Total Sessions Fatal",
                "Total Sessions Killed"
            ]
        },
        "Write Ahead Log": {
            "order": "6",
            "tablist": [
                "Archive Mode",
                "Archive Status Success",
                "Archive Status Failed",
                "Archive Ready Files Count",
                "Last Archived WAL File",
                "WAL Write Position",
                "WAL Insert Position",
                "WAL Flush Position",
                "WAL Files Count",
                "WAL Total Size"
            ]
        },
        "Recovery Conflicts": {
            "order": "7",
            "tablist": [
                "Standby_Conflicts",
                "Recovery Conflicts Total",
                "Conflicts Tablespace",
                "Conflicts Lock",
                "Conflicts Snapshot",
                "Conflicts Buffer Pin",
                "Conflicts Deadlock",
                "Oldest Running Transaction Age",
                "Active Connections",
                "Available Connections",
                "Max Connections",
                "Superuser Reserved Connections",
                "Connection Utilization Percent",
                "Active Queries",
                "Active Waiting Queries",
                "Locks Count"
            ]
        }
    }
}

units = {
    # Top-level cluster & replication metrics
    "Nodes Total": "nodes",
    "Nodes Up": "nodes",
    "Primary Count": "nodes",
    "No Primary Flag": "flag",
    "Split Brain Flag": "flag",
    "Primary Timeline": "timeline",
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
    "Physical Slots": "slots",
    "Logical Slots": "slots",
    "Max Slot Lag Bytes": "bytes",

    # Performance, DBA & IO metrics
    "Cache Hit Ratio": "%",
    "Dead Tuples": "tuples",
    "Oldest Transaction ID Age": "xids",
    "Total Block Reads": "blocks",
    "Total Block Hits": "blocks",
    "Heap Blocks Read": "blocks",
    "Heap Blocks Hit": "blocks",
    "Index Scans": "scans",
    "Index Rows Read": "rows",
    "Index Rows Fetched": "rows",
    "Total Rows Inserted": "rows",
    "Total Rows Updated": "rows",
    "Total Rows Deleted": "rows",
    "Total Rows Fetched": "rows",
    "Total Rows Returned": "rows",
    "Table Count": "tables",
    "Database Count": "databases",

    # Background Writer & Checkpoints
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

    # Transactions & Sessions
    "Total Commits": "transactions",
    "Total Rollbacks": "transactions",
    "Total Conflicts": "conflicts",
    "Transactions Open": "transactions",
    "Transactions Idle In Transaction": "transactions",
    "Total Sessions": "sessions",
    "Total Sessions Abandoned": "sessions",
    "Total Sessions Fatal": "sessions",
    "Total Sessions Killed": "sessions",

    # WAL & Archiving
    "WAL Write Position": "MB",
    "WAL Insert Position": "MB",
    "WAL Flush Position": "MB",
    "WAL Files Count": "files",
    "WAL Total Size": "MB",
    "Archive Status Success": "files",
    "Archive Status Failed": "files",
    "Archive Ready Files Count": "files",

    # Connections & Conflicts
    "Active Connections": "connections",
    "Available Connections": "connections",
    "Max Connections": "connections",
    "Superuser Reserved Connections": "connections",
    "Connection Utilization Percent": "%",
    "Active Queries": "queries",
    "Active Waiting Queries": "queries",
    "Locks Count": "locks",
    "Uptime": "s",
    "Recovery Conflicts Total": "conflicts",
    "Conflicts Tablespace": "conflicts",
    "Conflicts Lock": "conflicts",
    "Conflicts Snapshot": "conflicts",
    "Conflicts Buffer Pin": "conflicts",
    "Conflicts Deadlock": "conflicts",
    "Oldest Running Transaction Age": "s",

    # Nested Table Units
    "Cluster_Nodes": {
        "response_time_ms": "ms",
        "replay_backlog_bytes": "bytes",
        "replay_delay_s": "s",
        "connections": "connections",
        "timeline": "timeline",
        "up": "flag",
        "is_primary": "flag",
        "is_cascading": "flag",
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
    "Node_Activity": {
        "active_connections": "connections",
        "max_connections": "connections",
        "utilization_pct": "%",
        "active_queries": "queries",
        "waiting_queries": "queries",
        "idle_in_transaction": "transactions",
        "transactions_open": "transactions",
        "locks": "locks",
        "oldest_xact_age_s": "s",
        "uptime_s": "s",
        "status": "status"
    },
    "Node_Throughput": {
        "commits": "transactions",
        "rollbacks": "transactions",
        "rows_inserted": "rows",
        "rows_updated": "rows",
        "rows_deleted": "rows",
        "rows_fetched": "rows",
        "rows_returned": "rows",
        "block_reads": "blocks",
        "block_hits": "blocks",
        "cache_hit_pct": "%",
        "status": "status"
    },
    "Node_Checkpoints": {
        "checkpoints_timed": "checkpoints",
        "checkpoints_req": "checkpoints",
        "write_time_ms": "ms",
        "sync_time_ms": "ms",
        "buffers_checkpoint": "buffers",
        "buffers_clean": "buffers",
        "maxwritten_clean": "buffers",
        "buffers_alloc": "buffers",
        "buffers_backend": "buffers",
        "buffers_backend_fsync": "calls",
        "status": "status"
    },
    "Standby_Conflicts": {
        "confl_tablespace": "conflicts",
        "confl_lock": "conflicts",
        "confl_snapshot": "conflicts",
        "confl_bufferpin": "conflicts",
        "confl_deadlock": "conflicts",
        "total_conflicts": "conflicts",
        "status": "status"
    }
}


def coerce_metric_value(val_name, raw_val):
    """
    Coerces raw database metric values to integers, floats, or strings per Site24x7 rules.
    String exceptions: Server Version, Last Archived WAL File, Cluster Type, Cluster Type Evidence,
    Cluster Name, Archive Mode.
    All other metrics are strictly converted to numeric int or float.
    """
    if raw_val is None:
        return None
    str_val = str(raw_val).strip()
    if str_val.lower() == 'none':
        return None

    if val_name in (
        "Server Version", "Last Archived WAL File", "Cluster Type",
        "Cluster Type Evidence", "Cluster Name", "Archive Mode"
    ):
        return str_val

    # Attempt integer conversion
    try:
        if "." not in str_val:
            return int(str_val)
        val_f = float(str_val)
        if val_f.is_integer():
            return int(val_f)
        return round(val_f, 2)
    except (ValueError, TypeError):
        try:
            return round(float(str_val), 2)
        except (ValueError, TypeError):
            return str_val


def detect_cluster_type(evidence):
    """
    Pure function to classify cluster type from collected evidence.
    Returns: (cluster_type: str, cluster_type_evidence: str)
    cluster_type_evidence must be strictly under 100 characters.
    """
    managers = []
    manager_evidences = []

    # 1. Patroni check: requires actual valid patroni response object
    patroni_data = evidence.get("patroni")
    if patroni_data and isinstance(patroni_data, dict) and patroni_data.get("is_patroni"):
        scope = patroni_data.get("scope", "cluster")
        version = patroni_data.get("version", "")
        managers.append("Patroni")
        manager_evidences.append(f"Patroni REST API response (scope: {scope}, v{version})")

    # 2. repmgr check: extension, catalog table, or slot/app pattern
    exts = evidence.get("extensions", [])
    has_repmgr_table = evidence.get("repmgr_table", False)
    slot_names = evidence.get("slot_names", [])
    app_names = evidence.get("app_names", [])

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

    # 7. Managed cloud services
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

    # Conflict check: Patroni plus another manager or multiple conflicting managers
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
    and metrics collection without any module-level global variables.
    """
    def __init__(self, host, port, username, password, db, patroni_port=None):
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
        self.timeline = 0
        self.response_time_ms = 0.0
        self.is_up = False
        self.patroni_state = "N/A"
        self.patroni_info = None
        self.notes = []

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

            cur.execute("SELECT pg_is_in_recovery();")
            in_rec = cur.fetchone()[0]
            self.is_primary = not in_rec

            # Timeline detection
            try:
                if self.is_primary:
                    cur.execute("SELECT ('x' || substring(pg_walfile_name(pg_current_wal_lsn()) from 1 for 8))::bit(32)::int;")
                    self.timeline = int(cur.fetchone()[0])
                else:
                    cur.execute("SELECT timeline_id FROM pg_control_checkpoint();")
                    self.timeline = int(cur.fetchone()[0])
            except Exception:
                self.timeline = 1

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
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                self.patroni_state = data.get("state", "N/A")
                pat_obj = data.get("patroni")
                if isinstance(pat_obj, dict):
                    self.patroni_info = {
                        "is_patroni": True,
                        "scope": pat_obj.get("scope", "unknown"),
                        "version": pat_obj.get("version", ""),
                        "name": pat_obj.get("name", "")
                    }
        except Exception:
            self.patroni_state = "N/A"

    def collect_node_activity(self):
        """Collects row for Node_Activity table (Site24x7 compliant)."""
        row = {"name": self.endpoint_str, "status": 1}
        try:
            with self.conn.cursor() as cur:
                # Connections
                cur.execute("SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend';")
                row["active_connections"] = int(cur.fetchone()[0])

                cur.execute("SELECT setting::int FROM pg_settings WHERE name = 'max_connections';")
                row["max_connections"] = int(cur.fetchone()[0])

                row["utilization_pct"] = round((row["active_connections"] / max(row["max_connections"], 1)) * 100.0, 2)

                # Active queries & waiting queries
                cur.execute("SELECT count(*) FROM pg_stat_activity WHERE state = 'active';")
                row["active_queries"] = int(cur.fetchone()[0])

                cur.execute("SELECT count(*) FROM pg_stat_activity WHERE state = 'active' AND wait_event IS NOT NULL;")
                row["waiting_queries"] = int(cur.fetchone()[0])

                cur.execute("SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction';")
                row["idle_in_transaction"] = int(cur.fetchone()[0])

                cur.execute("SELECT count(*) FROM pg_stat_activity WHERE xact_start IS NOT NULL;")
                row["transactions_open"] = int(cur.fetchone()[0])

                cur.execute("SELECT count(*) FROM pg_locks;")
                row["locks"] = int(cur.fetchone()[0])

                cur.execute("SELECT COALESCE(MAX(EXTRACT(EPOCH FROM (now() - xact_start)))::bigint, 0) FROM pg_stat_activity WHERE state <> 'idle' AND xact_start IS NOT NULL;")
                row["oldest_xact_age_s"] = int(cur.fetchone()[0])

                cur.execute("SELECT FLOOR(EXTRACT(EPOCH FROM (current_timestamp - pg_postmaster_start_time())))::bigint;")
                row["uptime_s"] = int(cur.fetchone()[0])
        except Exception as e:
            self.notes.append(f"Node_Activity error on {self.endpoint_str}: {e}")
            row["status"] = 0
        return row

    def collect_node_throughput(self):
        """Collects row for Node_Throughput table (Site24x7 compliant)."""
        row = {"name": self.endpoint_str, "status": 1}
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT sum(xact_commit), sum(xact_rollback) FROM pg_stat_database;")
                c_row = cur.fetchone()
                row["commits"] = int(c_row[0] or 0)
                row["rollbacks"] = int(c_row[1] or 0)

                cur.execute("SELECT sum(tup_inserted), sum(tup_updated), sum(tup_deleted), sum(tup_fetched), sum(tup_returned), sum(blks_read), sum(blks_hit) FROM pg_stat_database;")
                d_row = cur.fetchone()
                row["rows_inserted"] = int(d_row[0] or 0)
                row["rows_updated"] = int(d_row[1] or 0)
                row["rows_deleted"] = int(d_row[2] or 0)
                row["rows_fetched"] = int(d_row[3] or 0)
                row["rows_returned"] = int(d_row[4] or 0)
                row["block_reads"] = int(d_row[5] or 0)
                row["block_hits"] = int(d_row[6] or 0)

                tot_blks = row["block_hits"] + row["block_reads"]
                row["cache_hit_pct"] = round((row["block_hits"] / tot_blks * 100.0), 2) if tot_blks > 0 else 100.0
        except Exception as e:
            self.notes.append(f"Node_Throughput error on {self.endpoint_str}: {e}")
            row["status"] = 0
        return row

    def collect_node_checkpoints(self):
        """Collects row for Node_Checkpoints table, handling PG 10-17 differences without fabricating 0s."""
        row = {"name": self.endpoint_str, "status": 1}
        try:
            with self.conn.cursor() as cur:
                is_pg17 = self.server_version_num >= 170000
                if is_pg17:
                    # In PG 17, checkpoints moved to pg_stat_checkpointer; buffers_backend not in bgwriter
                    cur.execute("""
                        SELECT c.num_timed, c.num_requested, c.write_time, c.sync_time, c.buffers_written,
                               b.buffers_clean, b.maxwritten_clean, b.buffers_alloc
                        FROM pg_stat_checkpointer c, pg_stat_bgwriter b;
                    """)
                    r = cur.fetchone()
                    row["checkpoints_timed"] = int(r[0] or 0)
                    row["checkpoints_req"] = int(r[1] or 0)
                    row["write_time_ms"] = int(r[2] or 0)
                    row["sync_time_ms"] = int(r[3] or 0)
                    row["buffers_checkpoint"] = int(r[4] or 0)
                    row["buffers_clean"] = int(r[5] or 0)
                    row["maxwritten_clean"] = int(r[6] or 0)
                    row["buffers_alloc"] = int(r[7] or 0)
                    # buffers_backend and buffers_backend_fsync omitted (not in PG17, do not fabricate 0)
                else:
                    cur.execute("""
                        SELECT checkpoints_timed, checkpoints_req, checkpoint_write_time, checkpoint_sync_time,
                               buffers_checkpoint, buffers_clean, maxwritten_clean, buffers_alloc,
                               buffers_backend, buffers_backend_fsync
                        FROM pg_stat_bgwriter;
                    """)
                    r = cur.fetchone()
                    row["checkpoints_timed"] = int(r[0] or 0)
                    row["checkpoints_req"] = int(r[1] or 0)
                    row["write_time_ms"] = int(r[2] or 0)
                    row["sync_time_ms"] = int(r[3] or 0)
                    row["buffers_checkpoint"] = int(r[4] or 0)
                    row["buffers_clean"] = int(r[5] or 0)
                    row["maxwritten_clean"] = int(r[6] or 0)
                    row["buffers_alloc"] = int(r[7] or 0)
                    row["buffers_backend"] = int(r[8] or 0)
                    row["buffers_backend_fsync"] = int(r[9] or 0)
        except Exception as e:
            self.notes.append(f"Node_Checkpoints error on {self.endpoint_str}: {e}")
            row["status"] = 0
        return row

    def collect_standby_conflicts(self):
        """Reads pg_stat_database_conflicts on a standby node."""
        if self.is_primary:
            return None
        row = {"name": self.endpoint_str, "status": 1}
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT COALESCE(sum(confl_tablespace), 0),
                           COALESCE(sum(confl_lock), 0),
                           COALESCE(sum(confl_snapshot), 0),
                           COALESCE(sum(confl_bufferpin), 0),
                           COALESCE(sum(confl_deadlock), 0)
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
            self.notes.append(f"Standby_Conflicts error on {self.endpoint_str}: {e}")
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
                # Extensions
                try:
                    cur.execute("SELECT extname FROM pg_extension WHERE extname IN ('repmgr', 'pgautofailover', 'citus', 'pglogical', 'bdr');")
                    evidence["extensions"] = [r[0] for r in cur.fetchall()]
                except Exception:
                    pass

                # repmgr catalog table
                try:
                    cur.execute("SELECT to_regclass('repmgr.nodes') IS NOT NULL;")
                    evidence["repmgr_table"] = bool(cur.fetchone()[0])
                except Exception:
                    pass

                # Managed roles
                try:
                    cur.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('rds_superuser', 'azure_pg_admin', 'cloudsqlsuperuser');")
                    evidence["managed_roles"] = [r[0] for r in cur.fetchall()]
                except Exception:
                    pass

                # Aurora function
                try:
                    cur.execute("SELECT to_regprocedure('aurora_version()') IS NOT NULL;")
                    evidence["aurora_version"] = bool(cur.fetchone()[0])
                except Exception:
                    pass

                # Slots
                try:
                    cur.execute("SELECT slot_name FROM pg_replication_slots;")
                    evidence["slot_names"] = [r[0] for r in cur.fetchall()]
                except Exception:
                    pass

                # Standby wal receiver & upstream
                if not self.is_primary:
                    try:
                        cur.execute("SELECT status, sender_host, sender_port, slot_name FROM pg_stat_wal_receiver;")
                        row = cur.fetchone()
                        if row:
                            sender_h, sender_p = row[1], row[2]
                            evidence["upstream"] = f"{sender_h}:{sender_p}" if sender_h else "primary"
                            if row[3]:
                                evidence["slot_names"].append(row[3])
                    except Exception:
                        pass

                # Cascading check: standby that itself has downstream standbys in pg_stat_replication
                try:
                    cur.execute("SELECT application_name FROM pg_stat_replication;")
                    st_rows = cur.fetchall()
                    if st_rows:
                        evidence["app_names"].extend([r[0] for r in st_rows])
                        if not self.is_primary:
                            evidence["is_cascading"] = 1
                except Exception:
                    pass
        except Exception:
            pass

        return evidence


class PostgresClusterCollector:
    """
    Main collector coordinating concurrent node probes, cluster-level metrics,
    per-node tables, cluster type detection, and Site24x7 JSON packaging.
    """
    def __init__(self, nodes_str, username, password, db, patroni_port=PATRONI_PORT, cluster_type=CLUSTER_TYPE):
        self.nodes_str = nodes_str or NODES
        self.username = username or USERNAME
        self.password = password or PASSWORD
        self.db = db or DB
        self.patroni_port = patroni_port or PATRONI_PORT
        self.cluster_type_override = cluster_type or CLUSTER_TYPE
        self.msg_notes = []

    def _add_note(self, note):
        if note and note not in self.msg_notes:
            self.msg_notes.append(note)

    def _parse_nodes(self):
        """Parses nodes parameter handling host:port, host:port:patroni_port, or name=host:port."""
        parsed = []
        for raw in self.nodes_str.split(','):
            raw = raw.strip()
            if not raw:
                continue
            if '=' in raw:
                alias, addr = raw.split('=', 1)
            else:
                alias, addr = None, raw

            parts = addr.split(':')
            if len(parts) == 3:
                h, p, pat = parts[0], parts[1], parts[2]
            elif len(parts) == 2:
                h, p, pat = parts[0], parts[1], self.patroni_port
            else:
                h, p, pat = parts[0], "5432", self.patroni_port

            parsed.append({
                "alias": alias,
                "host": h,
                "port": p,
                "patroni_port": pat,
                "endpoint_str": f"{h}:{p}" if (not pat or pat == "none") else f"{h}:{p}:{pat}"
            })
        return parsed

    def collect(self):
        results = OrderedDict()
        results["plugin_version"] = PLUGIN_VERSION
        results["heartbeat_required"] = HEARTBEAT
        results["status"] = 1

        node_defs = self._parse_nodes()
        nodes_total = len(node_defs)
        if nodes_total == 0:
            results["status"] = 0
            results["msg"] = "Configuration error: 'nodes' parameter is empty"
            return results

        # Parallel node probing
        clients = [
            PostgresNodeClient(
                host=nd["host"],
                port=nd["port"],
                username=self.username,
                password=self.password,
                db=self.db,
                patroni_port=nd["patroni_port"]
            )
            for nd in node_defs
        ]

        def probe_node(cli):
            try:
                cli.query_patroni()
            except Exception:
                pass
            try:
                cli.connect()
            except Exception as e:
                cli.notes.append(str(e))
            return cli

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(nodes_total, 10)) as executor:
            probed_clients = list(executor.map(probe_node, clients))

        # Evaluate cluster membership and identify primary
        nodes_up = 0
        primary_clients = []
        cluster_nodes = []
        node_activity_table = []
        node_throughput_table = []
        node_checkpoints_table = []
        standby_conflicts_table = []
        all_evidences = []

        for cli in probed_clients:
            if cli.notes:
                for n in cli.notes:
                    self._add_note(n)

            if cli.is_up:
                nodes_up += 1
                ev = cli.collect_evidence()
                if cli.patroni_info:
                    ev["patroni"] = cli.patroni_info
                all_evidences.append(ev)

                # Per-node tables
                node_activity_table.append(cli.collect_node_activity())
                node_throughput_table.append(cli.collect_node_throughput())
                node_checkpoints_table.append(cli.collect_node_checkpoints())

                if cli.is_primary:
                    primary_clients.append(cli)
                else:
                    conf_row = cli.collect_standby_conflicts()
                    if conf_row:
                        standby_conflicts_table.append(conf_row)

                # Cluster_Nodes row
                cluster_nodes.append({
                    "name": cli.endpoint_str,
                    "role": "primary" if cli.is_primary else "standby",
                    "patroni_state": cli.patroni_state,
                    "upstream": ev.get("upstream", "primary" if not cli.is_primary else "N/A"),
                    "is_cascading": ev.get("is_cascading", 0),
                    "up": 1,
                    "is_primary": 1 if cli.is_primary else 0,
                    "timeline": cli.timeline,
                    "response_time_ms": cli.response_time_ms,
                    "replay_backlog_bytes": 0,
                    "replay_delay_s": 0.0,
                    "connections": 0,
                    "status": 1
                })
            else:
                cluster_nodes.append({
                    "name": cli.endpoint_str,
                    "role": "offline",
                    "patroni_state": cli.patroni_state,
                    "upstream": "N/A",
                    "is_cascading": 0,
                    "up": 0,
                    "is_primary": 0,
                    "timeline": 0,
                    "response_time_ms": 0.0,
                    "replay_backlog_bytes": 0,
                    "replay_delay_s": 0.0,
                    "connections": 0,
                    "status": 0
                })

        primary_count = len(primary_clients)
        no_primary_flag = 1 if primary_count == 0 else 0
        split_brain_flag = 1 if primary_count > 1 else 0

        # Cluster Type Detection
        combined_evidence = {
            "patroni": None,
            "extensions": [],
            "repmgr_table": False,
            "managed_roles": [],
            "aurora_version": False,
            "slot_names": [],
            "app_names": [],
            "has_standbys": False,
            "standby_count": max(0, nodes_up - primary_count),
            "total_nodes": nodes_total,
            "is_in_recovery": (nodes_up > 0 and primary_count == 0)
        }
        for ev in all_evidences:
            if ev.get("patroni"):
                combined_evidence["patroni"] = ev["patroni"]
            combined_evidence["extensions"].extend(ev.get("extensions", []))
            if ev.get("repmgr_table"):
                combined_evidence["repmgr_table"] = True
            combined_evidence["managed_roles"].extend(ev.get("managed_roles", []))
            if ev.get("aurora_version"):
                combined_evidence["aurora_version"] = True
            combined_evidence["slot_names"].extend(ev.get("slot_names", []))
            combined_evidence["app_names"].extend(ev.get("app_names", []))

        combined_evidence["extensions"] = list(set(combined_evidence["extensions"]))
        combined_evidence["managed_roles"] = list(set(combined_evidence["managed_roles"]))
        combined_evidence["has_standbys"] = (combined_evidence["standby_count"] > 0 or len(combined_evidence["slot_names"]) > 0)

        if self.cluster_type_override and self.cluster_type_override.lower() != "auto":
            detected_type = self.cluster_type_override
            detected_evidence = "Configured override in postgres_cluster.cfg"
        else:
            detected_type, detected_evidence = detect_cluster_type(combined_evidence)

        results["Cluster Type"] = detected_type
        results["Cluster Type Evidence"] = detected_evidence

        # Standbys & Replication Telemetry
        replication_standbys = []
        replication_slots = []
        slots_total = 0
        slots_active = 0
        slots_inactive = 0
        slots_physical = 0
        slots_logical = 0
        max_slot_lag_bytes = 0
        max_replay_backlog = 0
        max_replay_delay_s = 0.0
        sync_standbys_count = 0
        cascading_standbys_count = sum(ev.get("is_cascading", 0) for ev in all_evidences)
        primary_timeline = primary_clients[0].timeline if primary_clients else 0

        # Query deep telemetry from primary if active
        active_primary = primary_clients[0] if primary_clients else None
        if active_primary:
            try:
                with active_primary.conn.cursor() as cur:
                    # Replication Standbys from primary's pg_stat_replication
                    try:
                        cur.execute("""
                            SELECT application_name, client_addr, state, sync_state, sync_priority,
                                   COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn), 0)::bigint AS replay_lag_bytes,
                                   COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), write_lsn), 0)::bigint AS write_lag_bytes,
                                   COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), flush_lsn), 0)::bigint AS flush_lag_bytes,
                                   EXTRACT(EPOCH FROM replay_lag)::float AS replay_lag_seconds
                            FROM pg_stat_replication;
                        """)
                        for r in cur.fetchall():
                            app_name, client_addr, st_state, sync_st, sync_prio, rep_b, wr_b, fl_b, rep_s = r
                            rep_lag_sec = round(float(rep_s or 0.0), 2)
                            is_sync = 1 if sync_st in ('sync', 'quorum') else 0
                            if is_sync:
                                sync_standbys_count += 1
                            max_replay_backlog = max(max_replay_backlog, rep_b)
                            max_replay_delay_s = max(max_replay_delay_s, rep_lag_sec)

                            replication_standbys.append({
                                "name": app_name or str(client_addr),
                                "client_addr": str(client_addr) if client_addr else "local",
                                "state": st_state or "streaming",
                                "sync_state": sync_st or "async",
                                "is_sync": is_sync,
                                "replay_lag_bytes": int(rep_b),
                                "write_lag_bytes": int(wr_b),
                                "flush_lag_bytes": int(fl_b),
                                "replay_lag_s": rep_lag_sec,
                                "status": 1
                            })
                    except Exception as e:
                        self._add_note(f"pg_stat_replication query error: {e}")

                    # Replication Slots from primary
                    try:
                        cur.execute("""
                            SELECT slot_name, plugin, slot_type, active,
                                   COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn), 0)::bigint AS wal_retained_bytes
                            FROM pg_replication_slots;
                        """)
                        for slot in cur.fetchall():
                            s_name, s_plugin, s_type, s_active, s_lag = slot
                            slots_total += 1
                            if s_active:
                                slots_active += 1
                            else:
                                slots_inactive += 1
                            if s_type == 'physical':
                                slots_physical += 1
                            else:
                                slots_logical += 1
                            max_slot_lag_bytes = max(max_slot_lag_bytes, int(s_lag or 0))

                            replication_slots.append({
                                "name": s_name,
                                "slot_type": s_type or "physical",
                                "plugin": s_plugin or "N/A",
                                "active": 1 if s_active else 0,
                                "wal_retained_bytes": int(s_lag or 0),
                                "status": 1
                            })
                    except Exception as e:
                        self._add_note(f"pg_replication_slots query error: {e}")

                    # Query core performance & DBA metrics against active primary
                    # 1. Cluster Name, Server PID, Superuser Reserved Connections
                    try:
                        cur.execute("SELECT current_setting('cluster_name');")
                        cn = cur.fetchone()[0]
                        results["Cluster Name"] = cn if cn else "postgres_cluster"
                    except Exception:
                        results["Cluster Name"] = "postgres_cluster"

                    try:
                        cur.execute("SELECT pg_backend_pid();")
                        results["Server PID"] = int(cur.fetchone()[0])
                    except Exception:
                        pass

                    try:
                        cur.execute("SELECT current_setting('superuser_reserved_connections')::int;")
                        results["Superuser Reserved Connections"] = int(cur.fetchone()[0])
                    except Exception:
                        results["Superuser Reserved Connections"] = 3

                    # 2. Standalone metrics for primary
                    cur.execute("SELECT version();")
                    results["Server Version"] = cur.fetchone()[0]

                    cur.execute("SELECT FLOOR(EXTRACT(EPOCH FROM current_timestamp - pg_postmaster_start_time()))::bigint;")
                    results["Uptime"] = int(cur.fetchone()[0])

                    cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema');")
                    results["Table Count"] = int(cur.fetchone()[0])

                    cur.execute("SELECT count(*) FROM pg_database WHERE datistemplate = false;")
                    results["Database Count"] = int(cur.fetchone()[0])

                    cur.execute("SELECT count(*) FROM pg_locks;")
                    results["Locks Count"] = int(cur.fetchone()[0])

                    cur.execute("SELECT count(*) FROM pg_stat_activity WHERE state = 'active';")
                    results["Active Queries"] = int(cur.fetchone()[0])

                    cur.execute("SELECT count(*) FROM pg_stat_activity WHERE state = 'active' AND wait_event IS NOT NULL;")
                    results["Active Waiting Queries"] = int(cur.fetchone()[0])

                    cur.execute("SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend';")
                    results["Active Connections"] = int(cur.fetchone()[0])

                    cur.execute("SELECT setting::int FROM pg_settings WHERE name = 'max_connections';")
                    results["Max Connections"] = int(cur.fetchone()[0])
                    results["Available Connections"] = max(0, results["Max Connections"] - results["Active Connections"])
                    results["Connection Utilization Percent"] = round((results["Active Connections"] / max(results["Max Connections"], 1)) * 100.0, 2)

                    cur.execute("SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction';")
                    results["Transactions Idle In Transaction"] = int(cur.fetchone()[0])

                    cur.execute("SELECT count(*) FROM pg_stat_activity WHERE xact_start IS NOT NULL;")
                    results["Transactions Open"] = int(cur.fetchone()[0])

                    cur.execute("SELECT COALESCE(MAX(EXTRACT(EPOCH FROM now() - xact_start))::bigint, 0) FROM pg_stat_activity WHERE state <> 'idle' AND xact_start IS NOT NULL;")
                    results["Oldest Running Transaction Age"] = int(cur.fetchone()[0])

                    # 3. DB Stats & Throughput
                    cur.execute("SELECT sum(xact_commit), sum(xact_rollback), sum(conflicts) FROM pg_stat_database;")
                    tx_row = cur.fetchone()
                    results["Total Commits"] = int(tx_row[0] or 0)
                    results["Total Rollbacks"] = int(tx_row[1] or 0)
                    results["Total Conflicts"] = int(tx_row[2] or 0)

                    cur.execute("SELECT sum(tup_inserted), sum(tup_updated), sum(tup_deleted), sum(tup_fetched), sum(tup_returned), sum(blks_read), sum(blks_hit) FROM pg_stat_database;")
                    io_row = cur.fetchone()
                    results["Total Rows Inserted"] = int(io_row[0] or 0)
                    results["Total Rows Updated"] = int(io_row[1] or 0)
                    results["Total Rows Deleted"] = int(io_row[2] or 0)
                    results["Total Rows Fetched"] = int(io_row[3] or 0)
                    results["Total Rows Returned"] = int(io_row[4] or 0)
                    results["Total Block Reads"] = int(io_row[5] or 0)
                    results["Total Block Hits"] = int(io_row[6] or 0)

                    tot_blks = results["Total Block Hits"] + results["Total Block Reads"]
                    results["Cache Hit Ratio"] = round((results["Total Block Hits"] / tot_blks * 100.0), 2) if tot_blks > 0 else 100.0

                    # 4. Heap & Index statistics
                    try:
                        cur.execute("SELECT COALESCE(sum(heap_blks_read), 0), COALESCE(sum(heap_blks_hit), 0) FROM pg_statio_user_tables;")
                        hp = cur.fetchone()
                        results["Heap Blocks Read"] = int(hp[0] or 0)
                        results["Heap Blocks Hit"] = int(hp[1] or 0)
                    except Exception:
                        results["Heap Blocks Read"] = 0
                        results["Heap Blocks Hit"] = 0

                    try:
                        cur.execute("SELECT COALESCE(sum(idx_scan), 0), COALESCE(sum(idx_tup_read), 0), COALESCE(sum(idx_tup_fetch), 0) FROM pg_stat_user_tables;")
                        idx = cur.fetchone()
                        results["Index Scans"] = int(idx[0] or 0)
                        results["Index Rows Read"] = int(idx[1] or 0)
                        results["Index Rows Fetched"] = int(idx[2] or 0)
                    except Exception:
                        results["Index Scans"] = 0
                        results["Index Rows Read"] = 0
                        results["Index Rows Fetched"] = 0

                    # 5. Dead Tuples and TxID Age
                    try:
                        cur.execute("SELECT COALESCE(sum(n_dead_tup), 0)::bigint FROM pg_stat_user_tables;")
                        results["Dead Tuples"] = int(cur.fetchone()[0])
                    except Exception:
                        results["Dead Tuples"] = 0

                    try:
                        cur.execute("SELECT COALESCE(max(age(datfrozenxid)), 0)::bigint FROM pg_database WHERE datallowconn = true;")
                        results["Oldest Transaction ID Age"] = int(cur.fetchone()[0])
                    except Exception:
                        results["Oldest Transaction ID Age"] = 0

                    # 6. Checkpoints & BGWriter
                    is_pg17 = active_primary.server_version_num >= 170000
                    if is_pg17:
                        cur.execute("""
                            SELECT c.num_timed, c.num_requested, c.write_time, c.sync_time, c.buffers_written,
                                   b.buffers_clean, b.maxwritten_clean, b.buffers_alloc
                            FROM pg_stat_checkpointer c, pg_stat_bgwriter b;
                        """)
                        bg = cur.fetchone()
                        results["Checkpoints Timed"] = int(bg[0] or 0)
                        results["Checkpoints Req"] = int(bg[1] or 0)
                        results["Checkpoint Write Time"] = int(bg[2] or 0)
                        results["Checkpoint Sync Time"] = int(bg[3] or 0)
                        results["Buffers Checkpoint"] = int(bg[4] or 0)
                        results["Buffers Clean"] = int(bg[5] or 0)
                        results["Maxwritten Clean"] = int(bg[6] or 0)
                        results["Buffers Alloc"] = int(bg[7] or 0)
                    else:
                        cur.execute("""
                            SELECT checkpoints_timed, checkpoints_req, checkpoint_write_time, checkpoint_sync_time,
                                   buffers_checkpoint, buffers_clean, maxwritten_clean, buffers_alloc,
                                   buffers_backend, buffers_backend_fsync
                            FROM pg_stat_bgwriter;
                        """)
                        bg = cur.fetchone()
                        results["Checkpoints Timed"] = int(bg[0] or 0)
                        results["Checkpoints Req"] = int(bg[1] or 0)
                        results["Checkpoint Write Time"] = int(bg[2] or 0)
                        results["Checkpoint Sync Time"] = int(bg[3] or 0)
                        results["Buffers Checkpoint"] = int(bg[4] or 0)
                        results["Buffers Clean"] = int(bg[5] or 0)
                        results["Maxwritten Clean"] = int(bg[6] or 0)
                        results["Buffers Alloc"] = int(bg[7] or 0)
                        results["Buffers Backend"] = int(bg[8] or 0)
                        results["Buffers Backend Fsync"] = int(bg[9] or 0)

                    # 7. Sessions (PG 14+)
                    if active_primary.server_version_num >= 140000:
                        cur.execute("SELECT sum(sessions), sum(sessions_abandoned), sum(sessions_fatal), sum(sessions_killed) FROM pg_stat_database;")
                        ses = cur.fetchone()
                        results["Total Sessions"] = int(ses[0] or 0)
                        results["Total Sessions Abandoned"] = int(ses[1] or 0)
                        results["Total Sessions Fatal"] = int(ses[2] or 0)
                        results["Total Sessions Killed"] = int(ses[3] or 0)

                    # 8. WAL & Archiving Telemetry (ALWAYS emitted per Step 1)
                    cur.execute("SELECT current_setting('archive_mode');")
                    arch_mode = cur.fetchone()[0]
                    results["Archive Mode"] = arch_mode

                    try:
                        cur.execute("SELECT archived_count, failed_count, last_archived_wal FROM pg_stat_archiver;")
                        arc = cur.fetchone()
                        results["Archive Status Success"] = int(arc[0] or 0)
                        results["Archive Status Failed"] = int(arc[1] or 0)
                        results["Last Archived WAL File"] = str(arc[2] or "0")
                    except Exception:
                        results["Archive Status Success"] = 0
                        results["Archive Status Failed"] = 0
                        results["Last Archived WAL File"] = "0"

                    try:
                        cur.execute("SELECT count(*) FROM pg_ls_archive_statusdir() WHERE name LIKE '%.ready';")
                        results["Archive Ready Files Count"] = int(cur.fetchone()[0])
                    except Exception:
                        results["Archive Ready Files Count"] = 0

                    # WAL Positions in MB
                    cur.execute("SELECT ROUND(pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0') / 1024.0 / 1024.0, 2);")
                    results["WAL Write Position"] = float(cur.fetchone()[0])

                    cur.execute("SELECT ROUND(pg_wal_lsn_diff(pg_current_wal_insert_lsn(), '0/0') / 1024.0 / 1024.0, 2);")
                    results["WAL Insert Position"] = float(cur.fetchone()[0])

                    cur.execute("SELECT ROUND(pg_wal_lsn_diff(pg_current_wal_flush_lsn(), '0/0') / 1024.0 / 1024.0, 2);")
                    results["WAL Flush Position"] = float(cur.fetchone()[0])

                    # WAL Files Count (segments only) and Total Size
                    try:
                        cur.execute("SELECT count(*), COALESCE(ROUND(SUM(size) / 1024.0 / 1024.0, 2), 0) FROM pg_ls_waldir() WHERE name ~ '^[0-9A-F]{24}$';")
                        w_row = cur.fetchone()
                        results["WAL Files Count"] = int(w_row[0] or 0)
                        results["WAL Total Size"] = float(w_row[1] or 0.0)
                    except Exception:
                        results["WAL Files Count"] = 0
                        results["WAL Total Size"] = 0.0

                    # 9. Recovery Conflicts: sum real conflicts from standbys
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

                    # 10. Per-DB Child Tables
                    cur.execute("""
                        SELECT d.datname AS name, s.numbackends as active_connections,
                               ROUND(pg_database_size(d.datname) / 1024 / 1024, 2) AS size_in_mb,
                               tup_inserted as rows_inserted, tup_updated as rows_updated,
                               tup_deleted as rows_deleted, tup_fetched as rows_fetched,
                               tup_returned as rows_returned, blks_read as block_reads, blks_hit as block_hits
                        FROM pg_database d JOIN pg_stat_database s ON d.oid = s.datid;
                    """)
                    db_stats_rows = []
                    for row in cur.fetchall():
                        db_stats_rows.append({
                            "name": row[0],
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

                    if active_primary.server_version_num >= 140000:
                        cur.execute("""
                            SELECT datname as name, xact_commit as commits, xact_rollback as rollbacks, conflicts,
                                   sessions, sessions_abandoned, sessions_fatal, sessions_killed,
                                   session_time, active_time as sessions_active_time,
                                   idle_in_transaction_time as session_idle_in_transaction_time
                            FROM pg_stat_database;
                        """)
                    else:
                        cur.execute("""
                            SELECT datname as name, xact_commit as commits, xact_rollback as rollbacks, conflicts
                            FROM pg_stat_database;
                        """)
                    tx_stats_rows = []
                    for row in cur.fetchall():
                        r_dict = {"name": row[0], "commits": int(row[1] or 0), "rollbacks": int(row[2] or 0), "conflicts": int(row[3] or 0)}
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
                self._add_note(f"Primary deep query error: {e}")
                results["Stats_per_DB"] = []
                results["Tranasctions_and_Session_per_Database"] = []
        else:
            self._add_note("Cluster alert: No reachable primary node detected")
            results["Stats_per_DB"] = []
            results["Tranasctions_and_Session_per_Database"] = []
            results["Archive Mode"] = "unknown"
            results["Archive Status Success"] = 0
            results["Archive Status Failed"] = 0
            results["Archive Ready Files Count"] = 0
            results["Last Archived WAL File"] = "0"
            results["WAL Write Position"] = 0.0
            results["WAL Insert Position"] = 0.0
            results["WAL Flush Position"] = 0.0
            results["WAL Files Count"] = 0
            results["WAL Total Size"] = 0.0
            results["Conflicts Tablespace"] = 0
            results["Conflicts Lock"] = 0
            results["Conflicts Snapshot"] = 0
            results["Conflicts Buffer Pin"] = 0
            results["Conflicts Deadlock"] = 0
            results["Recovery Conflicts Total"] = 0

        # Close all client connections
        for cli in probed_clients:
            cli.close()

        # Top-level cluster & replication counts
        standbys_expected = max(0, nodes_total - primary_count)
        standbys_streaming = len(replication_standbys)
        standby_disconnect_flag = 1 if standbys_expected != standbys_streaming else 0

        if nodes_up == 0:
            results["status"] = 0

        results["Nodes Total"] = int(nodes_total)
        results["Nodes Up"] = int(nodes_up)
        results["Primary Count"] = int(primary_count)
        results["No Primary Flag"] = int(no_primary_flag)
        results["Split Brain Flag"] = int(split_brain_flag)
        results["Primary Timeline"] = int(primary_timeline)

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
        results["Physical Slots"] = int(slots_physical)
        results["Logical Slots"] = int(slots_logical)
        results["Max Slot Lag Bytes"] = int(max_slot_lag_bytes)

        # Tabular Data (Enforce Site24x7 25-row limit)
        results["Cluster_Nodes"] = cluster_nodes[:25]
        results["Replication_Standbys"] = replication_standbys[:25]
        results["Replication_Slots"] = replication_slots[:25]
        results["Node_Activity"] = node_activity_table[:25]
        results["Node_Throughput"] = node_throughput_table[:25]
        results["Node_Checkpoints"] = node_checkpoints_table[:25]
        results["Standby_Conflicts"] = standby_conflicts_table[:25]

        # Site24x7 Child Discovery
        results["s247config"] = {
            "childdiscovery": [
                "Tranasctions_and_Session_per_Database",
                "Stats_per_DB"
            ]
        }

        # Assert total tables stay at or under 10
        active_tables = [
            k for k, v in results.items()
            if isinstance(v, list) and k not in ("tabs", "units", "s247config")
        ]
        assert len(active_tables) <= 10, f"Table limit exceeded: {len(active_tables)} tables present"

        # Apply tabs and nested units
        results.update(copy.deepcopy(tabs))
        results["units"] = units

        if self.msg_notes:
            results["msg"] = "; ".join(self.msg_notes)

        return results


def run(param):
    """Site24x7 agent Python plugin entrypoint."""
    nodes = param.get("nodes") if param and param.get("nodes") else NODES
    username = param.get("username") if param and param.get("username") else USERNAME
    password = param.get("password") if param and param.get("password") else PASSWORD
    db = param.get("db") if param and param.get("db") else DB
    patroni_port = param.get("patroni_port") if param and param.get("patroni_port") else PATRONI_PORT
    cluster_type = param.get("cluster_type") if param and param.get("cluster_type") else CLUSTER_TYPE

    collector = PostgresClusterCollector(nodes, username, password, db, patroni_port, cluster_type)
    return collector.collect()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Site24x7 PostgreSQL Cluster Plugin")
    parser.add_argument('--nodes', help='Comma-separated nodes (host:port, name=host:port, or host:port:patroni_port)', default=NODES)
    parser.add_argument('--username', help='PostgreSQL username', default=USERNAME)
    parser.add_argument('--password', help='PostgreSQL password', default=PASSWORD)
    parser.add_argument('--db', help='Database name', default=DB)
    parser.add_argument('--patroni_port', help='Patroni REST port or mapping', default=PATRONI_PORT)
    parser.add_argument('--cluster_type', help='Cluster type override or auto', default=CLUSTER_TYPE)
    args = parser.parse_args()

    collector = PostgresClusterCollector(
        nodes_str=args.nodes,
        username=args.username,
        password=args.password,
        db=args.db,
        patroni_port=args.patroni_port,
        cluster_type=args.cluster_type
    )
    result = collector.collect()
    print(json.dumps(result))
