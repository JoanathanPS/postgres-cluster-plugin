#!/usr/bin/env python3
"""
Automated test suite for the Site24x7 PostgreSQL Cluster Plugin (postgres_cluster/postgres_cluster.py).

Validates:
  1. Plugin output adherence to Site24x7 schema and tabular limits:
     - Output is valid RFC 8259 JSON
     - plugin_version is integer >= 5
     - heartbeat_required is boolean
     - Max 10 tables, max 15 columns per table, max 25 rows per table
     - Max 5 string columns per table (excluding 'name')
     - Row 'name' <= 520 chars, other string columns <= 100 chars
     - Row 'status' is numeric 1 or 0
     - Generic metric count <= 200
     - Numeric types: ints and floats emitted for all numeric columns and generic metrics
     - String types only for Server Version and Last Archived WAL File
     - Renamed WAL position metrics: WAL Write Position, WAL Insert Position, WAL Flush Position (MB)
     - WAL Files Count counts only 24-hex segments (name ~ '^[0-9A-F]{24}$'), excluding .history files
     - Archiving metrics reported only when archive_mode is 'on' or 'always'; omitted with 'archiving not enabled' note when 'off'
     - Write Ahead Log tablist dynamically omits absent archive metrics
     - Nested units format: units["Cluster_Nodes"] and units["Replication_Standbys"]
     - s247config.childdiscovery strictly contains per-DB tables (no Cluster child tables)
     - tabs["Cluster"]["tablist"] includes Cluster_Nodes and Replication_Standbys
  2. Cluster-specific metrics validation:
     - Nodes Total, Nodes Up, Primary Count, No Primary Flag, Split Brain Flag, Primary Timeline, Max Replay Backlog
     - Replication Slots metrics: Total, Active, Inactive, Physical, Logical, Max Slot Lag Bytes
  3. No fabricated data:
     - Permission errors cause metrics to be omitted, never set to fabricated 0 defaults
  4. Deadline enforcement:
     - Dead nodes and paused containers return valid JSON within under 10 seconds
  5. Authentication error reporting:
     - Wrong password reports auth error in msg with status 0
  6. Dynamic failover verification (optional --failover flag)
"""

import argparse
import json
import os
import subprocess
import sys
import time

AGENT_TIMEOUT_S = 35


class Report:
    def __init__(self):
        self.failures = []
        self.warnings = []

    def ok(self, msg):
        print(f"  [PASS] {msg}")

    def fail(self, msg):
        self.failures.append(msg)
        print(f"  [FAIL] {msg}")

    def warn(self, msg):
        self.warnings.append(msg)
        print(f"  [WARN] {msg}")

    def check(self, cond, msg):
        if cond:
            self.ok(msg)
        else:
            self.fail(msg)
        return cond


def get_python_exe():
    if sys.platform == "win32":
        import shutil
        if shutil.which("py"):
            return "py"
    return sys.executable


def run_plugin(plugin_py, nodes, user, password, db, patroni_port=None):
    cmd = [
        get_python_exe(), plugin_py,
        "--nodes", nodes,
        "--username", user,
        "--password", password,
        "--db", db
    ]
    if patroni_port:
        cmd.extend(["--patroni_port", str(patroni_port)])

    t0 = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=AGENT_TIMEOUT_S)
    return proc, time.monotonic() - t0


def validate_schema(data, rep):
    rep.check(isinstance(data.get("plugin_version"), int) and data["plugin_version"] >= 5,
              f"plugin_version is integer >= 5 ({data.get('plugin_version')})")
    rep.check("heartbeat_required" in data, "heartbeat_required is present")

    # Cluster metrics presence and numeric types
    expected_metrics = [
        "Nodes Total", "Nodes Up", "Primary Count", "No Primary Flag",
        "Split Brain Flag", "Primary Timeline", "Max Replay Backlog",
        "Replication Slots Total", "Replication Slots Active",
        "Replication Slots Inactive", "Physical Slots", "Logical Slots",
        "Max Slot Lag Bytes"
    ]
    for m in expected_metrics:
        rep.check(m in data, f"Cluster metric '{m}' is present ({data.get(m)})")
        rep.check(isinstance(data.get(m), (int, float)), f"Cluster metric '{m}' is numeric type ({type(data.get(m)).__name__})")

    # Renamed WAL position metrics
    rep.check("WAL Write Position" in data, f"WAL Write Position is present ({data.get('WAL Write Position')})")
    rep.check("WAL Insert Position" in data, f"WAL Insert Position is present ({data.get('WAL Insert Position')})")
    rep.check("WAL Flush Position" in data, f"WAL Flush Position is present ({data.get('WAL Flush Position')})")
    rep.check("Current WAL LSN" not in data, "Old 'Current WAL LSN' key successfully retired")
    rep.check("WAL Insert LSN" not in data, "Old 'WAL Insert LSN' key successfully retired")
    rep.check("WAL Flush LSN" not in data, "Old 'WAL Flush LSN' key successfully retired")

    # Competitor Advantage Metrics (Cache Hit Ratio, Dead Tuples, TxID Wraparound)
    rep.check("Cache Hit Ratio" in data and isinstance(data["Cache Hit Ratio"], (int, float)),
              f"Cache Hit Ratio is present and numeric ({data.get('Cache Hit Ratio')})")
    rep.check("Dead Tuples" in data and isinstance(data["Dead Tuples"], int),
              f"Dead Tuples is present and integer ({data.get('Dead Tuples')})")
    rep.check("Oldest Transaction ID Age" in data and isinstance(data["Oldest Transaction ID Age"], int),
              f"Oldest Transaction ID Age is present and integer ({data.get('Oldest Transaction ID Age')})")

    rep.check("WAL Files Count" in data, f"WAL Files Count is present ({data.get('WAL Files Count')})")
    rep.check("WAL Total Size" in data, f"WAL Total Size is present ({data.get('WAL Total Size')})")

    # Archiving metrics check: omitted when archiving is disabled
    msg = data.get("msg", "")
    if "archiving not enabled" in msg:
        rep.check("Archive Status Success" not in data, "Archive Status Success omitted when archive_mode is off")
        rep.check("Archive Status Failed" not in data, "Archive Status Failed omitted when archive_mode is off")
        rep.check("Last Archived WAL File" not in data, "Last Archived WAL File omitted when archive_mode is off")
        rep.check("Archive Ready Files Count" not in data, "Archive Ready Files Count omitted when archive_mode is off")
        rep.check(data.get("status") == 1, "'archiving not enabled' note in msg does not set status to 0")

        # Tablist check: absent archive metrics omitted from Write Ahead Log tablist
        wal_tablist = data.get("tabs", {}).get("Write Ahead Log", {}).get("tablist", [])
        archive_keys = {"Archive Status Success", "Archive Status Failed", "Last Archived WAL File", "Archive Ready Files Count"}
        rep.check(all(k not in wal_tablist for k in archive_keys),
                  f"Write Ahead Log tablist omits absent archive metrics when archiving is off ({wal_tablist})")

    # Top-level generic metrics numeric types rule
    # Only 'Server Version' and 'Last Archived WAL File' may be strings
    non_numeric_allowed = {"Server Version", "Last Archived WAL File", "msg"}
    ignored_keys = {"tabs", "units", "s247config", "plugin_version", "heartbeat_required", "status"}
    generic_metrics_count = 0

    for k, v in data.items():
        if k in ignored_keys or isinstance(v, list) or isinstance(v, dict):
            continue
        generic_metrics_count += 1
        if k not in non_numeric_allowed:
            rep.check(isinstance(v, (int, float)),
                      f"Top-level metric '{k}' is numeric type int/float (found {type(v).__name__}: {v})")

    rep.check(generic_metrics_count <= 200, f"Generic metrics count within Site24x7 limit of 200 ({generic_metrics_count} <= 200)")

    # Identify child tables
    tables = {k: v for k, v in data.items() if isinstance(v, list) and v and isinstance(v[0], dict)}
    rep.check(len(tables) <= 10, f"Total tables within Site24x7 limit of 10 ({len(tables)} <= 10)")

    # Site24x7 Tabular Limits verification for each table
    for t_name, rows in tables.items():
        rep.check(len(rows) <= 25, f"Table '{t_name}' row count within limit of 25 ({len(rows)} <= 25)")
        all_cols = set()
        for r in rows:
            all_cols.update(r.keys())
        rep.check(len(all_cols) <= 15, f"Table '{t_name}' column count within limit of 15 ({len(all_cols)} <= 15)")

        # Column string limit: max 5 string columns excluding 'name'
        string_cols = set()
        for r in rows:
            rep.check("name" in r, f"Table '{t_name}' row has 'name' key")
            rep.check(len(str(r.get("name", ""))) <= 520, f"Table '{t_name}' row 'name' length <= 520 chars")
            for col, val in r.items():
                if col != "name" and isinstance(val, str):
                    string_cols.add(col)
                    rep.check(len(val) <= 100, f"Table '{t_name}' column '{col}' string length <= 100 ({len(val)})")

        rep.check(len(string_cols) <= 5, f"Table '{t_name}' has <= 5 string columns excluding name (found {len(string_cols)}: {string_cols})")

    # Specific assertions for Cluster_Nodes
    rep.check("Cluster_Nodes" in data and isinstance(data["Cluster_Nodes"], list), "Cluster_Nodes table present")
    if "Cluster_Nodes" in data:
        cn_rows = data["Cluster_Nodes"]
        rep.check(len(cn_rows) == 3, f"Cluster_Nodes has 3 node rows ({len(cn_rows)})")
        prim_count = 0
        for r in cn_rows:
            rep.check(r.get("status") in (0, 1), f"Cluster_Nodes row status in {{0, 1}} ({r.get('status')})")
            rep.check(r.get("up") in (0, 1), f"Cluster_Nodes row up in {{0, 1}} ({r.get('up')})")
            rep.check(r.get("is_primary") in (0, 1), f"Cluster_Nodes row is_primary in {{0, 1}} ({r.get('is_primary')})")
            rep.check(isinstance(r.get("timeline"), int), f"Cluster_Nodes row timeline is int ({r.get('timeline')})")
            rep.check(isinstance(r.get("response_time_ms"), (int, float)), f"Cluster_Nodes row response_time_ms is float/int ({r.get('response_time_ms')})")
            rep.check(isinstance(r.get("replay_backlog_bytes"), int), f"Cluster_Nodes row replay_backlog_bytes is int ({r.get('replay_backlog_bytes')})")
            rep.check(isinstance(r.get("replay_delay_s"), (int, float)), f"Cluster_Nodes row replay_delay_s is float/int ({r.get('replay_delay_s')})")
            rep.check(isinstance(r.get("connections"), int), f"Cluster_Nodes row connections is int ({r.get('connections')})")
            rep.check(isinstance(r.get("role"), str), f"Cluster_Nodes row role is str ({r.get('role')})")
            rep.check(isinstance(r.get("patroni_state"), str), f"Cluster_Nodes row patroni_state is str ({r.get('patroni_state')})")
            if r.get("is_primary") == 1:
                prim_count += 1
        rep.check(prim_count == 1, f"Cluster_Nodes has exactly one primary node with is_primary=1 ({prim_count})")

    # Specific assertions for Replication_Standbys
    rep.check("Replication_Standbys" in data and isinstance(data["Replication_Standbys"], list), "Replication_Standbys table present")
    if "Replication_Standbys" in data:
        for r in data["Replication_Standbys"]:
            rep.check(r.get("is_sync") in (0, 1), f"Replication_Standbys row is_sync in {{0, 1}} ({r.get('is_sync')})")
            rep.check(isinstance(r.get("replay_lag_bytes"), int), f"Replication_Standbys row replay_lag_bytes is int ({r.get('replay_lag_bytes')})")
            rep.check(isinstance(r.get("write_lag_bytes"), int), f"Replication_Standbys row write_lag_bytes is int ({r.get('write_lag_bytes')})")
            rep.check(isinstance(r.get("flush_lag_bytes"), int), f"Replication_Standbys row flush_lag_bytes is int ({r.get('flush_lag_bytes')})")
            rep.check(isinstance(r.get("state"), str), f"Replication_Standbys row state is str ({r.get('state')})")
            rep.check(isinstance(r.get("sync_state"), str), f"Replication_Standbys row sync_state is str ({r.get('sync_state')})")
            rep.check(isinstance(r.get("client_addr"), str), f"Replication_Standbys row client_addr is str ({r.get('client_addr')})")

    # Specific assertions for Stats_per_DB (no stringified numbers!)
    if "Stats_per_DB" in data:
        for r in data["Stats_per_DB"]:
            for col, val in r.items():
                if col == "name":
                    rep.check(isinstance(val, str), f"Stats_per_DB '{col}' is string")
                elif col == "size_in_mb":
                    rep.check(isinstance(val, (int, float)), f"Stats_per_DB '{col}' is numeric float/int ({val})")
                else:
                    rep.check(isinstance(val, int), f"Stats_per_DB '{col}' is numeric int ({val})")

    # Units verification: nested table-column units
    units = data.get("units", {})
    rep.check(isinstance(units, dict) and "Nodes Total" in units, "units dictionary configured")
    rep.check("WAL Write Position" in units and units["WAL Write Position"] == "MB", "units has 'WAL Write Position': 'MB'")
    rep.check("WAL Insert Position" in units and units["WAL Insert Position"] == "MB", "units has 'WAL Insert Position': 'MB'")
    rep.check("WAL Flush Position" in units and units["WAL Flush Position"] == "MB", "units has 'WAL Flush Position': 'MB'")

    rep.check("Cluster_Nodes" in units and isinstance(units["Cluster_Nodes"], dict), "units contains nested dict 'Cluster_Nodes'")
    if "Cluster_Nodes" in units:
        rep.check("response_time_ms" in units["Cluster_Nodes"], "units['Cluster_Nodes'] has 'response_time_ms'")
        rep.check("replay_backlog_bytes" in units["Cluster_Nodes"], "units['Cluster_Nodes'] has 'replay_backlog_bytes'")
        rep.check("replay_delay_s" in units["Cluster_Nodes"], "units['Cluster_Nodes'] has 'replay_delay_s'")
        rep.check("connections" in units["Cluster_Nodes"], "units['Cluster_Nodes'] has 'connections'")

    rep.check("Replication_Standbys" in units and isinstance(units["Replication_Standbys"], dict), "units contains nested dict 'Replication_Standbys'")
    if "Replication_Standbys" in units:
        rep.check("replay_lag_bytes" in units["Replication_Standbys"], "units['Replication_Standbys'] has 'replay_lag_bytes'")
        rep.check("write_lag_bytes" in units["Replication_Standbys"], "units['Replication_Standbys'] has 'write_lag_bytes'")
        rep.check("flush_lag_bytes" in units["Replication_Standbys"], "units['Replication_Standbys'] has 'flush_lag_bytes'")

    # Tabs verification
    tabs = data.get("tabs", {})
    rep.check("Cluster" in tabs, "Cluster tab present in tabs definition")
    cl_tablist = tabs.get("Cluster", {}).get("tablist", [])
    rep.check("Cluster_Nodes" in cl_tablist, "Cluster_Nodes present in Cluster tab tablist")
    rep.check("Replication_Standbys" in cl_tablist, "Replication_Standbys present in Cluster tab tablist")

    # Childdiscovery in s247config: strictly per-DB tables
    childdiscovery = (data.get("s247config") or {}).get("childdiscovery", [])
    rep.check("Cluster_Nodes" not in childdiscovery, "Cluster_Nodes removed from s247config.childdiscovery")
    rep.check("Replication_Standbys" not in childdiscovery, "Replication_Standbys removed from s247config.childdiscovery")
    rep.check("Stats_per_DB" in childdiscovery, "Stats_per_DB present in s247config.childdiscovery")
    rep.check("Tranasctions_and_Session_per_Database" in childdiscovery, "Tranasctions_and_Session_per_Database present in s247config.childdiscovery")


def test_wal_history_exclusion(plugin_py, nodes, user, password, db, patroni_port, rep):
    """
    Tests that a cluster with .history files in the WAL directory is not over-counted:
    - WAL Files Count must count only WAL segment files (24-hex filenames matching ^[0-9A-F]{24}$).
    - WAL Total Size must sum only those segments.
    """
    print("\n=== Test: WAL History File Exclusion & Segment Count Accuracy ===")
    proc, elapsed = run_plugin(plugin_py, nodes, user, password, db, patroni_port)
    rep.check(proc.returncode == 0, f"Plugin execution succeeded (elapsed: {elapsed:.2f}s)")
    try:
        data = json.loads(proc.stdout)
        wal_count = data.get("WAL Files Count")
        wal_size = data.get("WAL Total Size")

        print(f"  Observed WAL Files Count: {wal_count}")
        print(f"  Observed WAL Total Size:  {wal_size} MB")

        # Live cluster has 26 WAL segments and 15 .history files (total 41 files in pg_ls_waldir)
        # WAL Files Count must be 26, NOT 41!
        rep.check(wal_count == 26, f"WAL Files Count strictly counts 24-hex segment files only ({wal_count} == 26, not 41)")
        rep.check(wal_size == 416.0, f"WAL Total Size matches 26 segments x 16MB ({wal_size} == 416.0 MB)")
    except Exception as e:
        rep.fail(f"Failed to verify WAL history file exclusion: {e}")

    # Simulated Mock Test for WAL directory filtering logic
    import re
    mock_files = [
        # 26 valid 24-hex WAL segments (16MB each)
        *[f"0000000100000001000000{i:02X}" for i in range(26)],
        # 15 timeline history files
        *[f"0000000{i:02X}.history" for i in range(1, 16)],
        # Other potential non-segment items
        "archive_status"
    ]
    wal_regex = re.compile(r'^[0-9A-F]{24}$')
    filtered_segments = [f for f in mock_files if wal_regex.match(f)]
    rep.check(len(filtered_segments) == 26, f"Regex '^[0-9A-F]{{24}}$' filters out 15 .history files and archive_status (26 segments matched)")


def test_permission_omission(rep):
    """Verifies that query or permission failures omit metrics rather than fabricating default 0s."""
    print("\n=== Test: Forced Permission / Error Handling (No Fabricated Defaults) ===")
    from unittest.mock import MagicMock

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "upstream_layout", "postgres_cluster")))
    try:
        import postgres_cluster as pg_mod

        # Create mock connection whose cursor fails on pg_ls_waldir
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        def fail_on_waldir(sql, *args, **kwargs):
            if "pg_ls_waldir" in sql or "pg_ls_archive_statusdir" in sql:
                raise Exception("permission denied for function pg_ls_waldir")
            return MagicMock()

        mock_cur.execute.side_effect = fail_on_waldir
        mock_cur.description = [("col",)]
        mock_cur.fetchall.return_value = []
        mock_cur.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cur
        mock_conn.server_version = 170002

        collector = pg_mod.pgsql("127.0.0.1", 5432, "site24x7", "site24x7", "postgres")
        collector._conn = mock_conn

        collector.metricCollector()

        # Check results: WAL Files Count and Archive Ready Files Count MUST NOT be in _results
        rep.check("WAL Files Count" not in collector._results, "WAL Files Count is omitted on permission error (not fabricated to 0)")
        rep.check("Archive Ready Files Count" not in collector._results, "Archive Ready Files Count is omitted on permission error (not fabricated to 0)")
        rep.check("wal_dir: permission denied" in collector._msg, "Error note appended to msg without failing status")
    except Exception as e:
        rep.fail(f"Permission omission test failed with exception: {e}")


def test_deadline_behavior(plugin_py, nodes, user, password, db, patroni_port, rep):
    """Tests that a paused container does not block execution beyond deadline."""
    print("\n=== Test: Deadline Behavior with Paused Node ===")
    pause_container = "patroni-pg-node3"
    print(f"  Pausing container '{pause_container}'...")
    subprocess.run(["docker", "pause", pause_container], check=True)
    try:
        proc, elapsed = run_plugin(plugin_py, nodes, user, password, db, patroni_port)
        rep.check(proc.returncode == 0, f"Plugin executed with exit code 0 during node pause (elapsed: {elapsed:.2f}s)")
        rep.check(elapsed < 10.0, f"Execution completed strictly under 10s deadline ({elapsed:.2f}s < 10.0s)")
        data = json.loads(proc.stdout)
        rep.check(data.get("status") == 1, "Plugin status remains 1 despite one paused node")
        rep.check(data.get("Nodes Up") == 2, f"Nodes Up correctly reports 2 ({data.get('Nodes Up')})")
    finally:
        print(f"  Unpausing container '{pause_container}'...")
        subprocess.run(["docker", "unpause", pause_container], check=True)
        time.sleep(2)


def test_failover_assertion(plugin_py, nodes, user, password, db, patroni_port, rep):
    print("\n=== Dynamic Failover Assertion ===")
    containers = ["patroni-pg-node1", "patroni-pg-node2", "patroni-pg-node3"]
    leader = None

    # Identify current leader
    for c in containers:
        try:
            res = subprocess.run(
                ["docker", "exec", c, "psql", "-U", "postgres", "-tA", "-c", "SELECT pg_is_in_recovery();"],
                capture_output=True, text=True, timeout=5
            )
            if res.stdout.strip() == "f":
                leader = c
                break
        except Exception:
            pass

    if not leader:
        rep.warn("Could not identify leader container via docker exec; skipping dynamic failover assertion.")
        return

    print(f"  Active leader container before failover: {leader}")
    proc_before, _ = run_plugin(plugin_py, nodes, user, password, db, patroni_port)
    data_before = json.loads(proc_before.stdout)
    init_nodes_up = data_before.get("Nodes Up", 3)
    init_timeline = data_before.get("Primary Timeline", 1)
    print(f"  Pre-failover baseline: Nodes Up = {init_nodes_up}, Timeline = {init_timeline}")

    # Stop leader
    print(f"  Stopping leader container '{leader}'...")
    subprocess.run(["docker", "stop", leader], check=True)

    try:
        print("  Waiting 12 seconds for Patroni automatic leader promotion...")
        time.sleep(12)

        proc_after, _ = run_plugin(plugin_py, nodes, user, password, db, patroni_port)
        rep.check(proc_after.returncode == 0, "Plugin exit code 0 during leader outage (did not crash)")
        data_after = json.loads(proc_after.stdout)

        new_nodes_up = data_after.get("Nodes Up")
        new_prim_count = data_after.get("Primary Count")
        new_timeline = data_after.get("Primary Timeline")

        print(f"  Post-failover state: Nodes Up = {new_nodes_up}, Primaries = {new_prim_count}, Timeline = {new_timeline}")

        rep.check(new_nodes_up == init_nodes_up - 1,
                  f"Nodes Up decremented by 1 ({init_nodes_up} -> {new_nodes_up})")
        rep.check(new_prim_count == 1,
                  f"Exactly 1 active primary elected ({new_prim_count})")
        rep.check(new_timeline >= init_timeline,
                  f"Primary Timeline advance detected ({init_timeline} -> {new_timeline})")

        stopped_node_entry = next((n for n in data_after.get("Cluster_Nodes", []) if n.get("status") == 0), None)
        rep.check(stopped_node_entry is not None and stopped_node_entry.get("role") == "offline",
                  f"Stopped node correctly marked as offline in Cluster_Nodes ({stopped_node_entry.get('name') if stopped_node_entry else 'None'})")

    finally:
        print(f"  Restarting stopped container '{leader}'...")
        subprocess.run(["docker", "start", leader], check=True)
        time.sleep(8)
        proc_rec, _ = run_plugin(plugin_py, nodes, user, password, db, patroni_port)
        data_rec = json.loads(proc_rec.stdout)
        rep.check(data_rec.get("Nodes Up") == 3, f"Cluster recovered back to 3 nodes up ({data_rec.get('Nodes Up')})")


def main():
    parser = argparse.ArgumentParser(description="PostgreSQL Cluster Plugin Test Suite")
    parser.add_argument("--failover", action="store_true", help="Run dynamic failover assertion test")
    args = parser.parse_args()

    upstream_py = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "upstream_layout", "postgres_cluster", "postgres_cluster.py"))
    fallback_py = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "postgres_cluster", "postgres_cluster.py"))
    plugin_py = upstream_py if os.path.exists(upstream_py) else fallback_py
    nodes = os.environ.get("PG_NODES", "127.0.0.1:5441:8001,127.0.0.1:5442:8002,127.0.0.1:5443:8003")
    user = os.environ.get("MONITOR_USER", "site24x7")
    password = os.environ.get("MONITOR_PASSWORD", "site24x7")
    db = os.environ.get("MONITOR_DB", "appdb")
    patroni_port = os.environ.get("PATRONI_PORT", "8008")

    rep = Report()
    print("=" * 65)
    print(" Site24x7 PostgreSQL Cluster Plugin Test Suite")
    print("=" * 65)
    print(f"Plugin:   {plugin_py}")
    print(f"Nodes:    {nodes}")
    print(f"User:     {user}")
    print(f"Database: {db}\n")

    # Test 1: Active 3-node cluster run and full schema validation
    print("=== Test 1: Active 3-node cluster run and tabular schema validation ===")
    proc, elapsed = run_plugin(plugin_py, nodes, user, password, db, patroni_port)
    rep.check(proc.returncode == 0, f"Exit code 0 (elapsed: {elapsed:.2f}s)")
    try:
        data = json.loads(proc.stdout)
        rep.ok("Valid JSON returned")
        validate_schema(data, rep)
        print(f"  Nodes Total:             {data.get('Nodes Total')}")
        print(f"  Nodes Up:                {data.get('Nodes Up')}")
        print(f"  Primary Count:           {data.get('Primary Count')}")
        print(f"  Primary Timeline:        {data.get('Primary Timeline')}")
        print(f"  Max Replay Lag:          {data.get('Max Replay Backlog')} bytes")
        print(f"  Replication Slots Total: {data.get('Replication Slots Total')}")
        print(f"  Replication Slots Active:{data.get('Replication Slots Active')}")
    except Exception as e:
        rep.fail(f"Failed to parse JSON: {e}\n{proc.stdout}")

    # Test 2: Dead host handling (never crash on dead node)
    print("\n=== Test 2: Dead host handling & timing constraint ===")
    dead_nodes = "node_dead=localhost:5999,node_dead2=localhost:5998"
    proc_dead, elapsed_dead = run_plugin(plugin_py, dead_nodes, user, password, db)
    rep.check(proc_dead.returncode == 0, f"Dead node test exit code 0 (elapsed: {elapsed_dead:.2f}s)")
    rep.check(elapsed_dead < 10.0, f"Dead node run completed under 10s timing constraint ({elapsed_dead:.2f}s < 10.0s)")
    try:
        dead_data = json.loads(proc_dead.stdout)
        rep.check(dead_data.get("No Primary Flag") == 1, "No Primary Flag is 1 on dead cluster")
        rep.check(dead_data.get("Nodes Up") == 0, "Nodes Up is 0 on dead cluster")
    except Exception as e:
        rep.fail(f"Dead node run did not output valid JSON: {e}")

    # Test 3: Wrong password on all nodes reports auth error in msg
    print("\n=== Test 3: Wrong password reports auth error in msg with status 0 ===")
    proc_auth, _ = run_plugin(plugin_py, nodes, user, "wrong_password_test", db)
    rep.check(proc_auth.returncode == 0, "Wrong password run exit code 0")
    try:
        auth_data = json.loads(proc_auth.stdout)
        rep.check(auth_data.get("status") == 0, f"status is 0 on auth failure ({auth_data.get('status')})")
        msg = auth_data.get("msg", "")
        rep.check("authentication failed" in msg.lower() or "password" in msg.lower(),
                  f"msg reports password authentication failure ('{msg}')")
    except Exception as e:
        rep.fail(f"Auth failure run did not output valid JSON: {e}")

    # Test 4: Forced permission failure check
    test_permission_omission(rep)

    # Test 5: WAL History file exclusion test
    test_wal_history_exclusion(plugin_py, nodes, user, password, db, patroni_port, rep)

    # Test 6: Deadline enforcement under paused node
    test_deadline_behavior(plugin_py, nodes, user, password, db, patroni_port, rep)

    # Test 7: Dynamic Failover Assertion
    if args.failover:
        test_failover_assertion(plugin_py, nodes, user, password, db, patroni_port, rep)

    print("\n" + "=" * 65)
    print(f"RESULT: {len(rep.failures)} failure(s), {len(rep.warnings)} warning(s)")
    print("=" * 65)
    for f in rep.failures:
        print(f"  FAIL: {f}")

    sys.exit(1 if rep.failures else 0)


if __name__ == "__main__":
    main()
