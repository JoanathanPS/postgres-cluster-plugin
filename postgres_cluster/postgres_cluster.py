#!/usr/bin/env python3
"""
PostgreSQL Cluster Monitoring Plugin for Site24x7 (v5 Engine).
Architecture: Catalogue -> Capabilities -> Truth Model -> Health Object -> Emitter.
Single-file deliverable conforming to Site24x7 hard constraints.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import concurrent.futures.thread
import copy
import hashlib
import json
import math
import os
import re
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import weakref
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import psycopg2
    import psycopg2.extensions
    HAVE_PSYCOPG2 = True
except ImportError:
    HAVE_PSYCOPG2 = False


# -----------------------------------------------------------------------------
# 0. PLATFORM CONSTANTS & ABSOLUTE LIMITS (Site24x7 Enforced)
# -----------------------------------------------------------------------------
PLUGIN_VERSION = 6
HEARTBEAT_REQUIRED = True

MAX_TABLES = 10
MAX_COLUMNS = 15
MAX_COLS = MAX_COLUMNS
MAX_ROWS = 25
MAX_STRING_COLS = 5       # includes 'name'
MAX_NAME_CHARS = 520
MAX_STRING_CHARS = 100
MAX_METRICS = 200
MAX_MSG_CHARS = 180

RESERVED_KEYS = {
    "plugin_version", "heartbeat_required", "status", "msg",
    "units", "tabs", "s4z7config", "s247config"
}

# -----------------------------------------------------------------------------
# 1. ENUMS (Integer encoded for Site24x7 table constraints)
# -----------------------------------------------------------------------------
# Overall & Node Status
STATUS_DOWN = 0
STATUS_UP = 1

# Node Roles
ROLE_UNKNOWN = 0
ROLE_PRIMARY = 1
ROLE_STANDBY = 2
ROLE_WITNESS = 3
ROLE_OFFLINE = 4
ROLE_CASCADING = 5
ROLE_DELAYED = 6
ROLE_STANDBY_LEADER = 7

ROLE_NAMES = {
    ROLE_UNKNOWN: "unknown",
    ROLE_PRIMARY: "primary",
    ROLE_STANDBY: "standby",
    ROLE_WITNESS: "witness",
    ROLE_OFFLINE: "offline",
    ROLE_CASCADING: "cascading",
    ROLE_DELAYED: "delayed",
    ROLE_STANDBY_LEADER: "standby_leader",
}

# Standby Sync States
SYNC_ASYNC = 0
SYNC_SYNC = 1
SYNC_QUORUM = 2

# Cluster Health Severities
HEALTH_OK = 0
HEALTH_WARN = 1
HEALTH_CRITICAL = 2

HEALTH_NAMES = {
    HEALTH_OK: "OK",
    HEALTH_WARN: "WARN",
    HEALTH_CRITICAL: "CRITICAL",
}

# Health Condition Codes (Stable, alertable, documented)
HEALTH_CODE_OK = 0
HEALTH_CODE_PRIMARY_DOWN = 1
HEALTH_CODE_SPLIT_BRAIN = 2
HEALTH_CODE_NO_STANDBYS_STREAMING = 3
HEALTH_CODE_SYNC_STANDBYS_DEFICIT = 4
HEALTH_CODE_SLOT_LOST_OR_CRITICAL = 5
HEALTH_CODE_XID_CRITICAL = 6
HEALTH_CODE_NO_FAILOVER_CANDIDATE = 7
HEALTH_CODE_AUTH_FAIL = 8
HEALTH_CODE_CONN_FAIL = 9

HEALTH_CODE_NODE_DOWN = 10
HEALTH_CODE_STANDBY_LAG_HIGH = 11
HEALTH_CODE_INACTIVE_SLOT_WARN = 12
HEALTH_CODE_TIMELINE_MISMATCH = 13
HEALTH_CODE_RECENT_FAILOVER = 14
HEALTH_CODE_XID_WARN = 15
HEALTH_CODE_HIGH_CONNECTIONS = 16
HEALTH_CODE_ARCHIVE_FAILING = 17
HEALTH_CODE_STALE_STATS = 18
HEALTH_CODE_UNSUPPORTED_VERSION = 19

# Error Taxonomy Codes
ERR_CONFIG_INVALID = "config_error"
ERR_AUTH_FAILURE = "auth_failure"
ERR_UNREACHABLE = "unreachable"
ERR_METRIC_UNAVAILABLE = "metric_unavailable"
ERR_POOLER_DETECTED = "pooler_detected"
ERR_UNSUPPORTED_CLUSTER = "unsupported_cluster"
ERR_BUDGET_EXCEEDED = "budget_exceeded"

# Version Capability Map (query/feature -> minimum version tuple)
REQUIRES: Dict[str, Tuple[int, int]] = {
    "pg_control_system": (10, 0),
    "pg_control_checkpoint": (10, 0),
    "pg_stat_wal_receiver": (9, 6),
    "pg_current_wal_lsn": (10, 0),
    "pg_wal_lsn_diff": (10, 0),
    "pg_last_wal_receive_lsn": (10, 0),
    "pg_last_wal_replay_lsn": (10, 0),
    "pg_stat_replication_lags": (10, 0),
    "pg_stat_activity_wait_events": (9, 6),
    "pg_stat_activity_backend_type": (10, 0),
    "pg_stat_wal": (14, 0),
    "pg_stat_io": (16, 0),
}
VERSION_FLOOR: Tuple[int, int] = (9, 6)
TOPOLOGY_UNKNOWN = 0
TOPOLOGY_PATRONI = 1
TOPOLOGY_REPMGR = 2
TOPOLOGY_NATIVE = 3
TOPOLOGY_MULTI_MASTER = 4
TOPOLOGY_CITUS = 5
TOPOLOGY_CNPG = 6
TOPOLOGY_STOLON = 7

# Monitoring Modes
MODE_AUTO = "auto"
MODE_STANDALONE = "standalone"
MODE_CLUSTER = "cluster"
VALID_MONITOR_MODES = {MODE_AUTO, MODE_STANDALONE, MODE_CLUSTER}

# Patroni States
PATRONI_STATE_UNKNOWN = 0
PATRONI_STATE_RUNNING = 1
PATRONI_STATE_STOPPED = 2
PATRONI_STATE_STARTING = 3
PATRONI_STATE_STOPPED_FAILED = 4
PATRONI_STATE_CRASHED = 5
PATRONI_STATE_PAUSED = 6
PATRONI_STATE_CREATING_STANDBY = 7
PATRONI_STATE_NA = 8

PATRONI_STATE_MAP = {
    "running": PATRONI_STATE_RUNNING,
    "stopped": PATRONI_STATE_STOPPED,
    "starting": PATRONI_STATE_STARTING,
    "stop failed": PATRONI_STATE_STOPPED_FAILED,
    "crashed": PATRONI_STATE_CRASHED,
    "paused": PATRONI_STATE_PAUSED,
    "creating replica": PATRONI_STATE_CREATING_STANDBY,
}

# Replication Slot Risk
RISK_OK = 0
RISK_WARN = 1
RISK_CRITICAL = 2
RISK_LOST = 3

# Replication Link Types & States
LINK_PHYSICAL = 0
LINK_LOGICAL = 1

LINK_STATE_STREAMING = 0
LINK_STATE_CATCHUP = 1
LINK_STATE_STOPPED = 2
LINK_STATE_PAUSED = 3
LINK_STATE_UNKNOWN = 4

SLOT_PHYSICAL = 0
SLOT_LOGICAL = 1


# -----------------------------------------------------------------------------
# 1.1 PURE HELPERS: VERSION PARSING & ADDRESS MAPPING
# -----------------------------------------------------------------------------
_VER_RE = re.compile(r"(\d+)(?:\.(\d+))?")

def parse_pg_version(raw: str) -> Tuple[int, int]:
    """
    Tolerantly extracts (major, minor) integers from real-world PostgreSQL strings:
    - '16.2' -> (16, 2)
    - '10.0' -> (10, 0)
    - '12.3_TDE_1.0' -> (12, 3)
    - '11.22-rds.20241121' -> (11, 22)
    - '12beta1' -> (12, 0)
    - '17devel' -> (17, 0)
    - 'PostgreSQL 16.15 (Debian 16.15-1.pgdg13+2)...' -> (16, 15)
    Returns (0, 0) on total failure without crashing.
    """
    if not raw or not isinstance(raw, str):
        return 0, 0
    clean = raw.strip()
    # If string contains 'PostgreSQL x.y', strip prefix
    idx = clean.find("PostgreSQL ")
    if idx != -1:
        clean = clean[idx + len("PostgreSQL "):]
    match = _VER_RE.search(clean)
    if not match:
        return 0, 0
    major = int(match.group(1))
    minor = int(match.group(2)) if match.group(2) is not None else 0
    return major, minor


def parse_address_map(raw_map: str) -> Dict[str, str]:
    """
    Parses comma-separated key=value address translations:
    'pg-node1:5432=127.0.0.1:5441,pg-node1:8008=127.0.0.1:8001'
    Used for container port forwarding and NAT bridging.
    """
    out: Dict[str, str] = {}
    if not raw_map or not isinstance(raw_map, str):
        return out
    for entry in raw_map.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" in entry:
            src, dst = entry.split("=", 1)
            out[src.strip()] = dst.strip()
    return out


def normalize_host(host: str) -> str:
    """Normalizes IPv4, bracketed IPv6, and localhost addresses."""
    if not host or not isinstance(host, str):
        return ""
    h = host.strip()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    return h


def safe_name(raw: Any) -> str:
    """Site24x7 table name cleaner: alphanumeric only, <= 520 chars."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(raw))[:MAX_NAME_CHARS]


def safe_int(val: Any, default: int = 0) -> int:
    """Safely converts value to int without raising ValueError/TypeError."""
    try:
        if val is None:
            return default
        return int(float(val))
    except (ValueError, TypeError):
        return default


def safe_float(val: Any, default: float = 0.0) -> float:
    """Safely converts value to float without raising ValueError/TypeError."""
    try:
        if val is None:
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


# -----------------------------------------------------------------------------
# 1.2 NODE CLIENT & QUERY HYGIENE (Never Harm Monitored Server)
# -----------------------------------------------------------------------------
# 1. THREADING & CONNECTION CLIENT
# -----------------------------------------------------------------------------
class DaemonThreadPoolExecutor(concurrent.futures.ThreadPoolExecutor):
    """ThreadPoolExecutor that creates daemon threads so interpreter exit is never blocked."""
    def _adjust_thread_count(self):
        if self._idle_semaphore.acquire(timeout=0):
            return
        def weakref_cb(_, q=self._work_queue):
            q.put(None)
        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = '%s_%d' % (self._thread_name_prefix or self, num_threads)
            t = threading.Thread(name=thread_name, target=concurrent.futures.thread._worker,
                                 args=(weakref.ref(self, weakref_cb),
                                       self._work_queue,
                                       self._initializer,
                                       self._initargs),
                                 daemon=True)
            t.start()
            self._threads.add(t)
            concurrent.futures.thread._threads_queues[t] = self._work_queue


class NodeClient:
    """
    Resilient single-node connection manager.
    Enforces strict connection timeouts, query statement timeouts,
    read-only transactions, query comment tagging, and clean resource cleanup.
    """
    def __init__(
        self,
        name: str,
        host: str,
        port: int = 5432,
        user: str = "site24x7",
        password: str = "",
        dbname: str = "postgres",
        sslmode: str = "prefer",
        sslrootcert: str = "",
        sslcert: str = "",
        sslkey: str = "",
        connect_timeout: int = 3,
        statement_timeout_ms: int = 3000
    ):
        self.name = name
        self.host = normalize_host(host)
        self.port = port
        self.user = user
        self.password = password
        self.dbname = dbname
        self.sslmode = sslmode
        self.sslrootcert = sslrootcert
        self.sslcert = sslcert
        self.sslkey = sslkey
        self.connect_timeout = connect_timeout
        self.statement_timeout_ms = statement_timeout_ms

        self.conn = None
        self.is_connected = False
        self.is_supported = True
        self.version_num = 0
        self.version_tuple = (0, 0)
        self.is_recovery = False
        self.system_identifier = ""
        self.settings: Dict[str, Any] = {}
        self.warnings: List[str] = []
        self.auth_failed: bool = False
        self.auth_error: str = ""
        self.last_error_code: Optional[str] = None
        self.last_error_class: Optional[str] = None

    def requires(self, feature: str) -> bool:
        """Returns True if this node meets or exceeds the required version for feature."""
        req = REQUIRES.get(feature, VERSION_FLOOR)
        return self.version_tuple >= req

    def connect(self) -> bool:
        """Establishes connection with protective GUCs and timeout limits."""
        if not HAVE_PSYCOPG2:
            self.warnings.append("psycopg2 module not installed")
            return False

        options = (
            f"-c statement_timeout={self.statement_timeout_ms} "
            f"-c lock_timeout=2000 "
            f"-c idle_in_transaction_session_timeout=5000 "
            f"-c default_transaction_read_only=on"
        )

        conn_host = self.host
        if conn_host == "localhost":
            conn_host = "127.0.0.1"

        conn_kwargs: Dict[str, Any] = {
            "host": conn_host,
            "port": self.port,
            "user": self.user,
            "dbname": self.dbname,
            "connect_timeout": self.connect_timeout,
            "application_name": "site24x7_pgcluster",
            "options": options,
        }

        if self.password:
            conn_kwargs["password"] = self.password

        if self.sslmode:
            conn_kwargs["sslmode"] = self.sslmode
        if self.sslrootcert and os.path.exists(self.sslrootcert):
            conn_kwargs["sslrootcert"] = self.sslrootcert
        if self.sslcert and os.path.exists(self.sslcert):
            conn_kwargs["sslcert"] = self.sslcert
        if self.sslkey and os.path.exists(self.sslkey):
            conn_kwargs["sslkey"] = self.sslkey

        try:
            self.conn = psycopg2.connect(**conn_kwargs)
            self.conn.autocommit = True
            self.is_connected = True
            self._load_node_capabilities()
            return True
        except Exception as e:
            self.is_connected = False
            err_str = str(e)
            pgcode = getattr(e, "pgcode", None)
            is_auth = (pgcode in ("28000", "28P01")) or ("password authentication failed" in err_str.lower())
            if is_auth:
                self.auth_failed = True
                self.auth_error = f"auth failed for user {self.user} on {self.name}"
                self.warnings.append(self.auth_error)
            else:
                self.warnings.append(f"Connection failed to {self.host}:{self.port} ({e})")
            return False

    def _load_node_capabilities(self):
        """Discovers version, recovery state, system_identifier, and key settings."""
        # 1. Recovery state
        row = self.query_one("SELECT pg_is_in_recovery();")
        if row is not None:
            self.is_recovery = bool(row[0])

        # 2. Version
        vnum = getattr(self.conn, "server_version", None)
        if vnum:
            self.version_num = vnum
            self.version_tuple = (vnum // 10000, (vnum % 10000) // 100)
        else:
            v_str = self.query_one("SELECT version();")
            if v_str:
                self.version_tuple = parse_pg_version(v_str[0])
                self.version_num = self.version_tuple[0] * 10000 + self.version_tuple[1] * 100

        # Floor check: minimum supported PostgreSQL version is 9.6
        if self.version_tuple and self.version_tuple < VERSION_FLOOR:
            self.is_supported = False
            self.warnings.append(f"unsupported_version: PostgreSQL {self.version_tuple[0]}.{self.version_tuple[1]} is below minimum 9.6 floor")
            return

        # 3. System Identifier (pg_control_system in PG 10+)
        if self.requires("pg_control_system"):
            id_row = self.query_one("SELECT system_identifier FROM pg_control_system();")
            if id_row:
                self.system_identifier = str(id_row[0])

        # 4. Critical GUC settings
        guc_rows = self.query_all("""
            SELECT name, setting FROM pg_settings
            WHERE name IN (
                'max_connections', 'autovacuum_freeze_max_age',
                'wal_segment_size', 'max_wal_senders', 'synchronous_standby_names',
                'archive_mode'
            );
        """)
        for r in guc_rows:
            if len(r) >= 2:
                self.settings[r[0]] = r[1]
            elif len(r) == 1:
                self.settings["max_connections"] = r[0]

    def query_one(self, sql: str, params: Optional[Tuple] = None) -> Optional[Tuple]:
        """Executes query and returns first row or None. If query failed, self.last_error_class is set."""
        rows = self.query_all(sql, params)
        if rows is None:
            return None
        return rows[0] if rows else None

    def query_all(self, sql: str, params: Optional[Tuple] = None) -> Optional[List[Tuple]]:
        """Executes query with comment tag prefix and safely closes cursor. Returns None on query failure."""
        if not self.conn or not self.is_connected:
            self.last_error_class = "connection"
            return None
        tagged_sql = f"/* service='site24x7_pgcluster' */ {sql}"
        cur = None
        try:
            cur = self.conn.cursor()
            cur.execute(tagged_sql, params)
            self.last_error_code = None
            self.last_error_class = None
            if cur.description or getattr(cur, "_rows", None):
                return cur.fetchall()
            return []
        except Exception as e:
            pgcode = getattr(e, "pgcode", "") or ""
            if pgcode == "42501":
                err_class = "insufficient_privilege"
            elif pgcode == "42P01":
                err_class = "undefined_table"
            elif pgcode.startswith("08"):
                err_class = "connection"
            elif pgcode == "57014":
                err_class = "query_timeout"
            else:
                err_class = "query_error"
            self.last_error_code = pgcode
            self.last_error_class = err_class
            self.warnings.append(f"Query failed on {self.name} [{err_class}]: {e}")
            return None
        finally:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass

    def close(self):
        """Closes connection gracefully."""
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            finally:
                self.conn = None
                self.is_connected = False


# -----------------------------------------------------------------------------
# 1.3 HEALTH OBJECT & REASONING ENGINE (Pure Function)
# -----------------------------------------------------------------------------
class Health:
    """Encapsulates cluster health decision with actionable remediation text."""
    __slots__ = ("code", "severity", "fact", "quantified", "context", "hint")

    def __init__(self, code: int, severity: int, fact: str,
                 quantified: str = "", context: str = "", hint: str = ""):
        self.code = code
        self.severity = severity
        self.fact = fact
        self.quantified = quantified
        self.context = context
        self.hint = hint

    def format_msg(self) -> str:
        """
        Renders Site24x7 single-line monitor message <= 180 chars:
        '<SEVERITY> <code>: <fact> (<quantified>) | <context> | hint: <action>'
        """
        sev_name = HEALTH_NAMES.get(self.severity, "INFO")
        code_str = f"c{self.code}"
        msg = f"{sev_name} {code_str}: {self.fact}"
        if self.quantified:
            msg += f" ({self.quantified})"
        if self.context:
            msg += f" | {self.context}"
        if self.hint:
            msg += f" | hint: {self.hint}"
        return msg[:MAX_MSG_CHARS]


def evaluate_cluster_health(
    *,
    has_primary: bool,
    primary_name: str = "",
    primary_last_seen_s: int = 0,
    primary_last_seen_iso: str = "",
    nodes_up: int = 0,
    nodes_total: int = 0,
    timeline: int = 0,
    primaries_count: int = 0,
    is_multi_master: bool = False,
    expected_standbys: int = 0,
    streaming_standbys: int = 0,
    sync_standbys_expected: int = 0,
    sync_standbys_actual: int = 0,
    has_failover_candidate: bool = True,
    slot_lost: bool = False,
    max_slot_retained_bytes: int = 0,
    slot_crit_bytes: int = 10 * 1024 * 1024 * 1024,
    slot_warn_bytes: int = 1024 * 1024 * 1024,
    inactive_slots: int = 0,
    xid_wraparound_pct: float = 0.0,
    max_replay_lag_s: float = 0.0,
    max_replay_backlog_b: int = 0,
    replay_warn_s: float = 60.0,
    replay_warn_b: int = 100 * 1024 * 1024,
    timeline_spread: int = 0,
    failover_age_s: int = -1,
    failover_window_s: int = 900,
    conn_saturation_pct: float = 0.0,
    archive_failed: int = 0,
    stale_stats: int = 0,
    auth_failure: bool = False,
    auth_msg: str = "",
) -> Health:
    """
    Pure health reasoning engine. Evaluates criteria in strict precedence order:
    CRITICAL -> WARN -> OK.
    """
    # 0. Auth failure is classified separately and MUST NOT masquerade as primary down
    if auth_failure:
        fact_str = auth_msg if auth_msg else "authentication failure on one or more cluster nodes"
        return Health(
            code=HEALTH_CODE_AUTH_FAIL,
            severity=HEALTH_CRITICAL,
            fact=fact_str,
            quantified="auth error",
            context=f"{nodes_up}/{nodes_total} nodes up",
            hint="check monitor credentials in cfg"
        )

    # 1. CRITICAL: No primary reachable
    if not has_primary or primaries_count == 0:
        last_seen = f"last seen {primary_name} {primary_last_seen_s}s ago" if primary_name else "no prior primary"
        cand_hint = "failover --candidate" if has_failover_candidate else "manual recovery needed: no candidate"
        return Health(
            code=HEALTH_CODE_PRIMARY_DOWN if has_failover_candidate else HEALTH_CODE_NO_FAILOVER_CANDIDATE,
            severity=HEALTH_CRITICAL,
            fact="no primary reachable",
            quantified=last_seen,
            context=f"{nodes_up}/{nodes_total} nodes up, timeline {timeline}",
            hint=f"patronictl list; {cand_hint}"
        )

    # 2. CRITICAL: Split Brain (>1 concurrent writable primaries without active-active mesh)
    if primaries_count > 1 and not is_multi_master:
        return Health(
            code=HEALTH_CODE_SPLIT_BRAIN,
            severity=HEALTH_CRITICAL,
            fact="split brain detected: multiple concurrent primaries",
            quantified=f"{primaries_count} primaries active",
            context=f"{nodes_up}/{nodes_total} nodes up",
            hint="fence rogue primary immediately"
        )

    # 3. CRITICAL: 0 of N expected standbys streaming
    if expected_standbys > 0 and streaming_standbys == 0:
        return Health(
            code=HEALTH_CODE_NO_STANDBYS_STREAMING,
            severity=HEALTH_CRITICAL,
            fact="zero standbys streaming WAL from primary",
            quantified=f"0/{expected_standbys} streaming",
            context=f"timeline {timeline}",
            hint="check standby pg_is_in_recovery() and walsender logs"
        )

    # 4. CRITICAL: Sync Standbys Deficit
    if sync_standbys_expected > 0 and sync_standbys_actual < sync_standbys_expected:
        return Health(
            code=HEALTH_CODE_SYNC_STANDBYS_DEFICIT,
            severity=HEALTH_CRITICAL,
            fact="synchronous standbys below required quorum",
            quantified=f"{sync_standbys_actual}/{sync_standbys_expected} sync",
            context="durability compromised",
            hint="check synchronous_standby_names"
        )

    # 5. CRITICAL: Slot Lost or Critical WAL Retention
    if slot_lost or max_slot_retained_bytes >= slot_crit_bytes:
        retained_mb = round(max_slot_retained_bytes / (1024 * 1024), 1)
        return Health(
            code=HEALTH_CODE_SLOT_LOST_OR_CRITICAL,
            severity=HEALTH_CRITICAL,
            fact="replication slot lost or retaining dangerous WAL volume",
            quantified=f"slot WAL: {retained_mb} MB",
            context="risk of disk exhaustion",
            hint="pg_drop_replication_slot() or advance standby"
        )

    # 6. CRITICAL: Transaction ID Wraparound >= 95%
    if xid_wraparound_pct >= 95.0:
        return Health(
            code=HEALTH_CODE_XID_CRITICAL,
            severity=HEALTH_CRITICAL,
            fact="urgent: transaction ID wraparound impending",
            quantified=f"{xid_wraparound_pct:.1f}% wraparound",
            context="server forced read-only soon",
            hint="VACUUM FREEZE in single-user mode"
        )

    # -------------------------------------------------------------------------
    # WARNINGS
    # -------------------------------------------------------------------------
    # 7. WARN: Any Node Down
    if nodes_up < nodes_total:
        return Health(
            code=HEALTH_CODE_NODE_DOWN,
            severity=HEALTH_WARN,
            fact=f"{nodes_total - nodes_up} cluster node(s) unreachable",
            quantified=f"{nodes_up}/{nodes_total} up",
            context=f"primary: {primary_name}",
            hint="inspect offline node postmaster"
        )

    # 8. WARN: Standby Lag High
    if max_replay_lag_s > replay_warn_s or max_replay_backlog_b > replay_warn_b:
        lag_txt = f"{max_replay_lag_s:.1f}s" if max_replay_lag_s > replay_warn_s else f"{max_replay_backlog_b // (1024*1024)} MB"
        return Health(
            code=HEALTH_CODE_STANDBY_LAG_HIGH,
            severity=HEALTH_WARN,
            fact="standby replay lag exceeds threshold",
            quantified=f"lag: {lag_txt}",
            context=f"threshold: {replay_warn_s}s",
            hint="check standby I/O saturation"
        )

    # 9. WARN: Inactive Slot or Warn WAL Retention
    if inactive_slots > 0 or max_slot_retained_bytes >= slot_warn_bytes:
        return Health(
            code=HEALTH_CODE_INACTIVE_SLOT_WARN,
            severity=HEALTH_WARN,
            fact=f"{inactive_slots} inactive slot(s) retaining WAL",
            quantified=f"{max_slot_retained_bytes // (1024*1024)} MB",
            context="WAL accumulating",
            hint="verify slot consumer is running"
        )

    # 10. WARN: Timeline Mismatch
    if timeline_spread > 0:
        return Health(
            code=HEALTH_CODE_TIMELINE_MISMATCH,
            severity=HEALTH_WARN,
            fact="timeline disagreement across cluster nodes",
            quantified=f"spread: {timeline_spread}",
            context="stale standby on old timeline",
            hint="pg_rewind standby to primary"
        )

    # 11. WARN: Recent Failover within Window
    if 0 <= failover_age_s <= failover_window_s:
        age_m = failover_age_s // 60
        return Health(
            code=HEALTH_CODE_RECENT_FAILOVER,
            severity=HEALTH_WARN,
            fact="recent failover occurred within warning window",
            quantified=f"{age_m}m ago",
            context=f"promoted: {primary_name}",
            hint="verify previous primary re-joined as standby"
        )

    # 12. WARN: XID Wraparound >= 70%
    if xid_wraparound_pct >= 70.0:
        return Health(
            code=HEALTH_CODE_XID_WARN,
            severity=HEALTH_WARN,
            fact="autovacuum freeze required soon",
            quantified=f"{xid_wraparound_pct:.1f}% wraparound",
            context="approaching freeze max age",
            hint="check autovacuum settings"
        )

    # 13. WARN: High Connection Saturation >= 90%
    if conn_saturation_pct >= 90.0:
        return Health(
            code=HEALTH_CODE_HIGH_CONNECTIONS,
            severity=HEALTH_WARN,
            fact="connection pool near exhaustion",
            quantified=f"{conn_saturation_pct:.1f}% used",
            context="max_connections threshold",
            hint="scale connection pooler (pgBouncer)"
        )

    # 14. WARN: Archiver Failures Accumulating
    if archive_failed > 0:
        return Health(
            code=HEALTH_CODE_ARCHIVE_FAILING,
            severity=HEALTH_WARN,
            fact="WAL archiver errors detected",
            quantified=f"{archive_failed} failed archives",
            context="backup continuity at risk",
            hint="check archive_command script & storage"
        )

    # 15. WARN: Stale Statistics
    if stale_stats > 0:
        return Health(
            code=HEALTH_CODE_STALE_STATS,
            severity=HEALTH_WARN,
            fact="tables with stale statistics detected",
            quantified=f"{stale_stats} tables",
            context="query planner degraded",
            hint="run ANALYZE"
        )

    # Healthy OK State
    return Health(
        code=HEALTH_CODE_OK,
        severity=HEALTH_OK,
        fact=f"Cluster healthy: {nodes_up}/{nodes_total} nodes active",
        quantified=f"timeline {timeline}",
        context=f"primary: {primary_name}",
        hint="none"
    )


def evaluate_database_health(
    *,
    connected: bool,
    auth_failure: bool = False,
    auth_msg: str = "",
    unsupported_version: bool = False,
    version_str: str = "",
    conn_pct: float = 0.0,
    xid_wraparound_pct: float = 0.0,
    active_queries: int = 0,
    longest_query_s: int = 0,
    status_reason: str = "",
    is_recovery: bool = False,
    uptime_s: int = 0,
    archive_failed: int = 0,
) -> Health:
    """
    Health evaluation for standalone PostgreSQL instances.
    Evaluates database availability, authentication, resource utilization, and version.
    Never checks or requires primary/replica cluster topology.
    """
    # 0. Auth failure
    if auth_failure:
        fact_str = auth_msg if auth_msg else "authentication failed for user"
        return Health(
            code=HEALTH_CODE_AUTH_FAIL,
            severity=HEALTH_CRITICAL,
            fact=fact_str,
            quantified="auth error",
            context="standalone instance",
            hint="check monitor credentials in cfg"
        )

    # 1. Connectivity failure
    if not connected:
        fact_str = status_reason if status_reason else "connection refused or timed out"
        return Health(
            code=HEALTH_CODE_CONN_FAIL,
            severity=HEALTH_CRITICAL,
            fact=fact_str,
            quantified="unreachable",
            context="standalone instance",
            hint="check host, port and pg_hba.conf"
        )

    # 2. Unsupported version
    if unsupported_version:
        return Health(
            code=HEALTH_CODE_UNSUPPORTED_VERSION,
            severity=HEALTH_CRITICAL,
            fact=f"unsupported_version: PostgreSQL {version_str} < 9.6 floor",
            quantified="version unsupported",
            context="standalone instance",
            hint="upgrade PostgreSQL to 9.6 or later"
        )

    # 3. WARN / CRIT: XID wraparound
    if xid_wraparound_pct >= 90.0:
        return Health(
            code=HEALTH_CODE_XID_CRITICAL,
            severity=HEALTH_CRITICAL,
            fact="transaction ID wraparound imminent",
            quantified=f"{xid_wraparound_pct:.1f}% wraparound",
            context="critical freeze danger",
            hint="run VACUUM FREEZE immediately"
        )
    elif xid_wraparound_pct >= 70.0:
        return Health(
            code=HEALTH_CODE_XID_WARN,
            severity=HEALTH_WARN,
            fact="autovacuum freeze required soon",
            quantified=f"{xid_wraparound_pct:.1f}% wraparound",
            context="approaching freeze max age",
            hint="check autovacuum settings"
        )

    # 4. WARN / CRIT: Connection saturation
    if conn_pct >= 95.0:
        return Health(
            code=HEALTH_CODE_HIGH_CONNECTIONS,
            severity=HEALTH_CRITICAL,
            fact="connection pool exhausted",
            quantified=f"{conn_pct:.1f}% used",
            context="max_connections saturated",
            hint="increase max_connections or scale connection pooler"
        )
    elif conn_pct >= 90.0:
        return Health(
            code=HEALTH_CODE_HIGH_CONNECTIONS,
            severity=HEALTH_WARN,
            fact="connection pool near exhaustion",
            quantified=f"{conn_pct:.1f}% used",
            context="max_connections threshold",
            hint="scale connection pooler (pgBouncer)"
        )

    # 5. WARN: Archive failed
    if archive_failed > 0:
        return Health(
            code=HEALTH_CODE_ARCHIVE_FAILING,
            severity=HEALTH_WARN,
            fact="WAL archiver errors detected",
            quantified=f"{archive_failed} failed archives",
            context="backup continuity at risk",
            hint="check archive_command script & storage"
        )

    # OK: Standalone instance healthy
    role_label = "read-only standby" if is_recovery else "writable standalone"
    return Health(
        code=HEALTH_CODE_OK,
        severity=HEALTH_OK,
        fact=f"standalone database healthy ({role_label})",
        quantified=f"uptime {uptime_s}s, {active_queries} active queries",
        context=role_label,
        hint="none"
    )


# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# 2. TAB DEFINITIONS (Exact 8 Tabs, strict order)
# -----------------------------------------------------------------------------
TAB_ORDER = [
    "Diagnosis",
    "Primary",
    "Nodes",
    "Replication",
    "Health and Capacity",
    "Performance",
    "WAL and Archiver",
    "Workload",
]

# Child Table Schemas for units and tabs
TABLE_UNITS: Dict[str, Dict[str, str]] = {
    "Cluster_Nodes": {
        "status": "status",
        "role": "status",
        "last_seen_s": "s",
        "timeline": "timeline",
        "replay_lag_s": "s",
        "replay_lag_bytes": "bytes",
        "conn_pct": "%",
        "resp_ms": "ms",
        "sync": "flag",
        "patroni_state": "status",
        "xact_age_s": "s",
    },
    "Node_Snapshot": {
        "status": "status",
        "version_num": "status",
        "uptime_s": "s",
        "active_queries": "queries",
        "idle_in_txn": "connections",
        "longest_query_s": "s",
        "temp_bytes": "bytes",
        "dead_tuples": "tuples",
    },
    "Replication_Links": {
        "status": "status",
        "sent_lag_b": "bytes",
        "write_lag_b": "bytes",
        "flush_lag_b": "bytes",
        "replay_lag_b": "bytes",
        "replay_lag_s": "s",
    },
    "Replication_Slots": {
        "status": "status",
        "active": "flag",
        "retained_mb": "MB",
    },
    "Database_Stats": {
        "status": "status",
        "size_mb": "MB",
        "connections": "connections",
        "commit_ratio": "%",
        "cache_hit_ratio": "%",
    },
    "Wait_Events": {
        "status": "status",
        "sessions": "sessions",
    },
    "Topology": {
        "status": "status",
        "node_count": "nodes",
        "timeline": "timeline",
    },
}

TABLE_TABS: Dict[str, str] = {
    "Topology": "Diagnosis",
    "Cluster_Nodes": "Nodes",
    "Node_Snapshot": "Nodes",
    "Replication_Links": "Replication",
    "Replication_Slots": "Replication",
    "Database_Stats": "Workload",
    "Wait_Events": "Workload",
}

OFFICIAL_COMPAT_UNITS: Dict[str, str] = {
    "Active Connections": "connections",
    "Max Connections": "connections",
    "Uptime": "s",
    "Total Rows Deleted": "rows",
    "Total Rows Fetched": "rows",
    "Total Rows Inserted": "rows",
    "Total Rows Returned": "rows",
    "Total Rows Updated": "rows",
    "Total Commits": "transactions",
    "Total Rollbacks": "transactions",
    "Total Sessions": "sessions",
    "Total Sessions Abandoned": "sessions",
    "Total Sessions Fatal": "sessions",
    "Total Sessions Killed": "sessions",
    "Idle Transactions": "transactions",
    "Transactions Open": "transactions",
    "Locks Count": "locks",
    "Database Count": "databases",
    "Table Count": "count",
    "Active Queries": "queries",
    "Active Waiting Queries": "queries",
    "Checkpoints Timed": "checkpoints",
    "Checkpoints Req": "checkpoints",
    "Checkpoint Write Time": "ms",
    "Checkpoint Sync Time": "ms",
    "Buffers Checkpoint": "buffers",
    "Buffers Clean": "buffers",
    "Maxwritten Clean": "buffers",
    "Buffers Backend": "buffers",
    "Buffers Backend Fsync": "buffers",
    "Buffers Alloc": "buffers",
    "Index Scans": "scans",
    "Index Rows Read": "rows",
    "Index Rows Fetched": "rows",
    "Heap Blocks Read": "blocks",
    "Heap Blocks Hit": "blocks",
    "Cache Hit Ratio": "%",
    "Total Block Reads": "blocks",
    "Total Block Hits": "blocks",
    "Total Conflicts": "conflicts",
}

OFFICIAL_COMPAT_TABLE_UNITS: Dict[str, Dict[str, str]] = {
    "Stats_per_DB": {
        "active_connections": "connections",
        "size_in_mb": "MB",
        "rows_inserted": "rows",
        "rows_updated": "rows",
        "rows_deleted": "rows",
        "rows_fetched": "rows",
        "rows_returned": "rows",
        "block_reads": "blocks",
        "block_hits": "blocks",
    },
    "Transactions_Per_Database": {
        "commits": "transactions",
        "rollbacks": "transactions",
        "conflicts": "conflicts",
        "sessions": "sessions",
        "sessions_abandoned": "sessions",
        "sessions_fatal": "sessions",
        "sessions_killed": "sessions",
        "session_time": "ms",
        "sessions_active_time": "ms",
        "idle_in_txn_time": "ms",
    },
}

OFFICIAL_COMPAT_TABS: Dict[str, Dict[str, Any]] = {
    "DB and IO stats": {
        "order": "8",
        "tablist": [
            "Stats_per_DB",
            "Total Rows Deleted",
            "Total Rows Fetched",
            "Total Rows Inserted",
            "Total Rows Returned",
            "Total Rows Updated",
            "Total Block Hits",
            "Total Block Reads",
            "Database Count",
            "Table Count",
            "Index Scans",
            "Index Rows Read",
            "Index Rows Fetched",
            "Heap Blocks Read",
            "Heap Blocks Hit",
            "Cache Hit Ratio",
        ],
    },
    "BG Writer": {
        "order": "9",
        "tablist": [
            "Checkpoints Timed",
            "Checkpoints Req",
            "Checkpoint Write Time",
            "Checkpoint Sync Time",
            "Buffers Checkpoint",
            "Buffers Clean",
            "Maxwritten Clean",
            "Buffers Backend",
            "Buffers Backend Fsync",
            "Buffers Alloc",
        ],
    },
    "Transactions and Sessions": {
        "order": "10",
        "tablist": [
            "Transactions_Per_Database",
            "Total Commits",
            "Total Rollbacks",
            "Total Conflicts",
            "Total Sessions",
            "Total Sessions Abandoned",
            "Total Sessions Fatal",
            "Total Sessions Killed",
            "Idle Transactions",
            "Transactions Open",
            "Active Connections",
            "Max Connections",
            "Uptime",
            "Locks Count",
            "Active Queries",
            "Active Waiting Queries",
            "Server Version",
        ],
    },
}

# -----------------------------------------------------------------------------
# 3. METRIC CATALOGUE (Single Source of Truth)
# -----------------------------------------------------------------------------
# Every top-level metric MUST be declared here.
# units{} and tabs{} are programmatically generated from this structure.
METRICS: List[Dict[str, Any]] = [
    # -------------------------------------------------------------------------
    # TAB 1: Diagnosis (Cluster overview, health code, timelines, failover)
    # -------------------------------------------------------------------------
    {"name": "Cluster_Health", "unit": "status", "tab": "Diagnosis", "type": int,
     "desc": "Cluster health severity: 0=OK, 1=WARN, 2=CRITICAL"},
    {"name": "Health_Code", "unit": "status", "tab": "Diagnosis", "type": int,
     "desc": "Stable numeric health condition code for alerting"},
    {"name": "Cluster_Role", "unit": "status", "tab": "Diagnosis", "type": int,
     "desc": "Observed role of target cluster entry point"},
    {"name": "Topology_Type", "unit": "status", "tab": "Diagnosis", "type": int,
     "desc": "Detected cluster manager: 1=Patroni, 2=repmgr, 3=Native Physical, etc."},
    {"name": "Nodes_Total", "unit": "nodes", "tab": "Diagnosis", "type": int,
     "desc": "Total active and historical nodes tracked in cluster"},
    {"name": "Nodes_Up", "unit": "nodes", "tab": "Diagnosis", "type": int,
     "desc": "Number of currently reachable nodes"},
    {"name": "Nodes_Down", "unit": "nodes", "tab": "Diagnosis", "type": int,
     "desc": "Number of currently unreachable or offline nodes"},
    {"name": "Nodes_Omitted", "unit": "nodes", "tab": "Diagnosis", "type": int,
     "desc": "Nodes omitted beyond the 25-row Site24x7 limit"},
    {"name": "Primary_Timeline", "unit": "timeline", "tab": "Diagnosis", "type": int,
     "desc": "Current timeline ID of the primary node"},
    {"name": "Timeline_Spread", "unit": "timeline", "tab": "Diagnosis", "type": int,
     "desc": "Spread between maximum and minimum observed node timelines"},
    {"name": "Failover_Age_s", "unit": "s", "tab": "Diagnosis", "type": int,
     "desc": "Seconds elapsed since the last detected failover"},
    {"name": "Failover_Count_24h", "unit": "failovers", "tab": "Diagnosis", "type": int,
     "desc": "Total failovers detected in the last 24 hours"},
    {"name": "Collect_Warnings", "unit": "events", "tab": "Diagnosis", "type": int,
     "desc": "Number of non-fatal warnings encountered during collection"},
    {"name": "Auth_Failure_Flag", "unit": "flag", "tab": "Diagnosis", "type": int,
     "desc": "1 if authentication failure occurred on any node, 0 otherwise"},
    {"name": "Budget_Exceeded", "unit": "flag", "tab": "Diagnosis", "type": int,
     "desc": "1 if cycle deadline was exceeded, 0 otherwise"},

    # String metrics in Diagnosis tab (string metrics have no unit in Site24x7)
    {"name": "Health_Reason", "unit": "", "tab": "Diagnosis", "type": str,
     "desc": "Concise explanation of current health code"},
    {"name": "First_Attention_Node", "unit": "", "tab": "Diagnosis", "type": str,
     "desc": "First node requiring operator attention"},
    {"name": "First_Attention_Reason", "unit": "", "tab": "Diagnosis", "type": str,
     "desc": "Why First_Attention_Node requires intervention"},
    {"name": "Action_Hint", "unit": "", "tab": "Diagnosis", "type": str,
     "desc": "Suggested remediation command or action"},
    {"name": "Last_Failover_To", "unit": "", "tab": "Diagnosis", "type": str,
     "desc": "Node promoted in the most recent failover"},

    # -------------------------------------------------------------------------
    # TAB 2: Primary (Core health, clamping, and activity of primary node)
    # -------------------------------------------------------------------------
    {"name": "Primary_Up", "unit": "flag", "tab": "Primary", "type": int,
     "desc": "1 if primary node is reachable and serving, 0 if down"},
    {"name": "Primary_Data_Age_s", "unit": "s", "tab": "Primary", "type": int,
     "desc": "Age of primary metrics in seconds (0 when live)"},
    {"name": "Primary_Data_Stale", "unit": "flag", "tab": "Primary", "type": int,
     "desc": "1 if primary data exceeds clamp TTL (1800s), 0 otherwise"},
    {"name": "Primary_Uptime_s", "unit": "s", "tab": "Primary", "type": int,
     "desc": "Primary PostgreSQL postmaster uptime in seconds"},
    {"name": "Primary_Connections", "unit": "connections", "tab": "Primary", "type": int,
     "desc": "Active client connections on primary"},
    {"name": "Primary_Max_Connections", "unit": "connections", "tab": "Primary", "type": int,
     "desc": "max_connections configuration setting on primary"},
    {"name": "Primary_Connection_Pct", "unit": "%", "tab": "Primary", "type": float,
     "desc": "Connection utilization percentage on primary"},
    {"name": "Primary_Active_Queries", "unit": "queries", "tab": "Primary", "type": int,
     "desc": "Queries currently in active execution on primary"},
    {"name": "Primary_Idle_In_Txn", "unit": "connections", "tab": "Primary", "type": int,
     "desc": "Connections currently in idle-in-transaction on primary"},
    {"name": "Primary_Longest_Txn_s", "unit": "s", "tab": "Primary", "type": int,
     "desc": "Duration of longest running transaction on primary"},
    {"name": "Primary_Blocked_Locks", "unit": "locks", "tab": "Primary", "type": int,
     "desc": "Sessions waiting on lock acquisition on primary"},
    {"name": "Primary_Commits_s", "unit": "transactions", "tab": "Primary", "type": float,
     "desc": "Transaction commits per second on primary"},
    {"name": "Primary_Rollbacks_s", "unit": "transactions", "tab": "Primary", "type": float,
     "desc": "Transaction rollbacks per second on primary"},
    {"name": "Primary_Tup_Inserted_s", "unit": "rows", "tab": "Primary", "type": float,
     "desc": "Tuples inserted per second on primary"},
    {"name": "Primary_Tup_Updated_s", "unit": "rows", "tab": "Primary", "type": float,
     "desc": "Tuples updated per second on primary"},
    {"name": "Primary_Tup_Deleted_s", "unit": "rows", "tab": "Primary", "type": float,
     "desc": "Tuples deleted per second on primary"},
    {"name": "Primary_Cache_Hit_Ratio", "unit": "%", "tab": "Primary", "type": float,
     "desc": "Buffer pool cache hit ratio on primary"},
    {"name": "Primary_Blks_Read_s", "unit": "blocks", "tab": "Primary", "type": float,
     "desc": "Disk blocks read per second on primary"},
    {"name": "Primary_WAL_LSN_MB", "unit": "MB", "tab": "Primary", "type": float,
     "desc": "Primary current WAL write position converted to megabytes"},
    {"name": "Primary_WAL_Rate_MBs", "unit": "MB", "tab": "Primary", "type": float,
     "desc": "Primary WAL bytes generated per second"},
    {"name": "Primary_WAL_Dir_MB", "unit": "MB", "tab": "Primary", "type": float,
     "desc": "Total disk space used by pg_wal directory on primary"},
    {"name": "Primary_Chkpts_Req_1h", "unit": "checkpoints", "tab": "Primary", "type": int,
     "desc": "Requested checkpoints in the last hour on primary"},
    {"name": "Primary_Chkpt_Write_ms", "unit": "ms", "tab": "Primary", "type": float,
     "desc": "Average checkpoint write time in milliseconds"},
    {"name": "Primary_Dead_Tuples", "unit": "tuples", "tab": "Primary", "type": int,
     "desc": "Estimated dead tuples awaiting vacuum on primary"},
    {"name": "Primary_XID_Age", "unit": "xids", "tab": "Primary", "type": int,
     "desc": "Maximum transaction ID age relative to freeze horizon"},
    {"name": "Primary_XID_Wrap_Pct", "unit": "%", "tab": "Primary", "type": float,
     "desc": "Percentage toward autovacuum_freeze_max_age wraparound"},
    {"name": "Primary_Archive_Ok", "unit": "files", "tab": "Primary", "type": int,
     "desc": "Total WAL segments successfully archived"},
    {"name": "Primary_Archive_Failed", "unit": "files", "tab": "Primary", "type": int,
     "desc": "Total WAL segments that failed archiving"},
    {"name": "Primary_Archive_Ready", "unit": "files", "tab": "Primary", "type": int,
     "desc": "WAL segments waiting to be archived (.ready)"},
    {"name": "Primary_Archive_Lag_s", "unit": "s", "tab": "Primary", "type": int,
     "desc": "Seconds elapsed since last successful WAL archive"},
    {"name": "Primary_Sessions_Killed", "unit": "sessions", "tab": "Primary", "type": int,
     "desc": "Sessions terminated due to conflicts or timeouts"},

    # String metrics in Primary tab
    {"name": "Primary_Node", "unit": "", "tab": "Primary", "type": str,
     "desc": "Name or address of current primary node"},
    {"name": "Primary_Data_Source", "unit": "", "tab": "Primary", "type": str,
     "desc": "Source of primary metrics: live, clamped, or none"},

    # -------------------------------------------------------------------------
    # TAB 3: Nodes (Cluster-wide node roll-up)
    # -------------------------------------------------------------------------
    {"name": "Standbys_Expected", "unit": "nodes", "tab": "Nodes", "type": int,
     "desc": "Number of standbys expected to stream from primary"},
    {"name": "Standbys_Streaming", "unit": "nodes", "tab": "Nodes", "type": int,
     "desc": "Number of standbys actively streaming WAL from primary"},
    {"name": "Standby_Disconnect_Flag", "unit": "flag", "tab": "Nodes", "type": int,
     "desc": "1 if any expected standby is disconnected, 0 otherwise"},
    {"name": "Sync_Standby_Count", "unit": "nodes", "tab": "Nodes", "type": int,
     "desc": "Number of synchronous standbys currently connected"},
    {"name": "Cascading_Standby_Count", "unit": "nodes", "tab": "Nodes", "type": int,
     "desc": "Number of cascading standbys connected to replicas"},
    {"name": "Delayed_Standby_Count", "unit": "nodes", "tab": "Nodes", "type": int,
     "desc": "Number of deliberately delayed standbys configured"},
    {"name": "Max_Replay_Lag_s", "unit": "s", "tab": "Nodes", "type": float,
     "desc": "Maximum replay lag across all active standbys in seconds"},
    {"name": "Max_Replay_Backlog", "unit": "bytes", "tab": "Nodes", "type": int,
     "desc": "Maximum replay byte backlog across all standbys"},
    {"name": "Worst_Conn_Pct", "unit": "%", "tab": "Nodes", "type": float,
     "desc": "Highest connection utilization percentage among all nodes"},
    {"name": "Slowest_Resp_ms", "unit": "ms", "tab": "Nodes", "type": float,
     "desc": "Slowest node response time in milliseconds"},

    # String metrics in Nodes tab
    {"name": "Worst_Conn_Node", "unit": "", "tab": "Nodes", "type": str,
     "desc": "Node experiencing highest connection saturation"},
    {"name": "Slowest_Node", "unit": "", "tab": "Nodes", "type": str,
     "desc": "Node exhibiting slowest response time during probe"},

    # -------------------------------------------------------------------------
    # TAB 4: Replication (Replication slots, mesh, and logical telemetry)
    # -------------------------------------------------------------------------
    {"name": "Replication_Slots_Total", "unit": "slots", "tab": "Replication", "type": int,
     "desc": "Total physical and logical replication slots"},
    {"name": "Replication_Slots_Active", "unit": "slots", "tab": "Replication", "type": int,
     "desc": "Active replication slots currently streaming"},
    {"name": "Inactive_Slots_Count", "unit": "slots", "tab": "Replication", "type": int,
     "desc": "Inactive replication slots retaining WAL"},
    {"name": "Max_Slot_Retained_MB", "unit": "MB", "tab": "Replication", "type": float,
     "desc": "Maximum WAL retained by any single replication slot"},
    {"name": "Slot_Risk", "unit": "risk", "tab": "Replication", "type": int,
     "desc": "Highest slot risk: 0=OK, 1=WARN, 2=CRITICAL, 3=LOST"},
    {"name": "Logical_Replication_Used", "unit": "flag", "tab": "Replication", "type": int,
     "desc": "1 if logical subscriptions or publications exist, 0 otherwise"},
    {"name": "Mesh_Links_Declared", "unit": "links", "tab": "Replication", "type": int,
     "desc": "Total mesh links declared in active-active topology"},
    {"name": "Mesh_Links_Active", "unit": "links", "tab": "Replication", "type": int,
     "desc": "Active streaming mesh links"},
    {"name": "Mesh_Disconnect_Flag", "unit": "flag", "tab": "Replication", "type": int,
     "desc": "1 if any declared mesh link is disconnected, 0 otherwise"},
    {"name": "Max_Logical_Lag_s", "unit": "s", "tab": "Replication", "type": float,
     "desc": "Maximum lag across logical subscriptions"},
    {"name": "Subscription_Apply_Errors", "unit": "errors", "tab": "Replication", "type": int,
     "desc": "Cumulative subscription apply errors from pg_stat_subscription_stats"},
    {"name": "Subscription_Conflicts", "unit": "conflicts", "tab": "Replication", "type": int,
     "desc": "Cumulative subscription conflict count"},

    # -------------------------------------------------------------------------
    # TAB 5: Health and Capacity (Storage, connection, and freeze limits)
    # -------------------------------------------------------------------------
    {"name": "XID_Wraparound_Pct", "unit": "%", "tab": "Health and Capacity", "type": float,
     "desc": "Cluster-wide maximum XID wraparound percentage"},
    {"name": "Max_Temp_MB", "unit": "MB", "tab": "Health and Capacity", "type": float,
     "desc": "Maximum temporary file usage across databases"},
    {"name": "Dead_Tuples_Total", "unit": "tuples", "tab": "Health and Capacity", "type": int,
     "desc": "Total dead tuples awaiting autovacuum across databases"},
    {"name": "Long_Running_Queries", "unit": "queries", "tab": "Health and Capacity", "type": int,
     "desc": "Queries executing longer than warning threshold (60s)"},
    {"name": "Blocked_Sessions", "unit": "sessions", "tab": "Health and Capacity", "type": int,
     "desc": "Total sessions currently blocked waiting on locks"},

    # -------------------------------------------------------------------------
    # TAB 6: Performance (Throughput, buffer pool, checkpoints, background writer)
    # -------------------------------------------------------------------------
    {"name": "Cache_Hit_Ratio", "unit": "%", "tab": "Performance", "type": float,
     "desc": "Cluster buffer pool cache hit ratio"},
    {"name": "Index_Hit_Ratio", "unit": "%", "tab": "Performance", "type": float,
     "desc": "Index scan buffer hit ratio"},
    {"name": "Blks_Read_s", "unit": "blocks", "tab": "Performance", "type": float,
     "desc": "Disk blocks read per second"},
    {"name": "Blks_Hit_s", "unit": "blocks", "tab": "Performance", "type": float,
     "desc": "Buffer pool hits per second"},
    {"name": "Checkpoints_Timed", "unit": "checkpoints", "tab": "Performance", "type": int,
     "desc": "Scheduled checkpoints completed"},
    {"name": "Checkpoints_Req", "unit": "checkpoints", "tab": "Performance", "type": int,
     "desc": "Forced/requested checkpoints completed"},
    {"name": "Checkpoint_Write_ms", "unit": "ms", "tab": "Performance", "type": float,
     "desc": "Average checkpoint write duration in milliseconds"},
    {"name": "Buffers_Backend", "unit": "buffers", "tab": "Performance", "type": int,
     "desc": "Buffers written directly by backends instead of bgwriter"},
    {"name": "Maxwritten_Clean", "unit": "events", "tab": "Performance", "type": int,
     "desc": "Times bgwriter stopped clean scan because it wrote too many buffers"},
    {"name": "Backend_Fsync", "unit": "events", "tab": "Performance", "type": int,
     "desc": "Times a backend had to execute its own fsync"},
    {"name": "Seq_Scans_s", "unit": "scans", "tab": "Performance", "type": float,
     "desc": "Sequential table scans per second"},
    {"name": "Idx_Scans_s", "unit": "scans", "tab": "Performance", "type": float,
     "desc": "Index scans per second"},

    # -------------------------------------------------------------------------
    # TAB 7: WAL and Archiver (WAL generation, archiving status)
    # -------------------------------------------------------------------------
    {"name": "WAL_LSN_MB", "unit": "MB", "tab": "WAL and Archiver", "type": float,
     "desc": "Total WAL bytes written mapped to megabytes"},
    {"name": "WAL_Rate_MBs", "unit": "MB", "tab": "WAL and Archiver", "type": float,
     "desc": "Cluster-wide WAL production rate in MB per second"},
    {"name": "WAL_Dir_MB", "unit": "MB", "tab": "WAL and Archiver", "type": float,
     "desc": "Current total size of pg_wal directory"},
    {"name": "Archive_Success", "unit": "files", "tab": "WAL and Archiver", "type": int,
     "desc": "Total WAL segments successfully archived"},
    {"name": "Archive_Failed", "unit": "files", "tab": "WAL and Archiver", "type": int,
     "desc": "Failed WAL archive attempts"},
    {"name": "Archive_Ready", "unit": "files", "tab": "WAL and Archiver", "type": int,
     "desc": "WAL segments currently pending archive"},

    # String metrics in WAL and Archiver tab
    {"name": "Archive_Mode", "unit": "", "tab": "WAL and Archiver", "type": str,
     "desc": "archive_mode setting: on, off, or always"},
    {"name": "Last_Archived_WAL", "unit": "", "tab": "WAL and Archiver", "type": str,
     "desc": "Filename of most recently archived WAL segment"},

    # -------------------------------------------------------------------------
    # TAB 8: Workload (Databases, sessions, and top wait events)
    # -------------------------------------------------------------------------
    {"name": "DB_Count", "unit": "databases", "tab": "Workload", "type": int,
     "desc": "Number of connectable databases in cluster"},
    {"name": "DB_Total_Size_MB", "unit": "MB", "tab": "Workload", "type": float,
     "desc": "Total disk size of all databases combined in MB"},
    {"name": "Active_Sessions", "unit": "sessions", "tab": "Workload", "type": int,
     "desc": "Total sessions actively executing queries"},
    {"name": "Idle_Sessions", "unit": "sessions", "tab": "Workload", "type": int,
     "desc": "Total connected idle sessions"},

    # String metrics in Workload tab
    {"name": "Largest_DB", "unit": "", "tab": "Workload", "type": str,
     "desc": "Name of largest database by on-disk size"},
    {"name": "Wait_Event_Top", "unit": "", "tab": "Workload", "type": str,
     "desc": "Most frequent non-idle wait event across backends"},

    # -------------------------------------------------------------------------
    # SELF-INSTRUMENTATION & STATE DIAGNOSTICS (Assigned to Diagnosis Tab)
    # -------------------------------------------------------------------------
    {"name": "Collect_Time_ms", "unit": "ms", "tab": "Diagnosis", "type": float,
     "desc": "Plugin execution time in milliseconds"},
    {"name": "Queries_Run", "unit": "queries", "tab": "Diagnosis", "type": int,
     "desc": "Total SQL queries executed this collection cycle"},
    {"name": "State_Persistent", "unit": "flag", "tab": "Diagnosis", "type": int,
     "desc": "1 if state file is stored on durable storage, 0 if volatile (/tmp)"},
    {"name": "State_Age_s", "unit": "s", "tab": "Diagnosis", "type": int,
     "desc": "Seconds since state file was last updated"},
    {"name": "State_IO_Errors", "unit": "errors", "tab": "Diagnosis", "type": int,
     "desc": "Cumulative state file read/write I/O errors"},
    {"name": "Rate_Warmup_Flag", "unit": "flag", "tab": "Diagnosis", "type": int,
     "desc": "1 during first poll cycle while rate baselines warm up, 0 otherwise"},

    # String diagnostics in Diagnosis tab
    {"name": "Slowest_Scope", "unit": "", "tab": "Diagnosis", "type": str,
     "desc": "Probe scope that took the longest time to execute"},
    {"name": "State_File", "unit": "", "tab": "Diagnosis", "type": str,
     "desc": "Active filesystem path of the state file (truncated <= 100)"},
    {"name": "State_Reason", "unit": "", "tab": "Diagnosis", "type": str,
     "desc": "Diagnostic status message for the state store layer"},
]

# Assert metric budget invariant at module import time
assert len(METRICS) <= MAX_METRICS, f"Catalogue exceeds {MAX_METRICS} metrics: found {len(METRICS)}"


# -----------------------------------------------------------------------------
# 4. TAB & UNIT GENERATOR
# -----------------------------------------------------------------------------
def build_tabs_and_units(metric_defs: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Programmatically generates the 'tabs' and 'units' dictionaries from the
    declarative METRICS catalogue and TABLE_UNITS to guarantee 100% synchronization.
    """
    tabs_dict: Dict[str, Any] = {}
    units_dict: Dict[str, Any] = {}

    # Initialize tabs in strict specified order
    for idx, tab_name in enumerate(TAB_ORDER, start=1):
        tabs_dict[tab_name] = {
            "order": str(idx),
            "tablist": []
        }

    # Add child tables to their assigned tabs
    for tbl_name, target_tab in TABLE_TABS.items():
        if target_tab in tabs_dict:
            tabs_dict[target_tab]["tablist"].append(tbl_name)

    # Add metrics to tabs and units
    for item in metric_defs:
        name = item["name"]
        tab = item["tab"]
        unit = item.get("unit", "")
        mtype = item.get("type", int)

        if tab in tabs_dict:
            tabs_dict[tab]["tablist"].append(name)
        else:
            raise ValueError(f"Metric '{name}' assigned to unknown tab '{tab}'")

        # String metrics do NOT have units in Site24x7
        if mtype != str and unit:
            units_dict[name] = unit

    # Include nested child table schemas in units
    for tbl_name, tbl_cols in TABLE_UNITS.items():
        units_dict[tbl_name] = copy.deepcopy(tbl_cols)

    return tabs_dict, units_dict


TABS_DEF, UNITS_DEF = build_tabs_and_units(METRICS)


def prune_omitted_metric(payload: Dict[str, Any], metric_name: str) -> None:
    """Removes a metric from payload, units, and tabs to maintain 100% schema synchronization."""
    payload.pop(metric_name, None)
    if "units" in payload and isinstance(payload["units"], dict):
        payload["units"].pop(metric_name, None)
    tabs_field = payload.get("tabs", {})
    tabs_data = tabs_field.get("tabs", {}) if "tabs" in tabs_field and isinstance(tabs_field.get("tabs"), dict) else tabs_field
    if isinstance(tabs_data, dict):
        for tab_info in tabs_data.values():
            if isinstance(tab_info, dict) and "tablist" in tab_info:
                tab_info["tablist"] = [t for t in tab_info["tablist"] if t != metric_name]


# -----------------------------------------------------------------------------
# 5. PLATFORM LIMIT VALIDATOR (Shipped in file, executed every cycle)
# -----------------------------------------------------------------------------
def validate_output(payload: Dict[str, Any]) -> List[str]:
    """
    Enforces all documented Site24x7 platform limits against the generated payload:
    - <= 10 tables, <= 15 cols, <= 25 rows, <= 5 string cols (incl name)
    - name <= 520, string cell <= 100
    - <= 200 metrics
    - Every tab metric is emitted, and every emitted metric has a unit and a tab
    - Row status is integer (0 or 1)
    - No NaN / Infinity values in floats
    Appends violations to returned list without raising exceptions.
    """
    violations: List[str] = []

    # 1. Reserved structural keys
    for r in ("plugin_version", "heartbeat_required", "status"):
        if r not in payload:
            violations.append(f"Missing required top-level key '{r}'")

    if not isinstance(payload.get("status"), int) or payload.get("status") not in (0, 1):
        violations.append(f"Top-level 'status' must be int 0 or 1, got {payload.get('status')!r}")

    # 2. Table detection & validation
    tables: Dict[str, List[Dict[str, Any]]] = {}
    metrics: Dict[str, Any] = {}

    for k, v in payload.items():
        if k in RESERVED_KEYS:
            continue
        if isinstance(v, list) and (not v or all(isinstance(r, dict) for r in v)):
            tables[k] = v
        else:
            metrics[k] = v

    if len(tables) > MAX_TABLES:
        violations.append(f"Table count {len(tables)} exceeds limit {MAX_TABLES}")

    for tname, rows in tables.items():
        if len(rows) > MAX_ROWS:
            violations.append(f"Table '{tname}' row count {len(rows)} exceeds limit {MAX_ROWS}")

        seen_names: Set[str] = set()
        for idx, row in enumerate(rows):
            if "name" not in row:
                violations.append(f"Table '{tname}' row {idx} missing required 'name' column")
            else:
                name_str = str(row["name"])
                if len(name_str) > MAX_NAME_CHARS:
                    violations.append(f"Table '{tname}' name exceeds {MAX_NAME_CHARS} chars: {len(name_str)}")
                if name_str in seen_names:
                    violations.append(f"Table '{tname}' duplicate row name '{name_str}'")
                seen_names.add(name_str)

            if "status" in row and (not isinstance(row["status"], int) or row["status"] not in (0, 1)):
                violations.append(f"Table '{tname}' row '{row.get('name')}' status must be int 0 or 1")

            # Check column limits & string columns count
            if len(row) > MAX_COLUMNS:
                violations.append(f"Table '{tname}' row '{row.get('name')}' column count {len(row)} > {MAX_COLUMNS}")

            string_cols = [c for c, val in row.items() if isinstance(val, str)]
            if len(string_cols) > MAX_STRING_COLS:
                violations.append(f"Table '{tname}' string columns {len(string_cols)} > {MAX_STRING_COLS} (cols: {string_cols})")

            for c, val in row.items():
                if c != "name" and isinstance(val, str) and len(val) > MAX_STRING_CHARS:
                    violations.append(f"Table '{tname}' col '{c}' value exceeds {MAX_STRING_CHARS} chars: {len(val)}")
                if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                    violations.append(f"Table '{tname}' col '{c}' contains NaN or Infinity")

    # 3. Metric budget & scalar validation
    if len(metrics) > MAX_METRICS:
        violations.append(f"Top-level metric count {len(metrics)} exceeds limit {MAX_METRICS}")

    for mname, mval in metrics.items():
        if mname in RESERVED_KEYS:
            violations.append(f"Metric name '{mname}' collides with reserved Site24x7 key")
        if isinstance(mval, float) and (math.isnan(mval) or math.isinf(mval)):
            violations.append(f"Metric '{mname}' contains NaN or Infinity")
        if isinstance(mval, str) and len(mval) > MAX_STRING_CHARS:
            violations.append(f"Metric '{mname}' string value exceeds {MAX_STRING_CHARS} chars")

    # 4. Tab and unit synchronization checks
    tabs_field = payload.get("tabs", {})
    tabs_data = tabs_field.get("tabs", {}) if "tabs" in tabs_field else tabs_field
    units_data = payload.get("units", {})

    all_tab_metrics: Set[str] = set()
    for t_name, t_content in tabs_data.items():
        for t_m in t_content.get("tablist", []):
            all_tab_metrics.add(t_m)
            if t_m not in metrics and t_m not in tables:
                violations.append(f"TAB_METRIC_NEVER_EMITTED: '{t_m}' declared in tab '{t_name}' but not emitted")
            if t_m in metrics and not isinstance(metrics[t_m], str) and t_m not in units_data:
                violations.append(f"TAB_METRIC_NO_UNIT: '{t_m}' declared in tab '{t_name}' has no unit")
            if t_m in tables and t_m not in units_data:
                violations.append(f"TAB_TABLE_NO_UNIT: Table '{t_m}' declared in tab '{t_name}' has no unit schema")

    for mname in metrics.keys():
        if mname not in all_tab_metrics:
            violations.append(f"EMITTED_METRIC_NO_TAB: '{mname}' emitted but not present in any tab")

    return violations


# -----------------------------------------------------------------------------
# 6. SKELETON EMITTER & ENTRY POINT (Step 0)
# -----------------------------------------------------------------------------
def get_empty_payload() -> Dict[str, Any]:
    """Generates an initial zero-state payload guaranteed to pass all limits."""
    payload: Dict[str, Any] = {
        "plugin_version": PLUGIN_VERSION,
        "heartbeat_required": HEARTBEAT_REQUIRED,
        "status": STATUS_UP,
        "units": copy.deepcopy(UNITS_DEF),
        "tabs": copy.deepcopy(TABS_DEF),
    }

    # Populate every declared metric with default zero/empty values
    for m in METRICS:
        mname = m["name"]
        mtype = m.get("type", int)
        if mtype == int:
            payload[mname] = 0
        elif mtype == float:
            payload[mname] = 0.0
        elif mtype == str:
            payload[mname] = "none"
        else:
            payload[mname] = 0

    # Populate declared child tables as empty lists
    for tbl in TABLE_UNITS.keys():
        payload[tbl] = []

    return payload


def self_test() -> int:
    """Exercises in-process assertions and validators without database access."""
    print("=================================================================", flush=True)
    print(f" Site24x7 PostgreSQL Cluster Plugin v{PLUGIN_VERSION} Self-Test (Skeleton Gate)", flush=True)
    print("=================================================================", flush=True)

    fails = 0

    def check(desc: str, ok: bool, extra: str = ""):
        nonlocal fails
        if ok:
            print(f"  [PASS] {desc}", flush=True)
        else:
            print(f"  [FAIL] {desc} {extra}", flush=True)
            fails += 1

    # 1. Catalogue Invariants
    check("Catalogue metric count <= 200", len(METRICS) <= MAX_METRICS, f"got {len(METRICS)}")
    check("All 8 tabs defined in order", [k for k in (TABS_DEF.get("tabs", TABS_DEF)).keys()] == TAB_ORDER)

    metric_names = [m["name"] for m in METRICS]
    check("No duplicate metric names in catalogue", len(metric_names) == len(set(metric_names)))
    check("No reserved keys used in catalogue", not any(m in RESERVED_KEYS for m in metric_names))

    # 2. Units completeness
    missing_units = [m["name"] for m in METRICS if m.get("type", int) != str and m["name"] not in UNITS_DEF]
    check("Every numeric catalogue metric has an entry in units{}", len(missing_units) == 0, f"missing: {missing_units}")
    missing_table_units = [tbl for tbl in TABLE_UNITS if tbl not in UNITS_DEF]
    check("Every child table has a schema entry in units{}", len(missing_table_units) == 0, f"missing: {missing_table_units}")

    # 3. Payload validation
    payload = get_empty_payload()
    violations = validate_output(payload)
    check("Empty payload passes validate_output() with 0 violations", len(violations) == 0, f"violations: {violations}")

    # 4. Failure detection in validate_output
    bad_payload = copy.deepcopy(payload)
    target_tabs = bad_payload["tabs"].get("tabs", bad_payload["tabs"])
    target_tabs["Primary"]["tablist"].append("Ghost_Metric")
    bad_violations = validate_output(bad_payload)
    check("validate_output catches TAB_METRIC_NEVER_EMITTED", any("Ghost_Metric" in v for v in bad_violations))

    print("=================================================================", flush=True)
    if fails == 0:
        print("RESULT: ALL SKELETON TESTS PASSED", flush=True)
        return 0
    else:
        print(f"RESULT: {fails} TEST(S) FAILED", flush=True)
        return 1


def lsn_to_bytes(lsn_val: Any) -> int:
    """Parses PostgreSQL Log Sequence Number (e.g. '0/3000000') to integer bytes."""
    if isinstance(lsn_val, (int, float)):
        return int(lsn_val)
    if isinstance(lsn_val, str) and "/" in lsn_val:
        parts = lsn_val.strip().split("/", 1)
        try:
            return (int(parts[0], 16) << 32) + int(parts[1], 16)
        except ValueError:
            return 0
    return 0


PATRONI_KNOWN_ROLES = {
    "leader", "standby_leader", "replica", "sync_standby",
    "async_standby", "uninitialized", "master"
}
PATRONI_KNOWN_STATES = {
    "running", "stopped", "starting", "stop failed", "crashed",
    "paused", "creating replica", "start failed", "restart failed",
    "custom", "init failed", "in flux", "demoted", "promoted", "unknown"
}


def fetch_patroni_cluster(host: str, port: int, timeout: float = 1.0) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Fetches cluster topology from Patroni REST API /cluster endpoint.
    Returns (status, data) where status is one of: 'positive', 'negative', 'error', 'not_applicable'.
    """
    if not host or not port:
        return "not_applicable", None
    url = f"http://{normalize_host(host)}:{port}/cluster"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "site24x7_pgcluster"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict) and "members" in data:
                    members = data.get("members", [])
                    # Must contain a member object with name, role AND state matching known sets
                    valid_members = [
                        m for m in members
                        if isinstance(m, dict) and "name" in m
                        and str(m.get("role", "")).lower() in PATRONI_KNOWN_ROLES
                        and str(m.get("state", "")).lower() in PATRONI_KNOWN_STATES
                    ]
                    if valid_members:
                        return "positive", data
                return "negative", None
            return "negative", None
    except urllib.error.HTTPError:
        return "negative", None
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, (ConnectionRefusedError, socket.gaierror)) or "refused" in str(reason).lower():
            return "negative", None
        return "error", None
    except Exception:
        return "error", None


def probe_cluster_managers(primary_client: Optional[NodeClient], patroni_probe_status: str) -> Tuple[int, str, Dict[str, str]]:
    """
    Evaluates evidence for Patroni, repmgr, Citus, CNPG, Stolon, pg_auto_failover, native, and unknown.
    Returns (manager_int, manager_str, probe_outcomes_dict).
    """
    probes: Dict[str, str] = {
        "patroni": patroni_probe_status,
        "repmgr": "negative",
        "citus": "negative",
        "pg_auto_failover": "negative",
        "cnpg": "negative",
        "stolon": "not_applicable"
    }

    if patroni_probe_status == "positive":
        return TOPOLOGY_PATRONI, "patroni", probes

    if not primary_client or not getattr(primary_client, "is_connected", False):
        return TOPOLOGY_UNKNOWN, "unknown", probes

    # 1. repmgr probe
    repmgr_row = primary_client.query_one("SELECT count(*) FROM pg_extension WHERE extname = 'repmgr';")
    if primary_client.last_error_class is not None:
        probes["repmgr"] = "error"
    elif repmgr_row and safe_int(repmgr_row[0]) > 0:
        probes["repmgr"] = "positive"
        return TOPOLOGY_REPMGR, "repmgr", probes
    else:
        probes["repmgr"] = "negative"

    # 2. Citus probe
    citus_row = primary_client.query_one("SELECT count(*) FROM pg_extension WHERE extname = 'citus';")
    if primary_client.last_error_class is not None:
        probes["citus"] = "error"
    elif citus_row and safe_int(citus_row[0]) > 0:
        probes["citus"] = "positive"
        return TOPOLOGY_CITUS, "citus", probes
    else:
        probes["citus"] = "negative"

    # 3. pg_auto_failover probe
    pgaf_row = primary_client.query_one("SELECT count(*) FROM pg_extension WHERE extname = 'pgautofailover';")
    if primary_client.last_error_class is not None:
        probes["pg_auto_failover"] = "error"
    elif pgaf_row and safe_int(pgaf_row[0]) > 0:
        probes["pg_auto_failover"] = "positive"
        return TOPOLOGY_UNKNOWN, "pg_auto_failover", probes
    else:
        probes["pg_auto_failover"] = "negative"

    # 4. CloudNativePG probe (env / local settings)
    if "CNPG_CLUSTER_NAME" in os.environ or "POD_NAME" in os.environ:
        probes["cnpg"] = "positive"
        return TOPOLOGY_CNPG, "cnpg", probes
    else:
        probes["cnpg"] = "negative"

    # 5. Native streaming replication evidence
    has_streaming_evidence = False
    rep_row = primary_client.query_one("SELECT count(*) FROM pg_stat_replication WHERE state = 'streaming';")
    if rep_row and safe_int(rep_row[0]) > 0:
        has_streaming_evidence = True
    else:
        wal_rec = primary_client.query_one("SELECT count(*) FROM pg_stat_wal_receiver WHERE status = 'streaming';")
        if wal_rec and safe_int(wal_rec[0]) > 0:
            has_streaming_evidence = True
        elif primary_client.is_recovery:
            p_ci = primary_client.query_one("SHOW primary_conninfo;")
            if p_ci and p_ci[0]:
                has_streaming_evidence = True

    # If ANY applicable probe resulted in an error (e.g. timed out probe):
    has_error = any(v == "error" for v in probes.values())
    if has_error:
        return TOPOLOGY_UNKNOWN, "unknown", probes

    if has_streaming_evidence:
        return TOPOLOGY_NATIVE, "native", probes

    return TOPOLOGY_UNKNOWN, "unknown", probes


def fetch_patroni_history(host: str, port: int, timeout: float = 1.0) -> List[List[Any]]:
    """Fetches failover history from Patroni REST API /history endpoint."""
    url = f"http://{normalize_host(host)}:{port}/history"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "site24x7_pgcluster"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []


def collect_official_compat(client: Optional[NodeClient]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Collects backward-compatibility metrics matching official postgres plugin (Fix 9).
    Emits 41 parent metrics, Stats_per_DB, and Transactions_Per_Database.
    """
    metrics: Dict[str, Any] = {}
    db_stats_rows: List[Dict[str, Any]] = []
    txn_session_rows: List[Dict[str, Any]] = []

    defaults: Dict[str, Any] = {
        "Table Count": 0,
        "Active Queries": 0,
        "Active Waiting Queries": 0,
        "Transactions Open": 0,
        "Idle Transactions": 0,
        "Locks Count": 0,
        "Max Connections": 0,
        "Active Connections": 0,
        "Total Commits": 0,
        "Total Rollbacks": 0,
        "Total Conflicts": 0,
        "Total Rows Inserted": 0,
        "Total Rows Updated": 0,
        "Total Rows Deleted": 0,
        "Total Rows Fetched": 0,
        "Total Rows Returned": 0,
        "Total Block Reads": 0,
        "Total Block Hits": 0,
        "Checkpoints Timed": 0,
        "Checkpoints Req": 0,
        "Checkpoint Write Time": 0.0,
        "Checkpoint Sync Time": 0.0,
        "Buffers Checkpoint": 0,
        "Buffers Clean": 0,
        "Maxwritten Clean": 0,
        "Buffers Backend": 0,
        "Buffers Backend Fsync": 0,
        "Buffers Alloc": 0,
        "Index Scans": 0,
        "Index Rows Read": 0,
        "Index Rows Fetched": 0,
        "Server Version": "unknown",
        "Uptime": 0,
        "Database Count": 0,
        "Heap Blocks Read": 0,
        "Heap Blocks Hit": 0,
        "Cache Hit Ratio": 0.0,
    }
    if client and client.version_tuple and client.version_tuple >= (14, 0):
        defaults.update({
            "Total Sessions": 0,
            "Total Sessions Abandoned": 0,
            "Total Sessions Fatal": 0,
            "Total Sessions Killed": 0,
        })
    metrics.update(defaults)

    if not client or not getattr(client, "is_connected", False) or not client.conn:
        return metrics, db_stats_rows, txn_session_rows

    major_version = client.version_tuple[0] if client.version_tuple else 0
    middle_version = client.version_tuple[1] if client.version_tuple else 0

    waiting = True
    str_tableStat = "SELECT COUNT(*) AS table_count FROM pg_stat_all_tables;"
    str_TransactionsOpen = "SELECT count(*) as transactions_open FROM pg_stat_activity WHERE xact_start IS NOT NULL;"
    str_version = "SHOW server_version;"

    if (major_version >= 10) or (major_version >= 9 and middle_version >= 2):
        str_usageActiveStat = "SELECT count(*) - ( SELECT count(*) FROM pg_stat_activity WHERE state = 'idle' ) as active_queries FROM pg_stat_activity;"
        str_usageWaitingStat = "SELECT count(*) as active_waiting_queries FROM pg_stat_activity WHERE state = 'active' AND wait_event IS NOT NULL;"
        str_TransactionsIdle = "SELECT COUNT(*) as idle_transactions FROM pg_stat_activity WHERE state = 'idle in transaction';"
    else:
        str_usageActiveStat = "SELECT count(*) - ( SELECT count(*) FROM pg_stat_activity WHERE current_query = '<IDLE>' ) as active_queries FROM pg_stat_activity;"
        str_TransactionsIdle = "SELECT COUNT(*) as idle_transactions FROM pg_stat_activity WHERE state = '<IDLE> in transaction';"
        waiting = False

    str_lockStat = "SELECT COUNT(*) as locks_count FROM pg_locks;"
    str_MaxConn = "select setting::int max_connections from pg_settings where name='max_connections';"
    str_dbStats = "SELECT sum(numbackends) as active_connections, sum(xact_commit) as total_commits, sum(xact_rollback) as total_rollbacks, sum(conflicts) as total_conflicts FROM pg_stat_database;"
    str_iostats = "SELECT sum(tup_inserted) as total_rows_inserted, sum(tup_updated) as total_rows_updated, sum(tup_deleted) as total_rows_deleted, sum(tup_fetched) as total_rows_fetched, sum(tup_returned) as total_rows_returned, sum(blks_read) as total_block_reads, sum(blks_hit) as total_block_hits FROM pg_stat_database;"

    if major_version >= 17:
        str_bgStats = "SELECT c.num_timed AS checkpoints_timed, c.num_requested AS checkpoints_req, c.write_time AS checkpoint_write_time, c.sync_time AS checkpoint_sync_time, c.buffers_written AS buffers_checkpoint, b.buffers_clean, b.maxwritten_clean, b.buffers_alloc FROM pg_stat_checkpointer c, pg_stat_bgwriter b;"
    else:
        str_bgStats = "SELECT checkpoints_timed,checkpoints_req,checkpoint_write_time,checkpoint_sync_time,buffers_checkpoint,buffers_clean,maxwritten_clean,buffers_backend,buffers_backend_fsync,buffers_alloc FROM pg_stat_bgwriter;"

    str_idxStats = "SELECT sum(idx_scan) as index_scans, sum(idx_tup_read) as index_rows_read, sum(idx_tup_fetch) as index_rows_fetched FROM pg_stat_user_indexes;"
    str_uptime = "SELECT FLOOR(EXTRACT(EPOCH FROM current_timestamp - pg_postmaster_start_time())) as uptime;"
    str_databaseCount = "SELECT COUNT(*) AS database_count FROM pg_database WHERE datname <> 'template0' AND datname <> 'template1';"
    str_Sessions = "SELECT SUM(sessions) as total_sessions, SUM(sessions_abandoned) as total_sessions_abandoned, SUM(sessions_fatal) as total_sessions_fatal, SUM(sessions_killed) as total_sessions_killed FROM pg_stat_database;"
    str_heap = "SELECT sum(heap_blks_read) as heap_blocks_read, sum(heap_blks_hit) as heap_blocks_hit, CASE WHEN (sum(heap_blks_hit) + sum(heap_blks_read)) = 0 THEN 0 ELSE sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) END as cache_hit_ratio FROM pg_statio_user_tables;"

    dict_queries: Dict[str, str] = {
        "table_count": str_tableStat,
        "active_queries": str_usageActiveStat,
        "transactions_open": str_TransactionsOpen,
        "transacttions_idle": str_TransactionsIdle,
        "db_stats": str_dbStats,
        "bg_stats": str_bgStats,
        "locks_count": str_lockStat,
        "max_conn": str_MaxConn,
        "io_stats": str_iostats,
        "idx_stats": str_idxStats,
        "version": str_version,
        "uptime": str_uptime,
        "no of databases": str_databaseCount,
        "heap_and_cache": str_heap,
    }
    if waiting:
        dict_queries["active_waiting_queries"] = str_usageWaitingStat
    if major_version >= 14:
        dict_queries["session"] = str_Sessions

    for q_key, sql in dict_queries.items():
        try:
            cur = client.conn.cursor()
            cur.execute(sql)
            col_names = [desc[0] for desc in cur.description]
            row = cur.fetchone()
            cur.close()
            if row:
                for idx, col in enumerate(col_names):
                    m_name = col.replace("_", " ").title()
                    val = row[idx]
                    if val is None:
                        val = 0
                    if m_name == "Server Version":
                        metrics[m_name] = str(val)[:MAX_STRING_CHARS]
                    elif isinstance(val, (int, float)):
                        metrics[m_name] = float(val) if isinstance(val, float) or "." in str(val) else int(val)
                    else:
                        try:
                            f_val = float(val)
                            metrics[m_name] = f_val if "." in str(val) else int(f_val)
                        except (ValueError, TypeError):
                            metrics[m_name] = str(val)[:MAX_STRING_CHARS]
        except Exception:
            if client.conn:
                try:
                    client.conn.rollback()
                except Exception:
                    pass

    # Compatibility Child Tables
    # 1. Transactions_Per_Database
    if major_version >= 14:
        conn_sql = "SELECT datname as name, xact_commit as commits, xact_rollback as rollbacks, conflicts, sessions, sessions_abandoned, sessions_fatal, sessions_killed, session_time, active_time as sessions_active_time, idle_in_transaction_time as idle_in_txn_time FROM pg_stat_database WHERE datname IS NOT NULL;"
    else:
        conn_sql = "SELECT datname as name, xact_commit as commits, xact_rollback as rollbacks, conflicts FROM pg_stat_database WHERE datname IS NOT NULL;"

    try:
        cur = client.conn.cursor()
        cur.execute(conn_sql)
        col_names = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        cur.close()
        for r in rows[:MAX_ROWS]:
            row_dict: Dict[str, Any] = {}
            for i, c in enumerate(col_names):
                val = r[i]
                if c == "name":
                    row_dict[c] = safe_name(val or "db")
                else:
                    if val is None:
                        val = 0
                    row_dict[c] = float(val) if isinstance(val, float) or (isinstance(val, (int, float, str)) and "." in str(val)) else int(val)
            txn_session_rows.append(row_dict)
    except Exception:
        if client.conn:
            try:
                client.conn.rollback()
            except Exception:
                pass

    # 2. Stats_per_DB
    db_sql = "SELECT d.datname AS name, s.numbackends as active_connections, ROUND(pg_database_size(d.datname) / 1024 / 1024, 2) AS size_in_mb, tup_inserted as rows_inserted, tup_updated as rows_updated, tup_deleted as rows_deleted, tup_fetched as rows_fetched, tup_returned as rows_returned, blks_read as block_reads, blks_hit as block_hits FROM pg_database d JOIN pg_stat_database s ON d.oid = s.datid WHERE d.datname IS NOT NULL;"
    try:
        cur = client.conn.cursor()
        cur.execute(db_sql)
        col_names = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        cur.close()
        for r in rows[:MAX_ROWS]:
            row_dict = {}
            for i, c in enumerate(col_names):
                val = r[i]
                if c == "name":
                    row_dict[c] = safe_name(val or "db")
                else:
                    if val is None:
                        val = 0
                    row_dict[c] = float(val) if isinstance(val, float) or (isinstance(val, (int, float, str)) and "." in str(val)) else int(val)
            db_stats_rows.append(row_dict)
    except Exception:
        if client.conn:
            try:
                client.conn.rollback()
            except Exception:
                pass

    return metrics, db_stats_rows, txn_session_rows


def parse_node_specs(raw_nodes: str, default_port: int = 5432) -> List[Tuple[str, str, int]]:
    """
    Parses comma-separated node specifications into (name, host, port) tuples.
    Formats supported:
    - 'pg1=127.0.0.1:5401,pg2=127.0.0.1:5402'
    - '127.0.0.1:5432,127.0.0.1:5433'
    - 'localhost'
    """
    specs: List[Tuple[str, str, int]] = []
    if not raw_nodes:
        return specs
    for item in raw_nodes.split(","):
        item = item.strip()
        if not item:
            continue
        name = ""
        host_port = item
        if "=" in item:
            name, host_port = item.split("=", 1)
            name = name.strip()
            host_port = host_port.strip()
        
        # Parse host and port
        if ":" in host_port:
            h, p_str = host_port.rsplit(":", 1)
            try:
                p = int(p_str)
            except ValueError:
                p = default_port
                h = host_port
        else:
            h = host_port
            p = default_port
        
        if not name:
            name = f"{normalize_host(h)}:{p}"
        specs.append((name, normalize_host(h), p))
    return specs


# -----------------------------------------------------------------------------
# 11. STATE STORE (Inlined atomic, keyed, self-describing state)
# -----------------------------------------------------------------------------
STATE_SCHEMA = 1
MAX_STATE_BYTES = 64 * 1024
NODE_TTL_DAYS = 7
DEFAULT_STATE_FILENAME = "postgres_cluster_state.json"


def _machine_id() -> str:
    """Stable per-machine identifier, best effort, never raises."""
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                val = f.read().strip()
            if val:
                return val[:64]
        except OSError:
            continue
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
            ) as key:
                val, _ = winreg.QueryValueEx(key, "MachineGuid")
                if val:
                    return str(val)[:64]
        except Exception:
            pass
    try:
        return "host-" + socket.gethostname()[:48]
    except Exception:
        return "host-unknown"


def _safe_token(raw: str, limit: int = 24) -> str:
    """Filesystem-safe, collision-resistant slug."""
    keep = "".join(c if (c.isalnum() or c in "-_") else "-" for c in str(raw or ""))
    keep = keep.strip("-")
    return (keep[:limit] or "cluster")


def writable_by_write_probe(directory: str) -> Tuple[bool, str]:
    """Tests writability using actual file creation instead of os.access()."""
    if not directory:
        return False, "no directory"
    if not os.path.isdir(directory):
        return False, "not a directory"
    import uuid
    probe = os.path.join(directory, f".pgcluster-probe.{uuid.uuid4().hex[:8]}")
    try:
        with open(probe, "wb") as f:
            f.write(b"ok")
            f.flush()
            os.fsync(f.fileno())
    except OSError as e:
        return False, str(e)
    finally:
        try:
            if os.path.exists(probe):
                os.remove(probe)
        except OSError:
            pass
    return True, "ok"


def ensure_dir(path: str) -> bool:
    """mkdir -p, True if directory exists afterwards."""
    try:
        os.makedirs(path, exist_ok=True)
        return os.path.isdir(path)
    except OSError:
        return False


class StateStore:
    """Atomic, keyed, self-describing JSON state for monitored cluster."""

    def __init__(
        self,
        plugin_file: str,
        cluster_id: str = "",
        name: str = "",
        seed: str = "",
        state_dir: Optional[str] = None,
        filename: str = DEFAULT_STATE_FILENAME,
        allow_temp_fallback: bool = True,
        warn=None,
    ):
        self.plugin_file = plugin_file
        self.plugin_dir = os.path.dirname(os.path.abspath(plugin_file))
        self.cluster_id = str(cluster_id or "")
        self.name = str(name or "")
        self.seed = str(seed or "")
        self.filename = filename
        self.explicit_dir = state_dir or ""
        self.allow_temp_fallback = allow_temp_fallback
        self._warn = warn or (lambda code, text: None)
        self._path: Optional[str] = None
        self._persistent: Optional[bool] = None
        self._reason: str = "not probed"
        self._machine = _machine_id()
        self._io_errors = 0
        self._last_written: Optional[float] = None

    def instance_key(self) -> str:
        """Namespaces the state file to avoid collision across clusters/folders."""
        identity = self.cluster_id or self.seed or self.name or "unnamed"
        seed = "|".join([self._machine, identity, self.plugin_dir])
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]

    def _candidates(self) -> List[Tuple[str, bool, str]]:
        cands: List[Tuple[str, bool, str]] = []
        if self.explicit_dir:
            cands.append((os.path.abspath(self.explicit_dir), True, "configured"))
        cands.append((self.plugin_dir, True, "plugin_dir"))
        if os.name == "nt":
            base = os.environ.get("PROGRAMDATA") or os.environ.get("ALLUSERSPROFILE")
            if base:
                cands.append((os.path.join(base, "Site24x7", "postgres_cluster"), True, "programdata"))
        else:
            cands.append(("/var/lib/site24x7/postgres_cluster", True, "var_lib"))
            xdg = os.environ.get("XDG_STATE_HOME") or (
                os.path.join(os.path.expanduser("~"), ".local", "state") if os.path.expanduser("~") not in ("~", "") else ""
            )
            if xdg:
                cands.append((os.path.join(xdg, "site24x7", "postgres_cluster"), True, "xdg_state"))
        if self.allow_temp_fallback:
            cands.append((os.path.join(tempfile.gettempdir(), "site24x7-postgres_cluster"), False, "tempdir"))
        return cands

    def probe(self, force: bool = False) -> "StateStore":
        if self._path and not force:
            return self
        self._path, self._persistent, self._reason = None, None, "no writable location"
        for directory, durable, label in self._candidates():
            if label != "configured" and not os.path.isdir(directory):
                if not ensure_dir(directory):
                    continue
            elif label == "configured" and not os.path.isdir(directory):
                if not ensure_dir(directory):
                    continue
            ok, why = writable_by_write_probe(directory)
            if not ok:
                continue
            target_dir = os.path.join(directory, f".pgcluster-{self.instance_key()}")
            if not ensure_dir(target_dir):
                continue
            ok2, _ = writable_by_write_probe(target_dir)
            if not ok2:
                continue
            self._path = os.path.join(target_dir, self.filename)
            self._persistent = durable
            self._reason = f"{label}: {target_dir}"
            return self
        return self

    @property
    def path(self) -> Optional[str]:
        if self._path is None:
            self.probe()
        return self._path

    def load(self) -> Dict[str, Any]:
        path = self.path
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read(MAX_STATE_BYTES * 2)
        except OSError:
            self._io_errors += 1
            return {}
        if len(raw) > MAX_STATE_BYTES:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            return {}
        if not isinstance(data, dict):
            return {}
        if data.get("schema") != STATE_SCHEMA:
            return {}
        if data.get("instance") != self.instance_key():
            return {}
        return data

    def save(self, state: Dict[str, Any]) -> bool:
        path = self.path
        if not path:
            return False
        state = dict(state or {})
        state["schema"] = STATE_SCHEMA
        state["instance"] = self.instance_key()
        state["machine_id"] = self._machine
        state["cluster_id"] = self.cluster_id
        state["name"] = self.name
        state["updated"] = int(time.time())
        state["nodes"] = self._prune_nodes(state.get("nodes") or {})

        tmp = None
        directory = os.path.dirname(path)
        try:
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".state.", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, separators=(",", ":"), default=str)
                f.flush()
                os.fsync(f.fileno())
            if os.name != "nt":
                try:
                    os.chmod(tmp, 0o600)
                except OSError:
                    pass
            os.replace(tmp, path)
            tmp = None
            self._last_written = time.time()
            return True
        except OSError:
            self._io_errors += 1
            return False
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    @staticmethod
    def _prune_nodes(nodes: Dict[str, Any]) -> Dict[str, Any]:
        cutoff = time.time() - NODE_TTL_DAYS * 86400
        out = {}
        for alias, entry in (nodes or {}).items():
            if not isinstance(entry, dict):
                continue
            seen = max(float(entry.get("ts_ok") or 0), float(entry.get("ts_fail") or 0))
            if seen and seen < cutoff:
                continue
            out[alias] = entry
        return out

    def diagnostics(self) -> Dict[str, Any]:
        age = None
        if self._last_written:
            age = int(time.time() - self._last_written)
        elif self._path and os.path.exists(self._path):
            try:
                age = int(time.time() - os.path.getmtime(self._path))
            except OSError:
                age = None
        return {
            "State_File": (self._path or "none")[-100:],
            "State_Persistent": 1 if self._persistent else 0,
            "State_Age_s": age if age is not None else -1,
            "State_IO_Errors": self._io_errors,
            "State_Reason": (self._reason or "")[:100],
        }


def read_cfg_file(cfg_path: str) -> Dict[str, Any]:
    """Parser for plugin .cfg file supporting standard and versioned section headers."""
    out: Dict[str, Any] = {}
    if not os.path.exists(cfg_path):
        return out
    current_section = ""
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith(";"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    current_section = line[1:-1].strip()
                    continue
                if current_section and current_section != "global_configurations" and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    out[k] = v
    except Exception:
        pass
    return out


def run(param: Dict[str, Any]) -> Dict[str, Any]:
    """Standard Site24x7 plugin entry point."""
    t0 = time.time()
    payload = get_empty_payload()

    if not HAVE_PSYCOPG2:
        payload["status"] = STATUS_DOWN
        payload["msg"] = (
            "psycopg2 Module Not Installed\n"
            "Dependency missing:'psycopg2' Python client library\n"
            "Install with command,\n\n"
            " pip3 install psycopg2-binary\n"
        )
        return payload

    # 1. Parameter resolution: CLI/argument param takes precedence over cfg file
    cfg_data = {}
    script_base = os.path.splitext(os.path.basename(__file__))[0]
    cfg_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{script_base}.cfg")
    if not os.path.exists(cfg_file):
        cfg_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "postgres_cluster.cfg")
    if os.path.exists(cfg_file):
        cfg_data = read_cfg_file(cfg_file)

    merged = dict(cfg_data)
    merged.update(param or {})

    username = merged.get("username", "site24x7")
    password = os.environ.get("PGPASSWORD") or merged.get("password", "")
    dbname = merged.get("db") or merged.get("dbname", "postgres")
    sslmode = merged.get("sslmode", "prefer")
    sslrootcert = merged.get("sslrootcert", "")
    sslcert = merged.get("sslcert", "")
    sslkey = merged.get("sslkey", "")

    # Monitoring mode resolution (auto | standalone | cluster)
    monitor_mode = str(merged.get("monitor_mode", MODE_AUTO)).strip().lower()
    if monitor_mode not in VALID_MONITOR_MODES:
        monitor_mode = MODE_AUTO

    # Node & Patroni resolution
    raw_nodes = merged.get("nodes", "")
    cluster_host = merged.get("cluster_host", "")
    cluster_name = merged.get("cluster_name", "")
    state_dir = merged.get("state_dir", "")
    port_default = int(merged.get("postgres_port") or 5432)
    patroni_port = int(merged.get("patroni_port") or 8008)
    address_map = parse_address_map(merged.get("address_map", ""))

    cluster_id = cluster_name or cluster_host or "postgres_cluster"
    compat_official = int(merged.get("compat_official", 1))
    compat_metrics: Dict[str, Any] = {}
    compat_db_stats: List[Dict[str, Any]] = []
    compat_txn_sessions: List[Dict[str, Any]] = []
    store = StateStore(
        plugin_file=__file__,
        cluster_id=cluster_id,
        name=cluster_name or "postgres_cluster",
        seed=cluster_host or "127.0.0.1",
        state_dir=state_dir
    )
    store.probe()
    prev_state = store.load()
    new_state: Dict[str, Any] = {"nodes": dict(prev_state.get("nodes") or {})}

    discovered_members: List[Dict[str, Any]] = []
    cluster_manager = 0  # 0=unknown, 1=Patroni, 2=repmgr, 3=Native
    patroni_data = None
    patroni_history = []

    # Attempt Patroni REST discovery first (skipped in standalone mode)
    seed_host = cluster_host or ("127.0.0.1" if not raw_nodes else "")
    patroni_probe_status = "not_applicable"
    if seed_host and monitor_mode != MODE_STANDALONE:
        # Check seed with address map if mapped
        mapped_seed = address_map.get(f"{seed_host}:{patroni_port}") or address_map.get(seed_host)
        actual_patroni_host = seed_host
        actual_patroni_port = patroni_port
        if mapped_seed and ":" in mapped_seed:
            actual_patroni_host, p_str = mapped_seed.rsplit(":", 1)
            actual_patroni_port = int(p_str)

        patroni_probe_status, patroni_data = fetch_patroni_cluster(actual_patroni_host, actual_patroni_port, timeout=1.0)
        if patroni_probe_status == "positive" and patroni_data and "members" in patroni_data:
            cluster_manager = TOPOLOGY_PATRONI
            payload["Topology_Type"] = TOPOLOGY_PATRONI
            discovered_members = patroni_data.get("members", [])
            patroni_history = fetch_patroni_history(actual_patroni_host, actual_patroni_port, timeout=1.0)

    node_specs: List[Dict[str, Any]] = []

    if discovered_members:
        for m in discovered_members:
            m_name = m.get("name", "")
            m_host = m.get("host", "")
            m_port = int(m.get("port") or 5432)
            m_role_str = str(m.get("role", "replica")).lower()
            m_state_str = str(m.get("state", "unknown")).lower()
            m_tl = int(m.get("timeline") or 0)
            m_lag = int(m.get("lag") or 0)

            # Apply address mapping if necessary
            target_key = f"{m_host}:{m_port}"
            mapped_target = address_map.get(target_key) or address_map.get(m_host)
            conn_host = m_host
            conn_port = m_port
            if mapped_target:
                if ":" in mapped_target:
                    conn_host, p_str = mapped_target.rsplit(":", 1)
                    conn_port = int(p_str)
                else:
                    conn_host = mapped_target

            node_specs.append({
                "name": m_name or target_key,
                "host": conn_host,
                "port": conn_port,
                "patroni_role": m_role_str,
                "patroni_state": PATRONI_STATE_MAP.get(m_state_str, PATRONI_STATE_UNKNOWN),
                "patroni_tl": m_tl,
                "patroni_lag": m_lag
            })
    elif raw_nodes:
        for name, host, port in parse_node_specs(raw_nodes, default_port=port_default):
            node_specs.append({
                "name": name,
                "host": host,
                "port": port,
                "patroni_role": "unknown",
                "patroni_state": PATRONI_STATE_NA,
                "patroni_tl": 0,
                "patroni_lag": 0
            })
    elif cluster_host:
        node_specs.append({
            "name": f"{cluster_host}:{port_default}",
            "host": cluster_host,
            "port": port_default,
            "patroni_role": "unknown",
            "patroni_state": PATRONI_STATE_NA,
            "patroni_tl": 0,
            "patroni_lag": 0
        })
    else:
        node_specs.append({
            "name": f"localhost:{port_default}",
            "host": "127.0.0.1",
            "port": port_default,
            "patroni_role": "unknown",
            "patroni_state": PATRONI_STATE_NA,
            "patroni_tl": 0,
            "patroni_lag": 0
        })

    # 2. Parallel / Multi-node probing
    node_rows: List[Dict[str, Any]] = []
    primary_client: Optional[NodeClient] = None
    standby_client: Optional[NodeClient] = None
    all_warnings: List[str] = []
    queries_count = 0
    slot_rows: Optional[List[Tuple]] = []
    rep_rows: Optional[List[Tuple]] = []

    timelines: List[int] = []
    standby_lags_s: List[float] = []
    standby_lags_b: List[int] = []
    conn_pcts: List[Tuple[float, str]] = []
    response_times: List[Tuple[float, str]] = []

    def probe_single_node(spec: Dict[str, Any]) -> Dict[str, Any]:
        n_name = spec["name"]
        n_host = spec["host"]
        n_port = spec["port"]
        p_role_str = spec["patroni_role"]
        p_state_int = spec["patroni_state"]

        row_res = {
            "name": safe_name(n_name),
            "role": ROLE_UNKNOWN,
            "status": STATUS_DOWN,
            "status_reason": "connection failed",
            "last_seen_s": 0,
            "last_seen_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "timeline": spec.get("patroni_tl", 0),
            "replay_lag_s": 0.0,
            "replay_lag_bytes": 0,
            "conn_pct": 0.0,
            "resp_ms": 0.0,
            "sync": None,
            "patroni_state": p_state_int,
            "xact_age_s": 0,
            "uptime_s": 0,
            "version_num": 0,
            "active_queries": 0,
            "idle_in_txn": 0,
            "longest_query_s": 0,
            "temp_bytes": 0,
            "dead_tuples": 0,
            "client": None,
            "is_primary": False
        }

        t_start = time.time()
        client = NodeClient(
            name=n_name,
            host=n_host,
            port=n_port,
            user=username,
            password=password,
            dbname=dbname,
            sslmode=sslmode,
            sslrootcert=sslrootcert,
            sslcert=sslcert,
            sslkey=sslkey
        )

        if client.connect():
            if not client.is_supported:
                row_res["status"] = STATUS_DOWN
                row_res["status_reason"] = f"unsupported_version: PostgreSQL {client.version_tuple[0]}.{client.version_tuple[1]} < 9.6"
                row_res["version_num"] = safe_int(client.version_num)
                row_res["client_warnings"] = list(client.warnings)
                row_res["client"] = client
                return row_res

            resp_ms = round((time.time() - t_start) * 1000.0, 2)
            row_res["status"] = STATUS_UP
            row_res["status_reason"] = "healthy"
            row_res["resp_ms"] = resp_ms
            row_res["client"] = client

            is_prim = (not client.is_recovery) or (p_role_str == "leader")
            row_res["is_primary"] = is_prim
            row_res["role"] = ROLE_PRIMARY if is_prim else ROLE_STANDBY

            # Probe connections and activity (Client backends only on PG10+)
            if client.version_tuple >= (10, 0):
                c_sql = "SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend';"
            else:
                c_sql = "SELECT count(*) FROM pg_stat_activity;"
            c_row = client.query_one(c_sql)
            if c_row and c_row[0] is not None:
                conns = safe_int(c_row[0])
                max_conn = safe_int(client.settings.get("max_connections", 100), default=100)
                c_pct = round(100.0 * conns / max_conn, 2) if max_conn > 0 else 0.0
                row_res["conn_pct"] = c_pct

            # Timeline
            if row_res["timeline"] == 0:
                tl_row = client.query_one("SELECT timeline_id FROM pg_control_checkpoint();")
                if tl_row and tl_row[0]:
                    row_res["timeline"] = safe_int(tl_row[0])

            # Standby specific lag
            if not is_prim:
                lag_row = client.query_one("SELECT extract(epoch from (now() - pg_last_xact_replay_timestamp()));")
                if lag_row and lag_row[0] is not None:
                    row_res["replay_lag_s"] = round(safe_float(lag_row[0]), 2)

                b_row = client.query_one("SELECT pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn());")
                if b_row and b_row[0] is not None:
                    row_res["replay_lag_bytes"] = safe_int(b_row[0])

                # Check if delayed replica
                delay_row = client.query_one("SHOW recovery_min_apply_delay;")
                if delay_row and delay_row[0] and delay_row[0] != "0":
                    row_res["role"] = ROLE_DELAYED

                # Check if cascading replica (standby with downstream streaming replicas)
                casc_row = client.query_one("SELECT count(*) FROM pg_stat_replication WHERE state = 'streaming';")
                if casc_row and safe_int(casc_row[0]) > 0:
                    row_res["role"] = ROLE_CASCADING

            # Per-node snapshot details
            row_res["version_num"] = safe_int(client.version_num)
            up_row = client.query_one("SELECT extract(epoch from (now() - pg_postmaster_start_time()))::int;")
            if up_row and up_row[0] is not None:
                row_res["uptime_s"] = safe_int(up_row[0])
            act_q = client.query_one("SELECT count(*) FROM pg_stat_activity WHERE state = 'active';")
            if act_q and act_q[0] is not None:
                row_res["active_queries"] = safe_int(act_q[0])
            idle_q = client.query_one("SELECT count(*) FROM pg_stat_activity WHERE state LIKE 'idle in transaction%';")
            if idle_q and idle_q[0] is not None:
                row_res["idle_in_txn"] = safe_int(idle_q[0])
            lq = client.query_one("SELECT coalesce(max(extract(epoch from (now() - query_start)))::int, 0) FROM pg_stat_activity WHERE state = 'active';")
            if lq and lq[0] is not None:
                row_res["longest_query_s"] = safe_int(lq[0])
        else:
            row_res["status_reason"] = client.warnings[-1][:100] if client.warnings else "unreachable"
            row_res["auth_failed"] = getattr(client, "auth_failed", False)
            row_res["auth_error"] = getattr(client, "auth_error", "")
            row_res["client_warnings"] = list(client.warnings)

        return row_res

    # Fan out probes with DaemonThreadPoolExecutor bounded by cycle_deadline
    cycle_deadline = float(merged.get("cycle_deadline") or 40.0)
    workers_count = min(16, max(len(node_specs), 1))
    executor = DaemonThreadPoolExecutor(max_workers=workers_count)
    future_map = {executor.submit(probe_single_node, spec): spec for spec in node_specs}

    time_spent = time.time() - t0
    remaining_probe_time = max(1.0, cycle_deadline - time_spent - 5.0)

    done, not_done = concurrent.futures.wait(future_map.keys(), timeout=remaining_probe_time)

    for future in done:
        try:
            res = future.result()
            node_rows.append(res)
            if res.get("client_warnings"):
                all_warnings.extend(res["client_warnings"])
            if res["client"]:
                queries_count += 4
                if res["client"].warnings:
                    all_warnings.extend(res["client"].warnings)
                if res["is_primary"]:
                    if primary_client is None:
                        primary_client = res["client"]
                    else:
                        res["client"].close()
                else:
                    if standby_client is None:
                        standby_client = res["client"]
                    else:
                        res["client"].close()
        except Exception as e:
            all_warnings.append(f"Probe thread error: {e}")

    if not_done:
        payload["Budget_Exceeded"] = 1
        all_warnings.append(f"cycle_deadline exceeded: {len(not_done)} node probe(s) timed out")
        for future in not_done:
            spec = future_map[future]
            n_name = spec["name"]
            prev_node_data = new_state["nodes"].get(n_name, {})
            last_seen = prev_node_data.get("ts_ok", 0)
            node_rows.append({
                "name": safe_name(n_name),
                "role": ROLE_UNKNOWN,
                "status": STATUS_DOWN,
                "status_reason": "unreachable (deadline exceeded)",
                "last_seen_s": int(t0 - last_seen) if last_seen > 0 else -1,
                "last_seen_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last_seen)) if last_seen > 0 else "never",
                "timeline": prev_node_data.get("timeline", 0),
                "replay_lag_s": 0.0,
                "replay_lag_bytes": 0,
                "conn_pct": 0.0,
                "resp_ms": 0.0,
                "sync": 0,
                "patroni_state": PATRONI_STATE_UNKNOWN,
                "xact_age_s": 0,
                "client": None,
                "is_primary": False
            })

    executor.shutdown(wait=False, cancel_futures=True)

    # Determine effective mode (standalone vs cluster)
    effective_mode = monitor_mode
    if monitor_mode == MODE_AUTO:
        if len(node_specs) > 1:
            effective_mode = MODE_CLUSTER
        elif patroni_probe_status == "positive" and len(discovered_members) > 1:
            effective_mode = MODE_CLUSTER
        else:
            # Single configured/discovered node
            active_probe_client = primary_client or standby_client
            if active_probe_client and getattr(active_probe_client, "is_connected", False):
                mgr_code, mgr_str, probes = probe_cluster_managers(active_probe_client, patroni_probe_status)
                if mgr_code in (TOPOLOGY_PATRONI, TOPOLOGY_REPMGR, TOPOLOGY_CITUS, TOPOLOGY_CNPG, TOPOLOGY_STOLON, TOPOLOGY_NATIVE):
                    effective_mode = MODE_CLUSTER
                    cluster_manager = mgr_code
                    cluster_manager_str = mgr_str
                else:
                    rep_chk = active_probe_client.query_one("SELECT count(*) FROM pg_stat_replication WHERE state = 'streaming';")
                    wal_chk = active_probe_client.query_one("SELECT count(*) FROM pg_stat_wal_receiver WHERE status = 'streaming';")
                    if (rep_chk and safe_int(rep_chk[0]) > 0) or (wal_chk and safe_int(wal_chk[0]) > 0):
                        effective_mode = MODE_CLUSTER
                        cluster_manager = TOPOLOGY_NATIVE
                        cluster_manager_str = "native"
                    else:
                        effective_mode = MODE_STANDALONE
            else:
                effective_mode = MODE_STANDALONE

    # Select active_client for metrics collection
    active_client = primary_client if primary_client else (standby_client if effective_mode == MODE_STANDALONE else None)
    if standby_client and standby_client is not active_client:
        standby_client.close()
        standby_client = None

    # Update node state history & dead-node retention
    for r in node_rows:
        alias = r["name"]
        entry = new_state["nodes"].get(alias) or {}
        if r["status"] == STATUS_UP:
            entry["ts_ok"] = t0
            entry["last_role"] = r["role"]
            entry["timeline"] = r["timeline"]
        else:
            entry["ts_fail"] = t0
            entry["last_reason"] = r["status_reason"]
            if "ts_ok" in entry:
                r["last_seen_s"] = int(t0 - float(entry["ts_ok"]))
        new_state["nodes"][alias] = entry

    seen_aliases = {r["name"] for r in node_rows}
    if effective_mode != MODE_STANDALONE:
        for alias, entry in prev_state.get("nodes", {}).items():
            if alias not in seen_aliases:
                last_ok = float(entry.get("ts_ok") or 0.0)
                if (t0 - last_ok) <= NODE_TTL_DAYS * 86400:
                    offline_row = {
                        "name": safe_name(alias),
                        "role": ROLE_OFFLINE,
                        "status": STATUS_DOWN,
                        "status_reason": f"offline (down {int((t0 - last_ok)/60)}m)" if last_ok > 0 else "offline",
                        "last_seen_s": int(t0 - last_ok) if last_ok > 0 else -1,
                        "last_seen_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last_ok)) if last_ok > 0 else "unknown",
                        "timeline": int(entry.get("timeline") or 0),
                        "replay_lag_s": 0.0,
                        "replay_lag_bytes": 0,
                        "conn_pct": 0.0,
                        "resp_ms": 0.0,
                        "sync": SYNC_ASYNC,
                        "patroni_state": PATRONI_STATE_UNKNOWN,
                        "xact_age_s": 0,
                        "uptime_s": 0,
                        "version_num": 0,
                        "active_queries": 0,
                        "idle_in_txn": 0,
                        "longest_query_s": 0,
                        "temp_bytes": 0,
                        "dead_tuples": 0,
                        "client": None,
                        "is_primary": False
                    }
                    node_rows.append(offline_row)
                    new_state["nodes"][alias] = entry

    # Sort node rows deterministically: Primary first, then DOWN, then WARN, then name
    def sort_key(r):
        is_prim = 0 if r["role"] == ROLE_PRIMARY else 1
        is_down = 0 if r["status"] == STATUS_DOWN else 1
        return (is_prim, is_down, r["name"])

    node_rows.sort(key=sort_key)

    nodes_total = len(node_rows)
    nodes_up = len([r for r in node_rows if r["status"] == STATUS_UP])
    nodes_down = nodes_total - nodes_up

    payload["Nodes_Total"] = nodes_total
    payload["Nodes_Up"] = nodes_up
    payload["Nodes_Down"] = nodes_down

    # Roll-up metrics calculation
    for r in node_rows:
        if r["status"] == STATUS_UP:
            if r["timeline"] > 0:
                timelines.append(r["timeline"])
            response_times.append((r["resp_ms"], r["name"]))
            conn_pcts.append((r["conn_pct"], r["name"]))
            if r["role"] in (ROLE_STANDBY, ROLE_DELAYED, ROLE_CASCADING):
                standby_lags_s.append(r["replay_lag_s"])
                standby_lags_b.append(r["replay_lag_bytes"])

    if timelines:
        payload["Primary_Timeline"] = max(timelines)
        payload["Timeline_Spread"] = max(timelines) - min(timelines)

    if standby_lags_s:
        payload["Max_Replay_Lag_s"] = max(standby_lags_s)
    if standby_lags_b:
        payload["Max_Replay_Backlog"] = max(standby_lags_b)

    if response_times:
        response_times.sort(reverse=True)
        payload["Slowest_Resp_ms"] = response_times[0][0]
        payload["Slowest_Node"] = response_times[0][1]

    if conn_pcts:
        conn_pcts.sort(reverse=True)
        payload["Worst_Conn_Pct"] = conn_pcts[0][0]
        payload["Worst_Conn_Node"] = conn_pcts[0][1]

    # Process Patroni Failover History
    if patroni_history:
        # History format: [[entry_num, lsn, reason, iso_timestamp, new_leader], ...]
        try:
            latest_entry = patroni_history[-1]
            last_ts_str = latest_entry[3]
            last_promoted = latest_entry[4]
            payload["Last_Failover_To"] = str(last_promoted)

            # Parse ISO timestamp to calculate age
            clean_ts = last_ts_str.replace("Z", "+00:00")
            # If subseconds have too many digits, truncate
            if "+" in clean_ts:
                dt_part, tz_part = clean_ts.split("+", 1)
                if "." in dt_part:
                    base, frac = dt_part.split(".", 1)
                    clean_ts = f"{base}.{frac[:6]}+{tz_part}"
            elif "-" in clean_ts[10:]:
                dt_part, tz_part = clean_ts[:19], clean_ts[19:]
                clean_ts = f"{dt_part}+{tz_part}"

            # Calculate seconds elapsed
            t_struct = time.strptime(clean_ts[:19], "%Y-%m-%dT%H:%M:%S")
            failover_epoch = time.mktime(t_struct)
            f_age = max(0, int(time.time() - failover_epoch))
            payload["Failover_Age_s"] = f_age

            # Count failovers in last 24h
            now_epoch = time.time()
            f_count_24h = 0
            for entry in patroni_history:
                try:
                    e_ts = entry[3][:19]
                    e_epoch = time.mktime(time.strptime(e_ts, "%Y-%m-%dT%H:%M:%S"))
                    if now_epoch - e_epoch <= 86400:
                        f_count_24h += 1
                except Exception:
                    pass
            payload["Failover_Count_24h"] = f_count_24h
        except Exception:
            pass

    # 3. Primary / Standalone Metrics Collection (Tier 1)
    if active_client:
        if not active_client.is_supported:
            payload["Primary_Up"] = 0
            payload["status"] = STATUS_DOWN
            payload["msg"] = f"CRITICAL: unsupported_version ({active_client.name} PostgreSQL {active_client.version_tuple[0]}.{active_client.version_tuple[1]} < 9.6 floor)"
            if primary_client:
                primary_client.close()
            if standby_client:
                standby_client.close()
            return payload

        payload["Primary_Up"] = 1
        payload["Primary_Node"] = active_client.name
        payload["Primary_Data_Source"] = "live"
        payload["Cluster_Role"] = ROLE_PRIMARY if not active_client.is_recovery else ROLE_STANDBY

        # 3.1 pg_stat_database aggregation
        db_sql = """
            SELECT sum(numbackends), sum(xact_commit), sum(xact_rollback),
                   sum(tup_inserted), sum(tup_updated), sum(tup_deleted),
                   sum(tup_fetched), sum(tup_returned), sum(blks_read), sum(blks_hit),
                   max(age(datfrozenxid))
            FROM pg_stat_database;
        """
        row = active_client.query_one(db_sql)
        queries_count += 1
        commits, rollbacks, ins, upd, dels, blks_r, blks_h = 0, 0, 0, 0, 0, 0, 0
        if row:
            conns = safe_int(row[0])
            commits = safe_int(row[1])
            rollbacks = safe_int(row[2])
            ins = safe_int(row[3])
            upd = safe_int(row[4])
            dels = safe_int(row[5])
            blks_r = safe_int(row[8]) if len(row) > 8 else 0
            blks_h = safe_int(row[9]) if len(row) > 9 else 0
            max_xid_age = safe_int(row[10]) if len(row) > 10 else 0

            payload["Primary_Connections"] = conns
            payload["Active_Sessions"] = conns

            # Rate calculation from state deltas
            prev_ts = float(prev_state.get("primary_ts") or 0.0)
            prev_counters = prev_state.get("primary_counters") or {}
            dt = t0 - prev_ts
            if prev_counters and 0.5 <= dt <= 900.0:
                payload["Primary_Commits_s"] = round(max(0.0, commits - safe_float(prev_counters.get("commits", commits))) / dt, 2)
                payload["Primary_Rollbacks_s"] = round(max(0.0, rollbacks - safe_float(prev_counters.get("rollbacks", rollbacks))) / dt, 2)
                payload["Primary_Tup_Inserted_s"] = round(max(0.0, ins - safe_float(prev_counters.get("ins", ins))) / dt, 2)
                payload["Primary_Tup_Updated_s"] = round(max(0.0, upd - safe_float(prev_counters.get("upd", upd))) / dt, 2)
                payload["Primary_Tup_Deleted_s"] = round(max(0.0, dels - safe_float(prev_counters.get("dels", dels))) / dt, 2)
                payload["Primary_Blks_Read_s"] = round(max(0.0, blks_r - safe_float(prev_counters.get("blks_r", blks_r))) / dt, 2)
                payload["Blks_Read_s"] = payload["Primary_Blks_Read_s"]
                payload["Blks_Hit_s"] = round(max(0.0, blks_h - safe_float(prev_counters.get("blks_h", blks_h))) / dt, 2)
                payload["Rate_Warmup_Flag"] = 0
            else:
                payload["Primary_Commits_s"] = 0.0
                payload["Primary_Rollbacks_s"] = 0.0
                payload["Primary_Tup_Inserted_s"] = 0.0
                payload["Primary_Tup_Updated_s"] = 0.0
                payload["Primary_Tup_Deleted_s"] = 0.0
                payload["Primary_Blks_Read_s"] = 0.0
                payload["Blks_Read_s"] = 0.0
                payload["Blks_Hit_s"] = 0.0
                payload["Rate_Warmup_Flag"] = 1

            total_blks = blks_h + blks_r
            hit_ratio = round((100.0 * blks_h / total_blks), 2) if total_blks > 0 else 100.0
            payload["Primary_Cache_Hit_Ratio"] = hit_ratio
            payload["Cache_Hit_Ratio"] = hit_ratio

            payload["Primary_XID_Age"] = max_xid_age
            freeze_max = safe_int(active_client.settings.get("autovacuum_freeze_max_age", 200_000_000), default=200_000_000)
            if freeze_max > 0:
                wrap_pct = round(100.0 * max_xid_age / freeze_max, 2)
                payload["Primary_XID_Wrap_Pct"] = wrap_pct
                payload["XID_Wraparound_Pct"] = wrap_pct

        # 3.2 Max connections and connection percentage
        max_conn = safe_int(active_client.settings.get("max_connections", 100), default=100)
        payload["Primary_Max_Connections"] = max_conn
        if max_conn > 0 and "Primary_Connections" in payload:
            conn_pct = round(100.0 * payload["Primary_Connections"] / max_conn, 2)
            payload["Primary_Connection_Pct"] = conn_pct

        # 3.3 Active & Idle-in-transaction queries
        act_sql = """
            SELECT
                count(*) FILTER (WHERE state = 'active'),
                count(*) FILTER (WHERE state LIKE 'idle in transaction%'),
                count(*) FILTER (WHERE state = 'idle'),
                coalesce(max(extract(epoch from (now() - xact_start))), 0)
            FROM pg_stat_activity;
        """
        act_row = active_client.query_one(act_sql)
        queries_count += 1
        if act_row:
            payload["Primary_Active_Queries"] = safe_int(act_row[0])
            payload["Primary_Idle_In_Txn"] = safe_int(act_row[1]) if len(act_row) > 1 else 0
            payload["Idle_Sessions"] = safe_int(act_row[2]) if len(act_row) > 2 else 0
            payload["Primary_Longest_Txn_s"] = safe_int(act_row[3]) if len(act_row) > 3 else 0

        # 3.4 WAL Current Position & Directory (Replay LSN on standby, Current LSN on writable)
        if active_client.is_recovery:
            wal_sql = "SELECT pg_last_wal_replay_lsn();" if active_client.requires("pg_current_wal_lsn") else "SELECT pg_last_xlog_replay_location();"
        else:
            wal_sql = "SELECT pg_current_wal_lsn();" if active_client.requires("pg_current_wal_lsn") else "SELECT pg_current_xlog_location();"
        wal_row = active_client.query_one(wal_sql)
        queries_count += 1
        wal_bytes = 0
        if wal_row and wal_row[0]:
            wal_bytes = lsn_to_bytes(wal_row[0])
            wal_mb = round(wal_bytes / (1024 * 1024), 2)
            payload["Primary_WAL_LSN_MB"] = wal_mb
            payload["WAL_LSN_MB"] = wal_mb
            prev_counters = prev_state.get("primary_counters") or {}
            prev_ts = float(prev_state.get("primary_ts") or 0.0)
            dt = t0 - prev_ts
            if prev_counters and 0.5 <= dt <= 900.0:
                p_wal = prev_counters.get("wal_bytes", wal_bytes)
                payload["Primary_WAL_Rate_MBs"] = round(max(0.0, wal_bytes - p_wal) / (1024 * 1024 * dt), 2)
                payload["WAL_Rate_MBs"] = payload["Primary_WAL_Rate_MBs"]

        # 3.5 Uptime
        uptime_row = active_client.query_one("SELECT extract(epoch from (now() - pg_postmaster_start_time()));")
        queries_count += 1
        if uptime_row and uptime_row[0]:
            payload["Primary_Uptime_s"] = int(uptime_row[0])

        # 3.6 Replication Standbys & Slots
        if effective_mode == MODE_STANDALONE:
            payload["Standbys_Expected"] = 0
        else:
            payload["Standbys_Expected"] = max(len(node_specs) - 1, 0)

        rep_sql = """
            SELECT application_name, client_addr::text, state, sync_state,
                   pg_wal_lsn_diff(sent_lsn, write_lsn) as write_lag_b,
                   pg_wal_lsn_diff(sent_lsn, flush_lsn) as flush_lag_b,
                   pg_wal_lsn_diff(sent_lsn, replay_lsn) as replay_lag_b,
                   coalesce(extract(epoch from replay_lag)::float, 0.0) as replay_lag_s
            FROM pg_stat_replication;
        """ if active_client.version_tuple >= (10, 0) else "SELECT application_name, client_addr, state, sync_state FROM pg_stat_replication;"
        rep_rows = active_client.query_all(rep_sql)
        queries_count += 1
        if rep_rows is None:
            err_cls = active_client.last_error_class or "query_error"
            prune_omitted_metric(payload, "Standbys_Streaming")
            prune_omitted_metric(payload, "Sync_Standby_Count")
            all_warnings.append(f"metric_unavailable: Standbys_Streaming ({err_cls})")
            all_warnings.append(f"metric_unavailable: Sync_Standby_Count ({err_cls})")
        else:
            streaming_count = len([r for r in rep_rows if str(r[2] if len(r) > 2 else r[1]).lower() == "streaming"])
            sync_count = len([r for r in rep_rows if str(r[3] if len(r) > 3 else r[2]).lower() in ("sync", "quorum")])
            payload["Standbys_Streaming"] = streaming_count
            payload["Sync_Standby_Count"] = sync_count

        if active_client.version_tuple >= (10, 0):
            slot_sql = """
                SELECT slot_name, slot_type, active,
                       pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) / 1024.0 / 1024.0 as retained_mb,
                       wal_status
                FROM pg_replication_slots;
            """ if active_client.version_tuple >= (13, 0) else """
                SELECT slot_name, slot_type, active,
                       pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) / 1024.0 / 1024.0 as retained_mb,
                       'normal' as wal_status
                FROM pg_replication_slots;
            """
        else:
            slot_sql = "SELECT slot_name, slot_type, active, 0.0 as retained_mb, 'normal' as wal_status FROM pg_replication_slots;"

        slot_rows = active_client.query_all(slot_sql)
        queries_count += 1
        if slot_rows is None:
            err_cls = active_client.last_error_class or "query_error"
            prune_omitted_metric(payload, "Replication_Slots_Total")
            prune_omitted_metric(payload, "Replication_Slots_Active")
            prune_omitted_metric(payload, "Inactive_Slots_Count")
            prune_omitted_metric(payload, "Max_Slot_Retained_MB")
            prune_omitted_metric(payload, "Slot_Risk")
            all_warnings.append(f"metric_unavailable: Replication_Slots_Total ({err_cls})")
            all_warnings.append(f"metric_unavailable: Replication_Slots_Active ({err_cls})")
            all_warnings.append(f"metric_unavailable: Inactive_Slots_Count ({err_cls})")
        else:
            payload["Replication_Slots_Total"] = len(slot_rows)
            payload["Replication_Slots_Active"] = len([s for s in slot_rows if bool(s[2])])
            payload["Inactive_Slots_Count"] = len(slot_rows) - payload["Replication_Slots_Active"]
            retained_list = [safe_float(s[3]) for s in slot_rows if len(s) > 3 and s[3] is not None]
            payload["Max_Slot_Retained_MB"] = max(retained_list, default=0.0)
            slot_risk = 0
            for s in slot_rows:
                s_active = bool(s[2])
                s_ret = safe_float(s[3]) if len(s) > 3 else 0.0
                s_wal_st = str(s[4]).lower() if len(s) > 4 else "normal"
                if s_wal_st == "lost":
                    slot_risk = max(slot_risk, 3)
                elif s_wal_st == "unreserved" or s_ret > 10240.0:
                    slot_risk = max(slot_risk, 2)
                elif (not s_active) or s_ret > 1024.0:
                    slot_risk = max(slot_risk, 1)
            payload["Slot_Risk"] = slot_risk

        # 3.7 Archiver status
        if active_client.settings.get("archive_mode", "off") != "off":
            payload["Archive_Mode"] = active_client.settings.get("archive_mode")
            arch_row = active_client.query_one("""
                SELECT archived_count, failed_count, last_archived_wal,
                       coalesce(extract(epoch from (now() - last_archived_time))::int, 0) as lag_s
                FROM pg_stat_archiver;
            """)
            queries_count += 1
            if active_client.last_error_class is not None:
                err_cls = active_client.last_error_class
                prune_omitted_metric(payload, "Primary_Archive_Ok")
                prune_omitted_metric(payload, "Archive_Success")
                prune_omitted_metric(payload, "Primary_Archive_Failed")
                prune_omitted_metric(payload, "Archive_Failed")
                prune_omitted_metric(payload, "Primary_Archive_Lag_s")
                all_warnings.append(f"metric_unavailable: Archive_Success ({err_cls})")
            elif arch_row:
                payload["Primary_Archive_Ok"] = safe_int(arch_row[0])
                payload["Archive_Success"] = safe_int(arch_row[0])
                payload["Primary_Archive_Failed"] = safe_int(arch_row[1])
                payload["Archive_Failed"] = safe_int(arch_row[1])
                payload["Last_Archived_WAL"] = str(arch_row[2] or "none")[:MAX_STRING_CHARS]
                payload["Primary_Archive_Lag_s"] = safe_int(arch_row[3])

            if active_client.version_tuple >= (10, 0):
                ready_row = active_client.query_one("SELECT count(*) FROM pg_ls_archive_statusdir() WHERE name LIKE '%.ready';")
                queries_count += 1
                if ready_row and ready_row[0] is not None:
                    payload["Primary_Archive_Ready"] = safe_int(ready_row[0])
                    payload["Archive_Ready"] = safe_int(ready_row[0])
                else:
                    prune_omitted_metric(payload, "Primary_Archive_Ready")
                    prune_omitted_metric(payload, "Archive_Ready")
                    if active_client.last_error_class is not None:
                        all_warnings.append(f"metric_unavailable: Primary_Archive_Ready ({active_client.last_error_class})")
            else:
                prune_omitted_metric(payload, "Primary_Archive_Ready")
                prune_omitted_metric(payload, "Archive_Ready")
        else:
            payload["Archive_Mode"] = "off"
            prune_omitted_metric(payload, "Primary_Archive_Ok")
            prune_omitted_metric(payload, "Archive_Success")
            prune_omitted_metric(payload, "Primary_Archive_Failed")
            prune_omitted_metric(payload, "Archive_Failed")
            prune_omitted_metric(payload, "Primary_Archive_Ready")
            prune_omitted_metric(payload, "Archive_Ready")
            prune_omitted_metric(payload, "Primary_Archive_Lag_s")

        # 3.8 Database sizes
        db_size_sql = "SELECT count(*), coalesce(sum(pg_database_size(oid)) / (1024*1024), 0) FROM pg_database WHERE datallowconn;"
        db_size_row = active_client.query_one(db_size_sql)
        queries_count += 1
        if active_client.last_error_class is not None:
            err_cls = active_client.last_error_class
            prune_omitted_metric(payload, "DB_Count")
            prune_omitted_metric(payload, "DB_Total_Size_MB")
            all_warnings.append(f"metric_unavailable: DB_Count ({err_cls})")
        elif db_size_row:
            payload["DB_Count"] = int(db_size_row[0] or 0)
            payload["DB_Total_Size_MB"] = round(float(db_size_row[1] or 0), 2) if len(db_size_row) > 1 else 0.0

        # 3.9 Additional Health and Activity Metrics (Finding 4)
        # Long running queries
        lq_sec = safe_int(merged.get("long_query_seconds", 300), default=300)
        lq_sql = f"""
            SELECT count(*) FROM pg_stat_activity
            WHERE state = 'active'
              AND (backend_type = 'client backend' OR backend_type IS NULL)
              AND (now() - query_start) > interval '{lq_sec} seconds';
        """
        lq_row = active_client.query_one(lq_sql)
        queries_count += 1
        if lq_row and lq_row[0] is not None:
            payload["Long_Running_Queries"] = safe_int(lq_row[0])
        elif active_client.last_error_class is not None:
            prune_omitted_metric(payload, "Long_Running_Queries")
            all_warnings.append(f"metric_unavailable: Long_Running_Queries ({active_client.last_error_class})")

        # Blocked sessions
        if active_client.version_tuple >= (9, 6):
            bs_sql = "SELECT count(*) FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid)) > 0;"
            bs_row = active_client.query_one(bs_sql)
            queries_count += 1
            if bs_row and bs_row[0] is not None:
                payload["Blocked_Sessions"] = safe_int(bs_row[0])
                payload["Primary_Blocked_Locks"] = safe_int(bs_row[0])
            elif active_client.last_error_class is not None:
                prune_omitted_metric(payload, "Blocked_Sessions")
                all_warnings.append(f"metric_unavailable: Blocked_Sessions ({active_client.last_error_class})")
        else:
            prune_omitted_metric(payload, "Blocked_Sessions")

        # Dead tuples total
        dt_sql = "SELECT coalesce(sum(n_dead_tup), 0) FROM pg_stat_user_tables;"
        dt_row = active_client.query_one(dt_sql)
        queries_count += 1
        if dt_row and dt_row[0] is not None:
            payload["Dead_Tuples_Total"] = safe_int(dt_row[0])
            payload["Primary_Dead_Tuples"] = safe_int(dt_row[0])
        elif active_client.last_error_class is not None:
            prune_omitted_metric(payload, "Dead_Tuples_Total")
            all_warnings.append(f"metric_unavailable: Dead_Tuples_Total ({active_client.last_error_class})")

        # Sessions killed (PG 14+)
        if active_client.version_tuple >= (14, 0):
            sk_row = active_client.query_one("SELECT coalesce(sum(sessions_killed), 0) FROM pg_stat_database;")
            queries_count += 1
            if sk_row and sk_row[0] is not None:
                payload["Primary_Sessions_Killed"] = safe_int(sk_row[0])
            elif active_client.last_error_class is not None:
                prune_omitted_metric(payload, "Primary_Sessions_Killed")
                all_warnings.append(f"metric_unavailable: Primary_Sessions_Killed ({active_client.last_error_class})")
        else:
            prune_omitted_metric(payload, "Primary_Sessions_Killed")

        # Logical replication & subscriptions
        has_sub = False
        if active_client.version_tuple >= (10, 0):
            sub_cnt = active_client.query_one("SELECT count(*) FROM pg_subscription;")
            queries_count += 1
            if sub_cnt and safe_int(sub_cnt[0]) > 0:
                has_sub = True

        if has_sub:
            payload["Logical_Replication_Used"] = 1
            if active_client.version_tuple >= (15, 0):
                sub_stats = active_client.query_one("SELECT coalesce(sum(apply_error_count), 0), coalesce(sum(sync_error_count), 0) FROM pg_stat_subscription_stats;")
                queries_count += 1
                if sub_stats:
                    payload["Subscription_Apply_Errors"] = safe_int(sub_stats[0])
                    payload["Subscription_Conflicts"] = safe_int(sub_stats[1])
                else:
                    prune_omitted_metric(payload, "Subscription_Apply_Errors")
                    prune_omitted_metric(payload, "Subscription_Conflicts")
            else:
                prune_omitted_metric(payload, "Subscription_Apply_Errors")
                prune_omitted_metric(payload, "Subscription_Conflicts")

            sub_lag = active_client.query_one("SELECT coalesce(max(extract(epoch from (now() - latest_end_time))), 0.0) FROM pg_stat_subscription WHERE latest_end_time IS NOT NULL;")
            queries_count += 1
            if sub_lag and sub_lag[0] is not None:
                payload["Max_Logical_Lag_s"] = round(safe_float(sub_lag[0]), 2)
            else:
                prune_omitted_metric(payload, "Max_Logical_Lag_s")
        else:
            payload["Logical_Replication_Used"] = 0
            prune_omitted_metric(payload, "Subscription_Apply_Errors")
            prune_omitted_metric(payload, "Subscription_Conflicts")
            prune_omitted_metric(payload, "Max_Logical_Lag_s")

        # Cascading and delayed standby counts
        payload["Cascading_Standby_Count"] = len([r for r in node_rows if r.get("role") == ROLE_CASCADING])
        payload["Delayed_Standby_Count"] = len([r for r in node_rows if r.get("role") == ROLE_DELAYED])
        s_exp = safe_int(payload.get("Standbys_Expected", 0))
        s_act = safe_int(payload.get("Standbys_Streaming", 0))
        payload["Standby_Disconnect_Flag"] = 1 if s_exp > s_act else 0

        # Multi-master & mesh metrics
        is_multi_master = bool(int(merged.get("is_multi_master") or 0)) or str(merged.get("topology_type", "")).lower() in ("multi_master", "4")
        if not is_multi_master:
            prune_omitted_metric(payload, "Mesh_Links_Declared")
            prune_omitted_metric(payload, "Mesh_Links_Active")
            prune_omitted_metric(payload, "Mesh_Disconnect_Flag")

        # Snapshot state for rate delta calculation and primary clamping
        new_state["primary_counters"] = {
            "commits": commits, "rollbacks": rollbacks,
            "ins": ins, "upd": upd, "dels": dels,
            "blks_r": blks_r, "blks_h": blks_h,
            "wal_bytes": wal_bytes
        }
        new_state["primary_metrics"] = {k: v for k, v in payload.items() if k.startswith("Primary_")}
        new_state["primary_ts"] = t0
        new_state["primary_name"] = active_client.name

        # Query standby wal_receiver if in recovery
        standby_wal_rec = None
        active_client_is_recovery = active_client.is_recovery
        active_client_version = active_client.version_tuple
        if active_client.is_recovery:
            standby_wal_rec = active_client.query_one("""
                SELECT sender_host, sender_port, status, slot_name,
                       coalesce(extract(epoch from (now() - pg_last_xact_replay_timestamp()))::float, 0.0) as replay_lag_s,
                       coalesce(pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn()), 0) as replay_lag_b
                FROM pg_stat_wal_receiver;
            """)
            queries_count += 1

        # Detect cluster manager before closing active connection
        if effective_mode == MODE_STANDALONE:
            cluster_manager = 0
            cluster_manager_str = "standalone"
        else:
            mgr_code, mgr_str, probe_res = probe_cluster_managers(active_client, patroni_probe_status)
            cluster_manager = mgr_code
            cluster_manager_str = mgr_str

        # Fix 9: Collect official postgres plugin backward compat metrics
        if compat_official == 1:
            compat_metrics, compat_db_stats, compat_txn_sessions = collect_official_compat(active_client)

        active_client.close()
        primary_client = None
        standby_client = None
    else:
        active_client_is_recovery = False
        active_client_version = (0, 0)
        standby_wal_rec = None
        if effective_mode == MODE_STANDALONE:
            cluster_manager = 0
            cluster_manager_str = "standalone"
        else:
            if not cluster_manager:
                mgr_code, mgr_str, probe_res = probe_cluster_managers(None, patroni_probe_status)
                cluster_manager = mgr_code
                cluster_manager_str = mgr_str

        # Fix 9: If primary is unreachable, collect from any connected local instance if available
        if compat_official == 1:
            local_client = None
            for r in node_rows:
                c = r.get("client")
                if c and getattr(c, "is_connected", False):
                    local_client = c
                    break
            compat_metrics, compat_db_stats, compat_txn_sessions = collect_official_compat(local_client)
        # Primary is down / unreachable: Apply Clamp if available within 900s
        prev_metrics = prev_state.get("primary_metrics") or {}
        prev_prim_ts = float(prev_state.get("primary_ts") or 0.0)
        if prev_metrics and (t0 - prev_prim_ts) <= 900.0:
            age_s = int(t0 - prev_prim_ts)
            for k, v in prev_metrics.items():
                if k.startswith("Primary_") and k in payload:
                    payload[k] = v
            payload["Primary_Up"] = 0
            payload["Primary_Data_Source"] = "clamped"
            payload["Primary_Data_Age_s"] = age_s
            payload["Primary_Data_Stale"] = 1 if age_s > 300 else 0
            payload["Primary_Commits_s"] = 0.0
            payload["Primary_Rollbacks_s"] = 0.0
            payload["Primary_Tup_Inserted_s"] = 0.0
            payload["Primary_Tup_Updated_s"] = 0.0
            payload["Primary_Tup_Deleted_s"] = 0.0
            payload["Primary_Blks_Read_s"] = 0.0
            payload["Primary_WAL_Rate_MBs"] = 0.0
            payload["Rate_Warmup_Flag"] = 1
            new_state["primary_metrics"] = prev_metrics
            new_state["primary_counters"] = prev_state.get("primary_counters", {})
            new_state["primary_ts"] = prev_prim_ts
            new_state["primary_name"] = prev_state.get("primary_name", "")
        else:
            payload["Primary_Up"] = 0
            payload["Primary_Data_Source"] = "none"
            payload["Primary_Data_Age_s"] = -1
            payload["Primary_Data_Stale"] = 1
            payload["Rate_Warmup_Flag"] = 1

    # Map sync state from rep_rows to node_rows (Finding 5)
    rep_link_data: List[Dict[str, Any]] = []
    if rep_rows:
        for r_item in rep_rows:
            app_n = str(r_item[0] or "")
            c_addr = str(r_item[1] or "") if len(r_item) > 1 and r_item[1] is not None else ""
            st = str(r_item[2] if len(r_item) > 2 else (r_item[1] if len(r_item) > 1 else "streaming"))
            sy_st = str(r_item[3] if len(r_item) > 3 else (r_item[2] if len(r_item) > 2 else "async"))
            w_lag = safe_int(r_item[4]) if len(r_item) > 4 else 0
            f_lag = safe_int(r_item[5]) if len(r_item) > 5 else 0
            r_lag_b = safe_int(r_item[6]) if len(r_item) > 6 else 0
            r_lag_s = safe_float(r_item[7]) if len(r_item) > 7 else 0.0

            clean_ip = c_addr.split('/')[0] if c_addr else ""
            rep_link_data.append({
                "app_name": app_n,
                "client_addr": clean_ip,
                "state": st,
                "sync_state": sy_st,
                "write_lag_b": w_lag,
                "flush_lag_b": f_lag,
                "replay_lag_b": r_lag_b,
                "replay_lag_s": r_lag_s
            })

            is_sync = SYNC_SYNC if sy_st.lower() in ("sync", "quorum") else SYNC_ASYNC
            for nr in node_rows:
                n_host = nr.get("host", "")
                n_name = nr.get("name", "")
                if clean_ip and (n_host == clean_ip or normalize_host(n_host) == clean_ip or address_map.get(clean_ip) == n_name):
                    nr["sync"] = is_sync
                elif app_n and (n_name == app_n or app_n.startswith(n_name)):
                    nr["sync"] = is_sync

    # 4. Format Child Tables (Site24x7 Hard Limits: <=10 tables, <=15 cols, <=5 strings, <=25 rows)

    # 4.1 Cluster_Nodes
    cluster_nodes_table: List[Dict[str, Any]] = []
    for r in node_rows[:MAX_ROWS]:
        node_entry = {
            "name": safe_name(r["name"]),
            "role": r["role"],
            "status": r["status"],
            "status_reason": str(r["status_reason"])[:MAX_STRING_CHARS],
            "last_seen_s": r["last_seen_s"],
            "last_seen_ts": str(r["last_seen_ts"])[:MAX_STRING_CHARS],
            "timeline": r["timeline"],
            "replay_lag_s": r["replay_lag_s"],
            "replay_lag_bytes": r["replay_lag_bytes"],
            "conn_pct": r["conn_pct"],
            "resp_ms": r["resp_ms"],
            "sync": r.get("sync"),
            "patroni_state": r["patroni_state"],
            "xact_age_s": r["xact_age_s"]
        }
        cluster_nodes_table.append(node_entry)

    if len(node_rows) > MAX_ROWS:
        omitted = len(node_rows) - MAX_ROWS
        payload["Nodes_Omitted"] = omitted
        cluster_nodes_table.append({
            "name": f"<{omitted} more nodes>",
            "role": ROLE_UNKNOWN,
            "status": STATUS_DOWN,
            "status_reason": f"{omitted} nodes omitted by 25-row limit",
            "last_seen_s": 0,
            "last_seen_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "timeline": 0,
            "replay_lag_s": 0.0,
            "replay_lag_bytes": 0,
            "conn_pct": 0.0,
            "resp_ms": 0.0,
            "patroni_state": PATRONI_STATE_UNKNOWN,
            "xact_age_s": 0
        })
    payload["Cluster_Nodes"] = cluster_nodes_table

    # 4.2 Node_Snapshot
    node_snapshot_table: List[Dict[str, Any]] = []
    for r in node_rows[:MAX_ROWS]:
        node_snapshot_table.append({
            "name": safe_name(r["name"]),
            "status": r.get("status", STATUS_DOWN),
            "version_num": int(r.get("version_num") or 0),
            "uptime_s": int(r.get("uptime_s") or 0),
            "active_queries": int(r.get("active_queries") or 0),
            "idle_in_txn": int(r.get("idle_in_txn") or 0),
            "longest_query_s": int(r.get("longest_query_s") or 0),
            "temp_bytes": int(r.get("temp_bytes") or 0),
            "dead_tuples": int(r.get("dead_tuples") or 0)
        })
    payload["Node_Snapshot"] = node_snapshot_table

    # 4.3 Replication_Links (Finding 3: ONLY real rows)
    replication_links_table: List[Dict[str, Any]] = []
    if rep_link_data:
        for idx, rl in enumerate(rep_link_data[:MAX_ROWS]):
            link_name = safe_name(rl["client_addr"] or rl["app_name"] or f"replica_{idx+1}")
            replication_links_table.append({
                "name": link_name,
                "status": 1 if rl["state"].lower() == "streaming" else 0,
                "application_name": rl["app_name"][:MAX_STRING_CHARS],
                "client_addr": rl["client_addr"][:MAX_STRING_CHARS],
                "state": rl["state"][:MAX_STRING_CHARS],
                "sync_state": rl["sync_state"][:MAX_STRING_CHARS],
                "write_lag_b": rl["write_lag_b"],
                "flush_lag_b": rl["flush_lag_b"],
                "replay_lag_b": rl["replay_lag_b"],
                "replay_lag_s": round(rl["replay_lag_s"], 2)
            })
    elif standby_wal_rec and standby_wal_rec[0]:
        # Standby instance: ONE row describing upstream link from pg_stat_wal_receiver
        s_host = str(standby_wal_rec[0] or "")
        s_port = safe_int(standby_wal_rec[1])
        s_st = str(standby_wal_rec[2] or "streaming")
        s_lag_s = safe_float(standby_wal_rec[4])
        s_lag_b = safe_int(standby_wal_rec[5])
        up_addr = f"{s_host}:{s_port}" if s_port else s_host
        replication_links_table.append({
            "name": safe_name(f"upstream_{up_addr}"),
            "status": 1 if s_st.lower() == "streaming" else 0,
            "client_addr": up_addr[:MAX_STRING_CHARS],
            "state": s_st[:MAX_STRING_CHARS],
            "replay_lag_b": s_lag_b,
            "replay_lag_s": round(s_lag_s, 2)
        })
    # If standalone with no replication, replication_links_table remains empty []
    payload["Replication_Links"] = replication_links_table[:MAX_ROWS]

    # 4.4 Replication_Slots
    replication_slots_table: List[Dict[str, Any]] = []
    for s_row in (slot_rows or [])[:MAX_ROWS]:
        s_name = str(s_row[0] or "")
        s_type = str(s_row[1] or "") if len(s_row) > 1 else "physical"
        s_act = 1 if bool(s_row[2]) else 0 if len(s_row) > 2 else 0
        replication_slots_table.append({
            "name": safe_name(s_name or "slot"),
            "status": s_act,
            "slot_type": s_type[:MAX_STRING_CHARS],
            "active": s_act,
            "retained_mb": 0.0,
            "wal_status": "normal"
        })
    payload["Replication_Slots"] = replication_slots_table

    # 4.5 Database_Stats
    db_stats_table: List[Dict[str, Any]] = []
    if payload.get("DB_Count", 0) > 0:
        db_stats_table.append({
            "name": safe_name(dbname or "postgres"),
            "status": 1,
            "size_mb": float(payload.get("DB_Total_Size_MB", 0.0)),
            "connections": int(payload.get("Primary_Connections", 0)),
            "commit_ratio": 100.0,
            "cache_hit_ratio": float(payload.get("Primary_Cache_Hit_Ratio", 100.0))
        })
    payload["Database_Stats"] = db_stats_table[:MAX_ROWS]

    # 4.6 Wait_Events
    wait_events_table: List[Dict[str, Any]] = []
    wait_events_table.append({
        "name": "CPU_running",
        "status": 1,
        "event_type": "CPU",
        "event": "running",
        "sessions": int(payload.get("Primary_Active_Queries", 0))
    })
    payload["Wait_Events"] = wait_events_table[:MAX_ROWS]

    # 4.7 Topology & Multi-Master / Manager Detection
    if effective_mode == MODE_STANDALONE:
        payload["Topology_Type"] = 0
        manager_str = "standalone"
        leader_val = None
        if standby_wal_rec and standby_wal_rec[0]:
            h = str(standby_wal_rec[0])
            p = str(standby_wal_rec[1]) if len(standby_wal_rec) > 1 and standby_wal_rec[1] else ""
            leader_val = f"{h}:{p}" if p else h
        elif payload.get("Primary_Up") == 1 and payload.get("Primary_Node") and not active_client_is_recovery:
            leader_val = str(payload.get("Primary_Node"))

        topo_entry: Dict[str, Any] = {
            "name": safe_name(cluster_name or "standalone"),
            "status": 1 if payload.get("Primary_Up") == 1 else 0,
            "manager": manager_str,
            "node_count": int(payload.get("Nodes_Total", 1)),
            "timeline": int(payload.get("Primary_Timeline", 1))
        }
        if leader_val:
            topo_entry["leader"] = str(leader_val)[:MAX_STRING_CHARS]
        payload["Topology"] = [topo_entry]
    else:
        is_multi_master = bool(int(merged.get("is_multi_master") or 0)) or str(merged.get("topology_type", "")).lower() in ("multi_master", "4")

        writable_nodes = [r for r in node_rows if r.get("role") == ROLE_PRIMARY]
        if len(writable_nodes) > 1:
            if payload.get("Logical_Replication_Used") == 1 or payload.get("Mesh_Links_Active", 0) > 0:
                is_multi_master = True
            elif not is_multi_master:
                for r in writable_nodes:
                    c = r.get("client")
                    if c and getattr(c, "is_connected", False):
                        sub_row = c.query_one("SELECT count(*) FROM pg_subscription;")
                        if sub_row and safe_int(sub_row[0]) > 0:
                            is_multi_master = True
                            break

        if is_multi_master:
            cluster_manager = TOPOLOGY_MULTI_MASTER
            payload["Topology_Type"] = TOPOLOGY_MULTI_MASTER
            manager_str = "multi_master"
        else:
            payload["Topology_Type"] = cluster_manager
            manager_str = cluster_manager_str

        payload["Topology"] = [{
            "name": safe_name(cluster_name or "postgres_cluster"),
            "status": 1 if payload.get("Primary_Up") == 1 else 0,
            "leader": str(payload.get("Primary_Node") or "none")[:MAX_STRING_CHARS],
            "manager": manager_str,
            "node_count": int(payload.get("Nodes_Total", 0)),
            "timeline": int(payload.get("Primary_Timeline", 0))
        }]

    # 5. Evaluate Health (Branching Standalone vs Cluster)
    auth_failed_nodes = [r for r in node_rows if r.get("auth_failed")]
    auth_failure = len(auth_failed_nodes) > 0 or any("password authentication failed" in w.lower() or "auth failed for user" in w.lower() for w in all_warnings)
    auth_msg = ""
    if auth_failure:
        if auth_failed_nodes:
            first_auth = auth_failed_nodes[0]
            auth_msg = first_auth.get("auth_error") or f"auth failed for user {username} on {first_auth.get('name')}"
        else:
            auth_msg = f"auth failed for user {username} on pg1"

    if effective_mode == MODE_STANDALONE:
        target_row = node_rows[0] if node_rows else {}
        connected = (target_row.get("status") == STATUS_UP)
        is_recovery = (target_row.get("role") == ROLE_STANDBY)
        unsupported = "unsupported_version" in str(target_row.get("status_reason", ""))

        health = evaluate_database_health(
            connected=connected,
            auth_failure=auth_failure,
            auth_msg=auth_msg,
            unsupported_version=unsupported,
            version_str=str(target_row.get("version_num", "")),
            conn_pct=payload.get("Primary_Connection_Pct", 0.0),
            xid_wraparound_pct=payload.get("Primary_XID_Wrap_Pct", 0.0),
            active_queries=payload.get("Primary_Active_Queries", 0),
            longest_query_s=payload.get("Primary_Longest_Txn_s", 0),
            status_reason=str(target_row.get("status_reason", "")),
            is_recovery=is_recovery,
            uptime_s=payload.get("Primary_Uptime_s", 0),
            archive_failed=payload.get("Primary_Archive_Failed", 0),
        )

        payload["Cluster_Health"] = health.severity
        payload["Health_Code"] = health.code
        payload["Health_Reason"] = health.fact[:MAX_STRING_CHARS]
        payload["Action_Hint"] = health.hint[:MAX_STRING_CHARS]
        payload["msg"] = health.format_msg()

        if health.severity == HEALTH_CRITICAL or auth_failure or not connected or unsupported:
            payload["status"] = STATUS_DOWN
        else:
            payload["status"] = STATUS_UP
    else:
        health = evaluate_cluster_health(
            has_primary=any(r["role"] == ROLE_PRIMARY and r["status"] == STATUS_UP for r in node_rows),
            primary_name=payload.get("Primary_Node", ""),
            nodes_up=nodes_up,
            nodes_total=nodes_total,
            timeline=payload.get("Primary_Timeline", 1),
            primaries_count=len([r for r in node_rows if r["role"] == ROLE_PRIMARY and r["status"] == STATUS_UP]),
            expected_standbys=payload.get("Standbys_Expected", 0),
            streaming_standbys=payload.get("Standbys_Streaming", 0),
            sync_standbys_expected=0,
            sync_standbys_actual=payload.get("Sync_Standby_Count", 0),
            inactive_slots=payload.get("Inactive_Slots_Count", 0),
            xid_wraparound_pct=payload.get("Primary_XID_Wrap_Pct", 0.0),
            max_replay_lag_s=payload.get("Max_Replay_Lag_s", 0.0),
            max_replay_backlog_b=payload.get("Max_Replay_Backlog", 0),
            timeline_spread=payload.get("Timeline_Spread", 0),
            failover_age_s=payload.get("Failover_Age_s", -1),
            conn_saturation_pct=payload.get("Primary_Connection_Pct", 0.0),
            archive_failed=payload.get("Primary_Archive_Failed", 0),
            auth_failure=auth_failure,
            auth_msg=auth_msg,
            is_multi_master=is_multi_master
        )

        payload["Cluster_Health"] = health.severity
        payload["Health_Code"] = health.code
        payload["Health_Reason"] = health.fact[:MAX_STRING_CHARS]
        payload["Action_Hint"] = health.hint[:MAX_STRING_CHARS]
        payload["msg"] = health.format_msg()

        if health.severity == HEALTH_CRITICAL or auth_failure:
            payload["status"] = STATUS_DOWN
        else:
            payload["status"] = STATUS_UP

    # Finding 9: Append metric_unavailable note to msg if any metric failed
    unavail_notes = [w for w in all_warnings if "metric_unavailable" in w]
    if unavail_notes:
        note = unavail_notes[0]
        if note not in payload["msg"]:
            payload["msg"] = f"{payload['msg']} | {note}"[:MAX_MSG_CHARS]

    if auth_failure:
        payload["Auth_Failure_Flag"] = 1

    payload["Collect_Warnings"] = len(all_warnings)
    payload["Queries_Run"] = queries_count
    payload["Collect_Time_ms"] = round((time.time() - t0) * 1000.0, 2)

    # Fix 9: Backward compatibility injection for official postgres plugin
    if compat_official == 1:
        # Check metric budget: platform cap is 200
        cur_metric_count = len([k for k, v in payload.items() if k not in RESERVED_KEYS and not isinstance(v, (list, dict))]) + len(compat_metrics)
        if cur_metric_count > 190:
            budget_warn = f"METRIC_BUDGET_WARNING: {cur_metric_count} metrics near 200 cap"
            all_warnings.append(budget_warn)
            payload["msg"] = f"{payload['msg']} | {budget_warn}"[:MAX_MSG_CHARS]

        compat_units = copy.deepcopy(OFFICIAL_COMPAT_UNITS)
        compat_tabs = copy.deepcopy(OFFICIAL_COMPAT_TABS)

        # Finding 7: On PG < 14, prune Total Sessions* from units, tabs, and tables
        if active_client_version < (14, 0):
            for s_key in ("Total Sessions", "Total Sessions Abandoned", "Total Sessions Fatal", "Total Sessions Killed"):
                compat_units.pop(s_key, None)
                for t_info in compat_tabs.values():
                    if "tablist" in t_info:
                        t_info["tablist"] = [x for x in t_info["tablist"] if x != s_key]

        payload["units"].update(compat_units)
        payload["units"]["Stats_per_DB"] = copy.deepcopy(OFFICIAL_COMPAT_TABLE_UNITS["Stats_per_DB"])

        txn_units = copy.deepcopy(OFFICIAL_COMPAT_TABLE_UNITS["Transactions_Per_Database"])
        if active_client_version < (14, 0):
            for sc in ("sessions", "sessions_abandoned", "sessions_fatal", "sessions_killed", "session_time", "sessions_active_time", "idle_in_txn_time"):
                txn_units.pop(sc, None)
        payload["units"]["Transactions_Per_Database"] = txn_units

        payload["tabs"].update(compat_tabs)

        payload["Stats_per_DB"] = compat_db_stats[:MAX_ROWS]
        payload["Transactions_Per_Database"] = compat_txn_sessions[:MAX_ROWS]
        payload["s247config"] = {
            "childdiscovery": [
                t for t in ["Transactions_Per_Database", "Stats_per_DB"]
                if payload.get(t) and len(payload.get(t)) > 0
            ]
        }
        payload.update(compat_metrics)

    # 6. Save state store & attach diagnostics
    store.save(new_state)
    payload.update(store.diagnostics())

    # 7. Validate payload integrity
    violations = validate_output(payload)
    if violations:
        payload["msg"] = f"schema: {'; '.join(violations[:2])}"[:MAX_MSG_CHARS]

    return payload




def main():
    parser = argparse.ArgumentParser(description=f"Site24x7 PostgreSQL Cluster Monitor v{PLUGIN_VERSION}")
    parser.add_argument("--self-test", action="store_true", help="Run in-process pure validation checks")
    parser.add_argument("--json-out", type=str, default="", help="Write emitted JSON to specified file")
    parser.add_argument("--nodes", type=str, default="", help="Comma-separated node specifications (e.g. pg1=host:port)")
    parser.add_argument("--cluster_host", type=str, default="", help="Hostname or IP of cluster seed node")
    parser.add_argument("--postgres_port", type=int, default=5432, help="PostgreSQL server port")
    parser.add_argument("--patroni_port", type=int, default=0, help="Patroni REST API port")
    parser.add_argument("--address_map", type=str, default="", help="Address translation map (e.g. pg1:5432=127.0.0.1:5441)")
    parser.add_argument("--username", type=str, default="", help="Monitoring username")
    parser.add_argument("--password", type=str, default="", help="Monitoring password")
    parser.add_argument("--db", type=str, default="postgres", help="Target database name")
    parser.add_argument("--cluster_name", type=str, default="", help="Cluster name override")
    parser.add_argument("--state_dir", type=str, default="", help="State file directory override")
    parser.add_argument("--sslmode", type=str, default="prefer", help="PostgreSQL SSL mode")
    parser.add_argument("--cycle_deadline", type=float, default=40.0, help="Total cycle collection deadline in seconds")
    parser.add_argument("--hard_exit", type=int, default=0, help="1 for immediate os._exit(0), 0 for clean interpreter exit")
    parser.add_argument("--is_multi_master", type=int, default=0, help="1 for multi-master active-active topology")
    parser.add_argument("--topology_type", type=str, default="", help="Topology type override")
    parser.add_argument("--compat_official", type=int, default=1, help="1 for official postgres backward compatibility, 0 for pure cluster")
    parser.add_argument("--monitor_mode", type=str, default="", help="Monitoring mode: auto | standalone | cluster")
    args, _ = parser.parse_known_args()

    if args.self_test:
        sys.exit(self_test())

    params: Dict[str, Any] = {}
    if args.monitor_mode:
        params["monitor_mode"] = args.monitor_mode
    if args.nodes:
        params["nodes"] = args.nodes
    if args.cluster_host:
        params["cluster_host"] = args.cluster_host
    if args.postgres_port:
        params["postgres_port"] = args.postgres_port
    if args.patroni_port:
        params["patroni_port"] = args.patroni_port
    if args.address_map:
        params["address_map"] = args.address_map
    if args.username:
        params["username"] = args.username
    if args.password:
        params["password"] = args.password
    if args.db:
        params["db"] = args.db
    if args.cluster_name:
        params["cluster_name"] = args.cluster_name
    if args.state_dir:
        params["state_dir"] = args.state_dir
    if args.sslmode:
        params["sslmode"] = args.sslmode
    if args.cycle_deadline:
        params["cycle_deadline"] = args.cycle_deadline
    if args.hard_exit:
        params["hard_exit"] = args.hard_exit
    if args.is_multi_master:
        params["is_multi_master"] = args.is_multi_master
    if args.topology_type:
        params["topology_type"] = args.topology_type
    if args.compat_official is not None:
        params["compat_official"] = args.compat_official

    result = run(params)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    print(json.dumps(result))
    sys.stdout.flush()
    if int(params.get("hard_exit") or 0) == 1:
        os._exit(0)


if __name__ == "__main__":
    main()
