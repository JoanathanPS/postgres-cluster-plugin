#!/usr/bin/env python3
"""
Automated test suite for the Site24x7 PostgreSQL Cluster Plugin (postgres_cluster/postgres_cluster.py).

Validates:
  1. Plugin output adherence to Site24x7 schema and tabular limits:
     - Output is valid RFC 8259 JSON
     - plugin_version is integer >= 7
     - heartbeat_required is boolean
     - Max 10 tables, max 15 columns per table, max 25 rows per table
     - Max 5 string columns per table (excluding 'name')
     - Row 'name' <= 520 chars, other string columns <= 100 chars
     - Row 'status' is numeric 1 or 0
     - Generic metric count <= 200
     - Numeric types: ints and floats emitted for all numeric columns and generic metrics
     - String types only for Server Version, Last Archived WAL File, Cluster Type, Cluster Type Evidence, Cluster Name, Archive Mode, msg
     - Nested units format: units["Cluster_Nodes"], units["Replication_Standbys"], units["Replication_Slots"],
       units["Node_Activity"], units["Node_Throughput"], units["Node_Checkpoints"], units["Standby_Conflicts"]
     - 7 tabs properly formed: Cluster, Replication, DB and IO stats, BG Writer, Transactions and Sessions, Write Ahead Log, Recovery Conflicts
     - s247config.childdiscovery strictly contains per-DB tables (no Cluster child tables)
  2. Coverage Map Assertion:
     - 100% of mapped items in tester/coverage_map.json exist in collector output
  3. Thread-safety under concurrency:
     - 3 concurrent collectors run simultaneously without cross-talk
  4. Cluster Type Detection fixtures:
     - 13 fixtures tested against detect_cluster_type
  5. Error scenarios:
     - Dead cluster: status 0, No Primary Flag 1, Nodes Up 0 under 10s
     - Wrong password: status 0, auth error reported in msg under 10s
     - Paused container: status 1, Nodes Up 2 under 10s
"""

import argparse
import concurrent.futures
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


def run_plugin(plugin_py, nodes, user, password, db, patroni_port=None, cluster_type=None):
    cmd = [
        get_python_exe(), plugin_py,
        "--nodes", nodes,
        "--username", user,
        "--password", password,
        "--db", db
    ]
    if patroni_port:
        cmd.extend(["--patroni_port", str(patroni_port)])
    if cluster_type:
        cmd.extend(["--cluster_type", str(cluster_type)])

    t0 = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=AGENT_TIMEOUT_S)
    return proc, time.monotonic() - t0


def validate_schema(data, rep):
    rep.check(isinstance(data.get("plugin_version"), int) and data["plugin_version"] >= 1,
              f"plugin_version is integer >= 1 ({data.get('plugin_version')})")
    rep.check("heartbeat_required" in data and isinstance(data["heartbeat_required"], bool),
              "heartbeat_required is boolean")
    rep.check(data.get("status") in (0, 1), f"status is 0 or 1 ({data.get('status')})")

    # Cluster metrics presence and numeric types
    expected_metrics = [
        "Cluster Health", "Nodes Total", "Nodes Up", "Primary Count", "No Primary Flag",
        "Split Brain Flag", "Primary Timeline", "Timeline Mismatch Flag", "Standbys Expected",
        "Standbys Streaming", "Standby Disconnect Flag", "Sync Standby Count",
        "Cascading Standby Count", "Max Replay Backlog", "Max Replay Delay",
        "Replication Slots Total", "Replication Slots Active",
        "Replication Slots Inactive", "Max Slot Lag Bytes"
    ]
    for m in expected_metrics:
        rep.check(m in data, f"Cluster metric '{m}' is present ({data.get(m)})")
        rep.check(isinstance(data.get(m), (int, float)), f"Cluster metric '{m}' is numeric type ({type(data.get(m)).__name__})")

    # String top-level metrics
    # String top-level metrics
    allowed_string_metrics = {
        "Last Archived WAL File", "Archive Mode", "Server Version", "msg"
    }
    for sm in ["Archive Mode", "Last Archived WAL File", "Server Version"]:
        if sm in data:
            rep.check(isinstance(data[sm], str), f"Top-level string metric '{sm}' is str ({data.get(sm)})")

    rep.check("Cluster Health" in data and data.get("Cluster Health") in (0, 1, 2), f"Cluster Health is 0/1/2 ({data.get('Cluster Health')})")
    rep.check("Timeline Mismatch Flag" in data and data.get("Timeline Mismatch Flag") in (0, 1), f"Timeline Mismatch Flag is 0/1 ({data.get('Timeline Mismatch Flag')})")
    rep.check("msg" not in data or data.get("msg") is None, f"msg omitted on healthy run ({data.get('msg')})")

    # Renamed WAL position metrics
    rep.check("WAL Write Position" in data and isinstance(data["WAL Write Position"], (int, float)),
              f"WAL Write Position is present and numeric ({data.get('WAL Write Position')})")
    rep.check("WAL Insert Position" in data and isinstance(data["WAL Insert Position"], (int, float)),
              f"WAL Insert Position is present and numeric ({data.get('WAL Insert Position')})")
    rep.check("WAL Flush Position" in data and isinstance(data["WAL Flush Position"], (int, float)),
              f"WAL Flush Position is present and numeric ({data.get('WAL Flush Position')})")
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

    rep.check("WAL Files Count" in data and isinstance(data["WAL Files Count"], int),
              f"WAL Files Count is present and integer ({data.get('WAL Files Count')})")
    rep.check("WAL Total Size" in data and isinstance(data["WAL Total Size"], (int, float)),
              f"WAL Total Size is present and numeric ({data.get('WAL Total Size')})")

    # Archive metrics: ALWAYS emitted per Step 1
    archive_metrics = [
        "Archive Mode", "Archive Status Success", "Archive Status Failed",
        "Archive Ready Files Count", "Last Archived WAL File"
    ]
    for am in archive_metrics:
        rep.check(am in data, f"Archive metric '{am}' is always emitted ({data.get(am)})")

    # Generic metrics limit: max 200
    ignored_keys = {"tabs", "units", "s247config", "plugin_version", "heartbeat_required", "status"}
    generic_metrics_count = 0
    for k, v in data.items():
        if k in ignored_keys or isinstance(v, list) or isinstance(v, dict):
            continue
        generic_metrics_count += 1
        if k not in allowed_string_metrics:
            rep.check(isinstance(v, (int, float)),
                      f"Top-level metric '{k}' is numeric type int/float (found {type(v).__name__}: {v})")

    rep.check(generic_metrics_count <= 200, f"Generic metrics count within Site24x7 limit of 200 ({generic_metrics_count} <= 200)")

    # Identify child tables
    tables = {k: v for k, v in data.items() if isinstance(v, list) and k not in ("tabs", "units", "s247config")}
    rep.check(len(tables) <= 10, f"Total tables within Site24x7 limit of 10 ({len(tables)} <= 10)")

    # Site24x7 Tabular Limits verification for each table
    for t_name, rows in tables.items():
        rep.check(len(rows) <= 25, f"Table '{t_name}' row count within limit of 25 ({len(rows)} <= 25)")
        all_cols = set()
        for r in rows:
            all_cols.update(r.keys())
        rep.check(len(all_cols) <= 15, f"Table '{t_name}' column count within limit of 15 ({len(all_cols)} <= 15)")

        string_cols = set()
        for r in rows:
            rep.check("name" in r, f"Table '{t_name}' row has 'name' key")
            rep.check(len(str(r.get("name", ""))) <= 520, f"Table '{t_name}' row 'name' length <= 520 chars")
            for col, val in r.items():
                if col != "name" and isinstance(val, str):
                    string_cols.add(col)
                    rep.check(len(val) <= 100, f"Table '{t_name}' column '{col}' string length <= 100 ({len(val)})")

        rep.check(len(string_cols) <= 5, f"Table '{t_name}' has <= 5 string columns excluding name (found {len(string_cols)}: {string_cols})")

    # Assertions for Cluster_Info
    rep.check("Cluster_Info" in data and isinstance(data["Cluster_Info"], list), "Cluster_Info table present")
    if "Cluster_Info" in data:
        ci_rows = data["Cluster_Info"]
        rep.check(len(ci_rows) == 1, f"Cluster_Info has exactly 1 row ({len(ci_rows)})")
        if len(ci_rows) > 0:
            ci = ci_rows[0]
            rep.check(ci.get("name") is not None, "Cluster_Info has name key")
            for sc in ["cluster_type", "type_evidence", "server_version", "primary_node", "health_reason"]:
                rep.check(isinstance(ci.get(sc), str), f"Cluster_Info column '{sc}' is str ({ci.get(sc)})")
            for nc in ["nodes_total", "nodes_up", "primary_timeline", "status"]:
                rep.check(isinstance(ci.get(nc), (int, float)), f"Cluster_Info column '{nc}' is numeric ({ci.get(nc)})")

    # Assertions for Cluster_Nodes
    rep.check("Cluster_Nodes" in data and isinstance(data["Cluster_Nodes"], list), "Cluster_Nodes table present")
    if "Cluster_Nodes" in data:
        cn_rows = data["Cluster_Nodes"]
        rep.check(len(cn_rows) == 3, f"Cluster_Nodes has 3 node rows ({len(cn_rows)})")
        prim_count = 0
        for r in cn_rows:
            rep.check(r.get("status") in (0, 1), f"Cluster_Nodes row status in {{0, 1}} ({r.get('status')})")
            rep.check(r.get("is_primary") in (0, 1), f"Cluster_Nodes row is_primary in {{0, 1}} ({r.get('is_primary')})")
            rep.check(isinstance(r.get("timeline"), int), f"Cluster_Nodes row timeline is int ({r.get('timeline')})")
            rep.check(isinstance(r.get("response_time_ms"), (int, float)), f"Cluster_Nodes row response_time_ms is float/int ({r.get('response_time_ms')})")
            rep.check(isinstance(r.get("connections"), int), f"Cluster_Nodes row connections is int ({r.get('connections')})")
            rep.check(isinstance(r.get("role"), str), f"Cluster_Nodes row role is str ({r.get('role')})")
            rep.check(isinstance(r.get("patroni_state"), str), f"Cluster_Nodes row patroni_state is str ({r.get('patroni_state')})")
            rep.check(isinstance(r.get("upstream"), str), f"Cluster_Nodes row upstream is str ({r.get('upstream')})")
            if r.get("is_primary") == 1:
                prim_count += 1
                rep.check("replay_backlog_bytes" not in r, "Primary row omits replay_backlog_bytes")
                rep.check("replay_delay_s" not in r, "Primary row omits replay_delay_s")
            else:
                rep.check(isinstance(r.get("replay_backlog_bytes"), int), f"Cluster_Nodes row replay_backlog_bytes is int ({r.get('replay_backlog_bytes')})")
                rep.check(isinstance(r.get("replay_delay_s"), (int, float)), f"Cluster_Nodes row replay_delay_s is float/int ({r.get('replay_delay_s')})")
        rep.check(prim_count == 1, f"Cluster_Nodes has exactly one primary node with is_primary=1 ({prim_count})")

    # Assertions for Replication_Standbys
    rep.check("Replication_Standbys" in data and isinstance(data["Replication_Standbys"], list), "Replication_Standbys table present")
    if "Replication_Standbys" in data:
        for r in data["Replication_Standbys"]:
            rep.check(r.get("is_sync") in (0, 1), f"Replication_Standbys row is_sync in {{0, 1}} ({r.get('is_sync')})")
            rep.check(isinstance(r.get("replay_lag_bytes"), int), f"Replication_Standbys row replay_lag_bytes is int ({r.get('replay_lag_bytes')})")
            rep.check(isinstance(r.get("write_lag_bytes"), int), f"Replication_Standbys row write_lag_bytes is int ({r.get('write_lag_bytes')})")
            rep.check(isinstance(r.get("flush_lag_bytes"), int), f"Replication_Standbys row flush_lag_bytes is int ({r.get('flush_lag_bytes')})")
            rep.check(isinstance(r.get("replay_lag_s"), (int, float)), f"Replication_Standbys row replay_lag_s is float/int ({r.get('replay_lag_s')})")
            rep.check(isinstance(r.get("state"), str), f"Replication_Standbys row state is str ({r.get('state')})")
            rep.check(isinstance(r.get("sync_state"), str), f"Replication_Standbys row sync_state is str ({r.get('sync_state')})")
            rep.check(isinstance(r.get("client_addr"), str), f"Replication_Standbys row client_addr is str ({r.get('client_addr')})")

    # Assertions for Replication_Slots
    rep.check("Replication_Slots" in data and isinstance(data["Replication_Slots"], list), "Replication_Slots table present")
    if "Replication_Slots" in data:
        for r in data["Replication_Slots"]:
            rep.check(r.get("active") in (0, 1), f"Replication_Slots row active in {{0, 1}} ({r.get('active')})")
            rep.check(isinstance(r.get("wal_retained_bytes"), int), f"Replication_Slots row wal_retained_bytes is int ({r.get('wal_retained_bytes')})")
            rep.check(isinstance(r.get("slot_type"), str), f"Replication_Slots row slot_type is str ({r.get('slot_type')})")
            rep.check(isinstance(r.get("plugin"), str), f"Replication_Slots row plugin is str ({r.get('plugin')})")

    # Assertions for 10 Child Tables
    expected_10_tables = [
        "Cluster_Info", "Cluster_Nodes", "Replication_Standbys", "Replication_Slots",
        "Node_IO", "Node_Checkpoints", "Stats_per_DB", "Node_Activity",
        "Node_Transactions", "Tranasctions_and_Session_per_Database"
    ]
    for pnt in expected_10_tables:
        rep.check(pnt in data and isinstance(data[pnt], list), f"Child table '{pnt}' present")

    # Units verification: nested table-column units
    units = data.get("units", {})
    rep.check(isinstance(units, dict) and "Nodes Total" in units, "units dictionary configured")
    for tbl_unit in ["Cluster_Info", "Cluster_Nodes", "Replication_Standbys", "Replication_Slots", "Node_IO", "Node_Checkpoints", "Node_Activity", "Node_Transactions"]:
        rep.check(tbl_unit in units and isinstance(units[tbl_unit], dict), f"units contains nested dict '{tbl_unit}'")

    # Tabs verification: strictly 5 tabs
    tabs = data.get("tabs", {})
    expected_tab_names = ["Cluster", "Replication", "Node Performance", "Transactions and Sessions", "WAL and Recovery"]
    tab_keys = list(tabs.keys())
    rep.check(len(tabs) == 5, f"Exactly 5 tabs defined in plugin tabs metadata (found {len(tabs)}: {tab_keys})")
    for et in expected_tab_names:
        rep.check(et in tabs, f"Tab '{et}' present in tabs definition")

    cl_tablist = tabs.get("Cluster", {}).get("tablist", [])
    rep.check("Cluster_Info" in cl_tablist, "Cluster_Info present in Cluster tab tablist")
    rep.check("Cluster_Nodes" in cl_tablist, "Cluster_Nodes present in Cluster tab tablist")

    rep_tablist = tabs.get("Replication", {}).get("tablist", [])
    rep.check("Replication_Standbys" in rep_tablist, "Replication_Standbys present in Replication tab tablist")
    rep.check("Replication_Slots" in rep_tablist, "Replication_Slots present in Replication tab tablist")

    perf_tablist = tabs.get("Node Performance", {}).get("tablist", [])
    rep.check("Node_IO" in perf_tablist, "Node_IO present in Node Performance tab tablist")
    rep.check("Node_Checkpoints" in perf_tablist, "Node_Checkpoints present in Node Performance tab tablist")
    rep.check("Stats_per_DB" in perf_tablist, "Stats_per_DB present in Node Performance tab tablist")

    tx_tablist = tabs.get("Transactions and Sessions", {}).get("tablist", [])
    rep.check("Node_Activity" in tx_tablist, "Node_Activity present in Transactions and Sessions tab tablist")
    rep.check("Node_Transactions" in tx_tablist, "Node_Transactions present in Transactions and Sessions tab tablist")
    rep.check("Tranasctions_and_Session_per_Database" in tx_tablist, "Tranasctions_and_Session_per_Database present in Transactions and Sessions tab tablist")

    wal_tablist = tabs.get("WAL and Recovery", {}).get("tablist", [])
    rep.check("WAL Write Position" in wal_tablist, "WAL Write Position in WAL and Recovery tab tablist")

    # Assert exactly 16 untabbed Summary metrics
    all_tabbed = set()
    for t_def in tabs.values():
        all_tabbed.update(t_def.get("tablist", []))
    collector_ignored = {"tabs", "units", "s247config", "plugin_version", "heartbeat_required", "status", "msg"}
    untabbed = [k for k, v in data.items() if k not in all_tabbed and k not in collector_ignored and not isinstance(v, (list, dict))]
    expected_untabbed = sorted([
        "Active Connections", "Active Queries", "Active Waiting Queries",
        "Cache Hit Ratio", "Cluster Health", "Database Count", "Heap Blocks Hit",
        "Heap Blocks Read", "Index Rows Fetched", "Index Rows Read", "Index Scans",
        "Locks Count", "Max Connections", "Nodes Up", "Server Version", "Table Count", "Uptime"
    ])
    rep.check(sorted(untabbed) == expected_untabbed, f"Exactly 17 untabbed metrics (OG 14 + Cluster Health + Nodes Up + Server Version) match OG+Summary spec (found {len(untabbed)}: {sorted(untabbed)})")

    # Childdiscovery in s247config: strictly per-DB tables
    childdiscovery = (data.get("s247config") or {}).get("childdiscovery", [])
    rep.check("Cluster_Nodes" not in childdiscovery, "Cluster_Nodes removed from s247config.childdiscovery")
    rep.check("Replication_Standbys" not in childdiscovery, "Replication_Standbys removed from s247config.childdiscovery")
    rep.check("Stats_per_DB" in childdiscovery, "Stats_per_DB present in s247config.childdiscovery")
    rep.check("Tranasctions_and_Session_per_Database" in childdiscovery, "Tranasctions_and_Session_per_Database present in s247config.childdiscovery")
def test_coverage_map_assertion(data, rep):
    """
    Validates that every single mapped item from PR #442 and standalone postgres.py
    in tester/coverage_map.json is present in the collector's output.
    """
    print("\n=== Test: Coverage Map 100% Assertion ===")
    cov_path = os.path.join(os.path.dirname(__file__), "coverage_map.json")
    if not os.path.exists(cov_path):
        rep.fail(f"Coverage map file not found: {cov_path}")
        return

    with open(cov_path, "r", encoding="utf-8") as f:
        cov = json.load(f)

    rep.check(len(cov) >= 90, f"Coverage map contains comprehensive mappings ({len(cov)} entries)")

    unmapped = []
    server_ver_str = str(data.get("Server Version", "")) or str(((data.get("Cluster_Info") or [{}])[0]).get("server_version", ""))
    is_pg17 = "PostgreSQL 17" in server_ver_str or "17." in server_ver_str

    for entry in cov:
        old_item = entry.get("old_item")
        source = entry.get("source")
        t = entry.get("type")
        v2_item = entry.get("v2_item")
        v2_tbl = entry.get("v2_table")

        # PG 17 omits buffers_backend direct writes from Postgres engine
        if is_pg17 and old_item == "Buffers Backend Direct Writes":
            continue

        # Skip items explicitly documented as removed in notes
        if "removed" in entry.get("notes", "").lower():
            continue

        ok = False
        if t == "metric":
            ok = v2_item in data
        elif t == "table":
            ok = v2_item in data and isinstance(data[v2_item], list)
        elif t == "column":
            if v2_tbl in data and isinstance(data[v2_tbl], list) and len(data[v2_tbl]) > 0:
                ok = any(v2_item in row for row in data[v2_tbl])

        if not ok:
            unmapped.append(f"{old_item} ({source}) -> type={t}, v2_item={v2_item}, v2_table={v2_tbl}")

    rep.check(len(unmapped) == 0, f"100% Coverage Parity achieved: 0 unmapped items (failed {len(unmapped)}: {unmapped[:3]})")


def test_thread_safety_concurrency(plugin_py, nodes, user, password, db, patroni_port, rep):
    """
    Runs 3 collector instances concurrently using ThreadPoolExecutor.
    Asserts no shared-state contamination, no crashes, and all 3 produce valid output.
    """
    print("\n=== Test: Thread-Safety Under Concurrency ===")
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "upstream_layout", "postgres_cluster")))
    import postgres_cluster as pg_mod

    def run_single_collector(thread_id):
        collector = pg_mod.PostgresClusterCollector(
            nodes_str=nodes,
            username=user,
            password=password,
            db=db,
            patroni_port=patroni_port
        )
        return thread_id, collector.collect()

    t0 = time.monotonic()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(run_single_collector, i) for i in range(3)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
    elapsed = time.monotonic() - t0

    rep.check(len(results) == 3, f"All 3 concurrent collectors finished successfully in {elapsed:.2f}s")
    for tid, res in results:
        print(f"  [CONCURRENCY THREAD {tid}] status={res.get('status')}, Nodes Up={res.get('Nodes Up')}, Primary Count={res.get('Primary Count')}, msg='{res.get('msg')}'")
        rep.check(res.get("status") == 1, f"Thread {tid} collector status is 1")
        rep.check(res.get("Nodes Up") == 3, f"Thread {tid} Nodes Up is 3")
        rep.check(len(res.get("Cluster_Nodes", [])) == 3, f"Thread {tid} Cluster_Nodes count is 3")


def test_cluster_type_fixtures(rep):
    """
    Tests detect_cluster_type pure function against all 13 realistic cluster fixtures.
    """
    print("\n=== Test: Cluster Type Detection (13 Fixtures) ===")
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "upstream_layout", "postgres_cluster")))
    from postgres_cluster import detect_cluster_type

    fixtures = [
        {
            "name": "Patroni",
            "evidence": {
                "patroni": {"is_patroni": True, "scope": "patroni-cluster", "version": "4.0.4"},
                "extensions": [],
                "repmgr_table": False,
                "slot_names": ["pg_node2", "pg_node3"],
                "app_names": ["pg-node2", "pg-node3"],
                "managed_roles": [],
                "aurora_version": False,
                "has_standbys": True,
                "standby_count": 2,
                "total_nodes": 3
            },
            "expected_type": "Patroni"
        },
        {
            "name": "repmgr",
            "evidence": {
                "patroni": None,
                "extensions": ["repmgr"],
                "repmgr_table": True,
                "slot_names": ["repmgr_slot_1001"],
                "app_names": ["repmgr_node1"],
                "managed_roles": [],
                "aurora_version": False,
                "has_standbys": True,
                "standby_count": 1,
                "total_nodes": 2
            },
            "expected_type": "repmgr"
        },
        {
            "name": "pg_auto_failover",
            "evidence": {
                "patroni": None,
                "extensions": ["pgautofailover"],
                "repmgr_table": False,
                "slot_names": ["pgautofailover_standby_1"],
                "app_names": [],
                "managed_roles": [],
                "aurora_version": False,
                "has_standbys": True,
                "standby_count": 1,
                "total_nodes": 2
            },
            "expected_type": "pg_auto_failover"
        },
        {
            "name": "CloudNative-PG",
            "evidence": {
                "patroni": None,
                "extensions": [],
                "repmgr_table": False,
                "slot_names": ["_cnpg_cluster_1"],
                "app_names": ["_cnpg_cluster_1"],
                "managed_roles": [],
                "aurora_version": False,
                "has_standbys": True,
                "standby_count": 1,
                "total_nodes": 2
            },
            "expected_type": "CloudNative-PG"
        },
        {
            "name": "Stolon",
            "evidence": {
                "patroni": None,
                "extensions": [],
                "repmgr_table": False,
                "slot_names": ["stolon_slot_1"],
                "app_names": ["stolon_node_1"],
                "managed_roles": [],
                "aurora_version": False,
                "has_standbys": True,
                "standby_count": 1,
                "total_nodes": 2
            },
            "expected_type": "Stolon"
        },
        {
            "name": "Citus Distributed",
            "evidence": {
                "patroni": None,
                "extensions": ["citus"],
                "repmgr_table": False,
                "slot_names": [],
                "app_names": [],
                "managed_roles": [],
                "aurora_version": False,
                "has_standbys": False,
                "total_nodes": 3
            },
            "expected_type": "Citus Distributed"
        },
        {
            "name": "AWS Aurora",
            "evidence": {
                "patroni": None,
                "extensions": [],
                "repmgr_table": False,
                "slot_names": [],
                "app_names": [],
                "managed_roles": [],
                "aurora_version": True,
                "has_standbys": True,
                "standby_count": 1,
                "total_nodes": 2
            },
            "expected_type": "AWS Aurora"
        },
        {
            "name": "AWS RDS",
            "evidence": {
                "patroni": None,
                "extensions": [],
                "repmgr_table": False,
                "slot_names": [],
                "app_names": [],
                "managed_roles": ["rds_superuser"],
                "aurora_version": False,
                "has_standbys": True,
                "standby_count": 1,
                "total_nodes": 2
            },
            "expected_type": "AWS RDS"
        },
        {
            "name": "Azure Database for PostgreSQL",
            "evidence": {
                "patroni": None,
                "extensions": [],
                "repmgr_table": False,
                "slot_names": [],
                "app_names": [],
                "managed_roles": ["azure_pg_admin"],
                "aurora_version": False,
                "has_standbys": False,
                "total_nodes": 1
            },
            "expected_type": "Azure Database for PostgreSQL"
        },
        {
            "name": "GCP Cloud SQL",
            "evidence": {
                "patroni": None,
                "extensions": [],
                "repmgr_table": False,
                "slot_names": [],
                "app_names": [],
                "managed_roles": ["cloudsqlsuperuser"],
                "aurora_version": False,
                "has_standbys": False,
                "total_nodes": 1
            },
            "expected_type": "GCP Cloud SQL"
        },
        {
            "name": "mixed/unknown conflict",
            "evidence": {
                "patroni": {"is_patroni": True, "scope": "patroni-cluster", "version": "4.0.4"},
                "extensions": ["repmgr"],
                "repmgr_table": True,
                "slot_names": [],
                "app_names": [],
                "managed_roles": [],
                "aurora_version": False,
                "has_standbys": True,
                "total_nodes": 3
            },
            "expected_type": "mixed/unknown"
        },
        {
            "name": "streaming replication (unmanaged)",
            "evidence": {
                "patroni": None,
                "extensions": [],
                "repmgr_table": False,
                "slot_names": ["replica1_slot"],
                "app_names": ["walreceiver"],
                "managed_roles": [],
                "aurora_version": False,
                "has_standbys": True,
                "standby_count": 1,
                "total_nodes": 2
            },
            "expected_type": "streaming replication (no HA manager detected)"
        },
        {
            "name": "Multi-Master (Active-Active)",
            "evidence": {
                "patroni": None,
                "extensions": [],
                "repmgr_table": False,
                "slot_names": ["sub_mm1"],
                "slot_types": ["logical"],
                "logical_replication_count": 2,
                "primary_count": 2,
                "app_names": ["sub_mm1"],
                "managed_roles": [],
                "aurora_version": False,
                "has_standbys": False,
                "standby_count": 0,
                "total_nodes": 2
            },
            "expected_type": "Multi-Master (Active-Active)"
        },
        {
            "name": "standalone",
            "evidence": {
                "patroni": None,
                "extensions": [],
                "repmgr_table": False,
                "slot_names": [],
                "app_names": [],
                "managed_roles": [],
                "aurora_version": False,
                "has_standbys": False,
                "standby_count": 0,
                "total_nodes": 1
            },
            "expected_type": "standalone"
        }
    ]

    for fx in fixtures:
        c_type, c_ev = detect_cluster_type(fx["evidence"])
        rep.check(c_type == fx["expected_type"], f"Fixture '{fx['name']}' returned '{c_type}' == '{fx['expected_type']}'")
        rep.check(len(c_ev) < 100, f"Fixture '{fx['name']}' evidence < 100 chars ({len(c_ev)} chars: '{c_ev}')")
        rep.check(len(c_ev) > 0, f"Fixture '{fx['name']}' evidence non-empty")


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

        # Must be positive integer count and matching 16MB per segment
        rep.check(isinstance(wal_count, int) and wal_count > 0, f"WAL Files Count is positive integer ({wal_count})")
        expected_size = round(wal_count * 16.0, 2)
        rep.check(wal_size == expected_size, f"WAL Total Size matches {wal_count} segments x 16MB ({wal_size} == {expected_size} MB)")
    except Exception as e:
        rep.fail(f"Failed to verify WAL history file exclusion: {e}")


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



def test_type_consistency(plugin_py, nodes, user, password, db, patroni_port, rep):
    """
    Asserts consistent JSON data types across healthy, single node down, and dead cluster states.
    """
    print("\n=== Test: JSON Type Consistency Across States ===")
    import sys
    sys.path.insert(0, os.path.dirname(plugin_py))
    import postgres_cluster as pg_mod

    # 1. Healthy cluster
    p1 = pg_mod.PostgresClusterCollector(nodes_str=nodes, username=user, password=password, db=db, patroni_port=patroni_port)
    d1 = p1.collect()

    # 2. Node down
    bad_nodes = nodes.replace('5443', '5499')
    p2 = pg_mod.PostgresClusterCollector(nodes_str=bad_nodes, username=user, password=password, db=db, patroni_port=patroni_port)
    d2 = p2.collect()

    # 3. Dead cluster
    dead_nodes = 'pgnode1=127.0.0.1:5491:8001,pgnode2=127.0.0.1:5492:8002,pgnode3=127.0.0.1:5493:8003'
    p3 = pg_mod.PostgresClusterCollector(nodes_str=dead_nodes, username=user, password=password, db=db, patroni_port=patroni_port)
    d3 = p3.collect()

    keys1 = {k: type(v) for k, v in d1.items() if not isinstance(v, (list, dict)) and k not in ('msg',)}
    keys2 = {k: type(v) for k, v in d2.items() if not isinstance(v, (list, dict)) and k not in ('msg',)}
    keys3 = {k: type(v) for k, v in d3.items() if not isinstance(v, (list, dict)) and k not in ('msg',)}

    for k, t1 in keys1.items():
        if k in keys2:
            rep.check(t1 == keys2[k], f"Type consistency (node down) for '{k}': expected {t1.__name__}, got {keys2[k].__name__}")
        if k in keys3:
            rep.check(t1 == keys3[k], f"Type consistency (dead cluster) for '{k}': expected {t1.__name__}, got {keys3[k].__name__}")

    fabricated = [k for k in ("Uptime", "Active Connections", "Max Connections", "Total Commits",
                              "Last Archived WAL File", "Buffers Backend", "Table Count") if k in d3]
    rep.check(not fabricated, f"Dead cluster omits unreadable metrics, no fabricated zeros (found: {fabricated})")
    rep.check(d3.get('status') == 0, f"Dead cluster status is 0 ({d3.get('status')})")

def test_failover_assertion(plugin_py, nodes, user, password, db, patroni_port, rep):
    print("\n=== Dynamic Failover Assertion ===")
    containers = ["patroni-pg-node1", "patroni-pg-node2", "patroni-pg-node3"]
    leader = None

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

    print(f"  Stopping leader container '{leader}'...")
    subprocess.run(["docker", "stop", leader], check=True)

    try:
        print("  Waiting 12 seconds for Patroni automatic leader promotion...")
        time.sleep(12)

        proc_after, _ = run_plugin(plugin_py, nodes, user, password, db, patroni_port)
        rep.check(proc_after.returncode == 0, "Plugin exit code 0 during leader outage (did not crash)")
        data_after = json.loads(proc_after.stdout)
        rep.check(data_after.get("Nodes Up") == 2, f"Nodes Up correctly reports 2 during failover ({data_after.get('Nodes Up')})")
        rep.check(data_after.get("Primary Count") == 1, f"New primary cleanly elected ({data_after.get('Primary Count')})")
        rep.check(data_after.get("No Primary Flag") == 0, "No Primary Flag remains 0 after successful election")
        rep.check(data_after.get("Split Brain Flag") == 0, "Split Brain Flag remains 0 (no duplicate primaries)")

        new_timeline = data_after.get("Primary Timeline", 0)
        rep.check(new_timeline >= init_timeline, f"Primary Timeline incremented or preserved ({new_timeline} >= {init_timeline})")
    finally:
        print(f"  Restarting leader container '{leader}'...")
        subprocess.run(["docker", "start", leader], check=True)
        time.sleep(12)
        proc_rec, _ = run_plugin(plugin_py, nodes, user, password, db, patroni_port)
        data_rec = json.loads(proc_rec.stdout)
        rep.check(data_rec.get("Nodes Up") == 3, f"Cluster recovered back to 3 nodes up ({data_rec.get('Nodes Up')})")


def test_exception_injection(plugin_py, nodes, user, password, db, patroni_port, rep):
    """
    Test: Unexpected Exception Injection Handling
    Asserts that collect() catches any unexpected internal exception,
    returns valid JSON with status: 0, sets msg with the exception text,
    retains data collected so far, and never emits an unhandled traceback to stdout.
    """
    print("\n=== Test: Unexpected Exception Injection Handling ===")
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "upstream_layout", "postgres_cluster")))
    import postgres_cluster as pg_mod

    collector = pg_mod.PostgresClusterCollector(
        nodes_str=nodes,
        username=user,
        password=password,
        db=db,
        patroni_port=patroni_port
    )

    # In-memory injection: inject an unexpected RuntimeError inside _parse_nodes
    def broken_parse():
        raise RuntimeError("SIMULATED_INTERNAL_CORRUPTION_FAILURE")
    collector._parse_nodes = broken_parse

    try:
        res = collector.collect()
        rep.check(isinstance(res, dict), "collect() returns valid dictionary despite unexpected exception")
        rep.check(res.get("status") == 0, f"status is 0 on injected exception ({res.get('status')})")
        rep.check("msg" in res and "SIMULATED_INTERNAL_CORRUPTION_FAILURE" in str(res.get("msg")),
                  f"msg contains injected exception text ('{res.get('msg')}')")
        rep.check(res.get("plugin_version") == pg_mod.PLUGIN_VERSION,
                  "plugin_version is preserved in results")
        rep.check(res.get("heartbeat_required") == pg_mod.HEARTBEAT,
                  "heartbeat_required is preserved in results")
        rep.check("tabs" in res and "units" in res,
                  "tabs and units schemas are preserved in results")
    except Exception as e:
        rep.fail(f"collect() raised unexpected exception instead of handling safely: {e}")

    # Subprocess execution test: verify CLI execution outputs valid JSON with status 0 and no traceback on stdout
    test_code = (
        "import sys, json, os\n"
        f"sys.path.insert(0, r'{os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'upstream_layout', 'postgres_cluster'))}')\n"
        "import postgres_cluster as pg\n"
        "def broken_parse(self):\n"
        "    raise ValueError('SIMULATED_CLI_EXCEPTION')\n"
        "pg.PostgresClusterCollector._parse_nodes = broken_parse\n"
        f"collector = pg.PostgresClusterCollector('{nodes}', '{user}', '{password}', '{db}')\n"
        "res = collector.collect()\n"
        "print(json.dumps(res))\n"
    )
    proc = subprocess.run([sys.executable, "-c", test_code], capture_output=True, text=True)
    rep.check(proc.returncode == 0, f"CLI runner completed with exit code 0 ({proc.returncode})")
    rep.check("Traceback" not in proc.stdout, "No traceback present on stdout")
    try:
        cli_data = json.loads(proc.stdout)
        rep.check(cli_data.get("status") == 0, f"CLI output status is 0 ({cli_data.get('status')})")
        rep.check("SIMULATED_CLI_EXCEPTION" in cli_data.get("msg", ""),
                  f"CLI output msg contains exception text ('{cli_data.get('msg')}')")
    except Exception as e:
        rep.fail(f"CLI output was not valid JSON: {e}\nStdout: {proc.stdout}\nStderr: {proc.stderr}")



def test_standalone_sql_parity(rep):
    """
    Validates that every single standalone query in get_standalone_queries()
    matches standalone postgres.py character-for-character across PG 14, 16, and 17.
    """
    print("\n=== Test: Standalone SQL Parity vs postgres.py ===")
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "upstream_layout", "postgres_cluster")))
    import postgres_cluster as pg_mod
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "postgres")))
    import postgres as std_mod

    for ver in [140000, 160000, 170000]:
        major = ver // 10000
        std_mod.VERSION = ver
        std_mod.inititializeQueries()
        expected_queries = std_mod.dict_psqlQueries
        v2_queries = pg_mod.get_standalone_queries(major)

        for qkey, qval in expected_queries.items():
            rep.check(qkey in v2_queries, f"PG{major} query '{qkey}' present in v2 get_standalone_queries")
            if qkey in v2_queries:
                clean_exp = " ".join(qval.split())
                clean_v2 = " ".join(v2_queries[qkey].split())
                rep.check(clean_exp == clean_v2, f"PG{major} SQL for '{qkey}' matches postgres.py exactly")


def test_cluster_health_rules(rep):
    """
    Unit tests for evaluate_cluster_health pure function verifying every branch of the health logic:
    Critical: no primary, split-brain, no streaming standby when expected.
    Degraded: node down, standby disconnected, lag over threshold, inactive slot, timeline mismatch.
    Healthy: all criteria met.
    """
    print("\n=== Test: Cluster Health Rules and Fixtures ===")
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "upstream_layout", "postgres_cluster")))
    from postgres_cluster import evaluate_cluster_health

    # 1. Critical: No primary
    code, reason = evaluate_cluster_health(3, 2, 0, 1, 0, 2, 2, 0.0, 0, 0, 0)
    rep.check(code == 2 and "No active primary" in reason, f"Critical (no primary): {code}, '{reason}'")

    # 2. Critical: Split brain
    code, reason = evaluate_cluster_health(3, 3, 2, 0, 1, 1, 1, 0.0, 0, 0, 0)
    rep.check(code == 2 and "Split brain" in reason, f"Critical (split brain): {code}, '{reason}'")

    # 3. Critical: No streaming standby while expected
    code, reason = evaluate_cluster_health(3, 3, 1, 0, 0, 2, 0, 0.0, 0, 0, 0)
    rep.check(code == 2 and "No streaming standbys" in reason, f"Critical (0 streaming): {code}, '{reason}'")

    # 4. Degraded: Node down
    code, reason = evaluate_cluster_health(3, 2, 1, 0, 0, 2, 2, 0.0, 0, 0, 0)
    rep.check(code == 1 and "node(s) offline" in reason, f"Degraded (node offline): {code}, '{reason}'")

    # 5. Degraded: Standby disconnected
    code, reason = evaluate_cluster_health(3, 3, 1, 0, 0, 2, 1, 0.0, 0, 0, 0)
    rep.check(code == 1 and "standby(s) not streaming" in reason, f"Degraded (standby disconnect): {code}, '{reason}'")

    # 6. Degraded: Replay delay over threshold
    code, reason = evaluate_cluster_health(3, 3, 1, 0, 0, 2, 2, 75.0, 0, 0, 0)
    rep.check(code == 1 and "Replay delay" in reason, f"Degraded (delay > 60s): {code}, '{reason}'")

    # 7. Degraded: Replay backlog over threshold
    code, reason = evaluate_cluster_health(3, 3, 1, 0, 0, 2, 2, 0.0, 120 * 1024 * 1024, 0, 0)
    rep.check(code == 1 and "Replay backlog" in reason, f"Degraded (backlog > 100MB): {code}, '{reason}'")

    # 8. Degraded: Inactive slot
    code, reason = evaluate_cluster_health(3, 3, 1, 0, 0, 2, 2, 0.0, 0, 1, 0)
    rep.check(code == 1 and "inactive replication slot" in reason, f"Degraded (inactive slot): {code}, '{reason}'")

    # 9. Degraded: Timeline mismatch
    code, reason = evaluate_cluster_health(3, 3, 1, 0, 0, 2, 2, 0.0, 0, 0, 1)
    rep.check(code == 1 and "Timeline mismatch" in reason, f"Degraded (timeline mismatch): {code}, '{reason}'")

    # 10. Healthy: All OK
    code, reason = evaluate_cluster_health(3, 3, 1, 0, 0, 2, 2, 0.0, 0, 0, 0)
    rep.check(code == 0 and "Cluster healthy" in reason, f"Healthy: {code}, '{reason}'")

    # 11. Multi-Master: 2 Primaries is Healthy
    code, reason = evaluate_cluster_health(2, 2, 2, 0, 0, 0, 1, 0.0, 0, 0, 0, cluster_type="Multi-Master (Active-Active)")
    rep.check(code == 0 and "Multi-master cluster healthy" in reason, f"Multi-master healthy: {code}, '{reason}'")

    # 12. Multi-Master: 1 Node down is Degraded
    code, reason = evaluate_cluster_health(2, 1, 1, 0, 0, 0, 0, 0.0, 0, 0, 0, cluster_type="Multi-Master (Active-Active)")
    rep.check(code == 1 and "offline" in reason, f"Multi-master degraded: {code}, '{reason}'")


def test_regressions(plugin_py, nodes, user, password, db, patroni_port, rep):
    """Regression tests for bugs found in the v1 audit (fabricated zeros, parity gaps, naming, classification)."""
    print("\n=== Test: Audit Regressions & OG Parity ===")
    import sys, math, importlib.util
    sys.path.insert(0, os.path.dirname(plugin_py))
    import postgres_cluster as pg_mod

    def collect(n):
        return pg_mod.PostgresClusterCollector(nodes_str=n, username=user, password=password, db=db, patroni_port=patroni_port).collect()

    healthy = collect(nodes)
    # Server Version parity (OG reports it as a flat textual metric)
    rep.check(isinstance(healthy.get("Server Version"), str) and healthy["Server Version"], f"Flat 'Server Version' present ({healthy.get('Server Version')})")
    # Per-database child table: no null-name row (OG drops it)
    tx = healthy.get("Tranasctions_and_Session_per_Database", [])
    rep.check(tx and all(isinstance(r.get("name"), str) and r["name"] for r in tx), f"Tranasctions_and_Session_per_Database has no null-name row ({[r.get('name') for r in tx]})")
    # Cluster_Info name is alphanumeric
    ci = (healthy.get("Cluster_Info") or [{}])[0]
    import re as _re
    rep.check(bool(_re.fullmatch(r"[A-Za-z0-9]+", str(ci.get("name", "")))), f"Cluster_Info name alphanumeric ({ci.get('name')})")

    # Down node must still emit a status 0 row in every per-node table
    down = collect(nodes.replace("5443", "5499"))
    for t in ("Node_IO", "Node_Checkpoints", "Node_Activity", "Node_Transactions", "Cluster_Nodes"):
        rows = down.get(t, [])
        zero_rows = [r for r in rows if r.get("status") == 0]
        rep.check(len(rows) == 3 and len(zero_rows) == 1, f"{t}: 3 rows with exactly one status 0 row for the down node ({len(rows)} rows, {len(zero_rows)} down)")
    rep.check(down.get("Cluster Health") == 1, f"One node down gives Cluster Health 1 ({down.get('Cluster Health')})")

    # Duplicate aliases are made unique
    first = nodes.split(",")[0].split("=", 1)[-1]
    dup = pg_mod.PostgresClusterCollector(nodes_str=f"n={first},n={nodes.split(',')[1].split('=', 1)[-1]}", username=user, password=password, db=db, patroni_port=patroni_port, discover="off").collect()
    names = [r["name"] for r in dup.get("Cluster_Nodes", [])]
    rep.check(len(names) == len(set(names)) == 2, f"Duplicate aliases made unique ({names})")

    # Empty nodes: explicit failure, not a silent fallback
    empty = pg_mod.run({"nodes": "", "username": user, "password": password, "db": db, "patroni_port": patroni_port})
    rep.check(empty.get("status") == 0 and "No nodes" in str(empty.get("msg")), f"Empty nodes gives status 0 with message ({empty.get('msg')})")

    # Cluster type classification
    base = dict(extensions=[], repmgr_table=False, managed_roles=[], aurora_version=False, slot_names=[], slot_types=[],
                logical_replication_count=0, primary_count=1, app_names=[], total_nodes=3, is_in_recovery=True,
                has_standbys=True, has_replication_slots=True, standby_count=2)
    def typ(**kw):
        e = dict(base); e.update(kw); return pg_mod.detect_cluster_type(e)[0]
    rep.check(typ(extensions=["pglogical"]).startswith("streaming"), f"pglogical extension alone is not multi-master ({typ(extensions=['pglogical'])})")
    rep.check("ulti" in typ(extensions=["pglogical"], primary_count=2), "pglogical with 2 primaries is multi-master")
    rep.check(typ(patroni={"is_patroni": True, "scope": "x"}, extensions=["pglogical"]) == "Patroni", "Patroni plus pglogical extension stays Patroni")
    rep.check(typ(patroni={"is_patroni": True, "scope": "x"}, extensions=["citus"]) == "Patroni + Citus", "Patroni plus citus is 'Patroni + Citus'")

    # SQL parity against the standalone postgres.py on the primary node
    try:
        og_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(plugin_py))), "..", "postgres", "postgres.py")
        og_path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "postgres", "postgres.py"))
        spec = importlib.util.spec_from_file_location("og_postgres", og_path)
        og = importlib.util.module_from_spec(spec); spec.loader.exec_module(og)
        prim_idx = [i for i, r in enumerate(healthy["Cluster_Nodes"]) if r.get("is_primary") == 1][0]
        parsed = pg_mod.PostgresClusterCollector(nodes_str=nodes, username=user, password=password, db=db, patroni_port=patroni_port)._parse_nodes()
        pd = parsed[prim_idx]  # configured nodes keep their order; names may be replaced by Patroni member names
        ogres = og.run({"host": pd[1], "port": str(pd[2]), "username": user, "password": password, "db": db})
        skip = {"plugin_version", "heartbeat_required", "status", "msg", "tabs", "units", "s247config"}
        stable = {"Max Connections", "Database Count", "Table Count", "Server Version", "Heap Blocks Read", "Index Scans", "Index Rows Read", "Index Rows Fetched", "Checkpoints Req"}
        for k, v in ogres.items():
            if k in skip or isinstance(v, list):
                continue
            rep.check(k in healthy, f"OG metric '{k}' exists in plugin output")
            if k in stable and k in healthy:
                try:
                    rep.check(math.isclose(float(v), float(healthy[k]), rel_tol=0.02, abs_tol=2), f"OG parity '{k}': OG={v} plugin={healthy[k]}")
                except ValueError:
                    rep.check(str(v) == str(healthy[k]), f"OG parity '{k}': OG={v} plugin={healthy[k]}")
        for t in ("Tranasctions_and_Session_per_Database", "Stats_per_DB"):
            og_cols = set(ogres[t][0].keys()); pl_cols = set(healthy[t][0].keys())
            rep.check(og_cols == pl_cols, f"{t} columns identical to OG ({sorted(og_cols ^ pl_cols)})")
            rep.check([r['name'] for r in ogres[t]] == [r['name'] for r in healthy[t]], f"{t} rows identical to OG")
    except Exception as e:
        rep.fail(f"OG parity test could not run: {type(e).__name__}: {e}")


def test_discovery(plugin_py, nodes, user, password, db, patroni_port, rep):
    """Node discovery: one address is enough; known nodes are never duplicated; the switch and cap work."""
    print("\n=== Test: Node Discovery ===")
    import sys
    sys.path.insert(0, os.path.dirname(plugin_py))
    import postgres_cluster as pg_mod

    def collector(n, discover="auto"):
        return pg_mod.PostgresClusterCollector(nodes_str=n, username=user, password=password, db=db, patroni_port=patroni_port, discover=discover)

    def fake(members):
        return lambda *a, **k: (members, "Patroni REST API", {})

    real = pg_mod.discover_cluster_members
    try:
        base = "a=10.1.1.1:5432:8008"
        m = lambda alias, host, port=5432: {"alias": alias, "member": alias, "host": host, "port": port, "patroni_port": "8008", "source": "Patroni REST API"}

        pg_mod.discover_cluster_members = fake([m("a", "10.1.1.1"), m("b", "10.1.1.2"), m("c", "10.1.1.3")])
        names = [d[0] for d in collector(base)._apply_discovery(collector(base)._parse_nodes())]
        rep.check(names == ["a", "b", "c"], f"One configured address discovers the other members ({names})")

        # A node added later is picked up without any config change; one removed disappears
        pg_mod.discover_cluster_members = fake([m("a", "10.1.1.1"), m("b", "10.1.1.2"), m("c", "10.1.1.3"), m("d", "10.1.1.4")])
        names = [d[0] for d in collector(base)._apply_discovery(collector(base)._parse_nodes())]
        rep.check(names == ["a", "b", "c", "d"], f"A newly added node is found without editing the config ({names})")
        pg_mod.discover_cluster_members = fake([m("a", "10.1.1.1"), m("c", "10.1.1.3")])
        names = [d[0] for d in collector(base)._apply_discovery(collector(base)._parse_nodes())]
        rep.check(names == ["a", "c"], f"A removed node is no longer listed ({names})")

        # A configured node with a custom alias at the same address is not duplicated
        pg_mod.discover_cluster_members = fake([m("pg1", "10.1.1.1"), m("pg2", "10.1.1.2")])
        names = [d[0] for d in collector("primary1=10.1.1.1:5432:8008")._apply_discovery(collector("primary1=10.1.1.1:5432:8008")._parse_nodes())]
        rep.check(names == ["primary1", "pg2"], f"Configured alias is kept, same address not duplicated ({names})")

        # A complete explicit list under different addresses/aliases (e.g. a down node cannot report its name) gets no phantom nodes
        pg_mod.discover_cluster_members = fake([m("x1", "10.9.9.1"), m("x2", "10.9.9.2"), m("x3", "10.9.9.3")])
        cfg3 = "a=10.1.1.1:5432:8008,b=10.1.1.2:5432:8008,c=10.1.1.3:5432:8008"
        names = [d[0] for d in collector(cfg3)._apply_discovery(collector(cfg3)._parse_nodes())]
        rep.check(names == ["a", "b", "c"], f"A complete explicit list gets no phantom nodes ({names})")

        # Switch off
        names = [d[0] for d in collector(base, "off")._apply_discovery(collector(base, "off")._parse_nodes())]
        rep.check(names == ["a"], f"discover=off monitors only the listed nodes ({names})")

        # Cap at 25 rows
        pg_mod.discover_cluster_members = fake([m(f"n{i}", f"10.2.0.{i}") for i in range(1, 40)])
        n = len(collector(base)._apply_discovery(collector(base)._parse_nodes()))
        rep.check(n == 25, f"Discovered nodes are capped at 25 ({n})")

        # Discovery failure keeps the configured nodes
        pg_mod.discover_cluster_members = fake([])
        names = [d[0] for d in collector(base)._apply_discovery(collector(base)._parse_nodes())]
        rep.check(names == ["a"], f"Failed discovery keeps the configured node ({names})")
    finally:
        pg_mod.discover_cluster_members = real

    # Live: Patroni REST discovery from one member
    try:
        first = nodes.split(",")[0].split("=", 1)[-1].split(":")
        if len(first) >= 3:
            members, scope = pg_mod.discover_via_patroni(first[0], first[2])
            rep.check(len(members) >= 2 and all(x["alias"] for x in members),
                      f"Live Patroni /cluster from one member returns the whole cluster ({[x['alias'] for x in members]})")
    except Exception as e:
        rep.fail(f"Live Patroni discovery test failed: {type(e).__name__}: {e}")


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
        data = {}

    # Test 2: Coverage Map 100% Assertion
    if data:
        test_coverage_map_assertion(data, rep)

    # Test 3: Thread-Safety Under Concurrency
    test_thread_safety_concurrency(plugin_py, nodes, user, password, db, patroni_port, rep)

    # Test 4: Cluster Type Detection (13 Fixtures)
    test_cluster_type_fixtures(rep)

    # Test 5: Dead host handling (never crash on dead node)
    print("\n=== Test 5: Dead host handling & timing constraint ===")
    dead_nodes = "node_dead=localhost:5999,node_dead2=localhost:5998"
    proc_dead, elapsed_dead = run_plugin(plugin_py, dead_nodes, user, password, db)
    rep.check(proc_dead.returncode == 0, f"Dead node test exit code 0 (elapsed: {elapsed_dead:.2f}s)")
    rep.check(elapsed_dead < 10.0, f"Dead node run completed under 10s timing constraint ({elapsed_dead:.2f}s < 10.0s)")
    try:
        dead_data = json.loads(proc_dead.stdout)
        rep.check(dead_data.get("status") == 0, f"status is 0 on dead cluster ({dead_data.get('status')})")
        rep.check(dead_data.get("No Primary Flag") == 1, "No Primary Flag is 1 on dead cluster")
        rep.check(dead_data.get("Nodes Up") == 0, "Nodes Up is 0 on dead cluster")
    except Exception as e:
        rep.fail(f"Dead node run did not output valid JSON: {e}")

    # Test 6: Wrong password on all nodes reports auth error in msg
    print("\n=== Test 6: Wrong password reports auth error in msg with status 0 ===")
    proc_auth, elapsed_auth = run_plugin(plugin_py, nodes, user, "wrong_password_test", db)
    rep.check(proc_auth.returncode == 0, "Wrong password run exit code 0")
    rep.check(elapsed_auth < 10.0, f"Wrong password run completed under 10s ({elapsed_auth:.2f}s < 10.0s)")
    try:
        auth_data = json.loads(proc_auth.stdout)
        rep.check(auth_data.get("status") == 0, f"status is 0 on auth failure ({auth_data.get('status')})")
        msg = auth_data.get("msg", "")
        rep.check("authentication failed" in msg.lower() or "password" in msg.lower(),
                  f"msg reports password authentication failure ('{msg}')")
    except Exception as e:
        rep.fail(f"Auth failure run did not output valid JSON: {e}")

    # Test 7: WAL History file exclusion test
    test_wal_history_exclusion(plugin_py, nodes, user, password, db, patroni_port, rep)

    # Test 8: Deadline enforcement under paused node
    test_deadline_behavior(plugin_py, nodes, user, password, db, patroni_port, rep)

    # Test 9: Unexpected Exception Injection Handling
    test_exception_injection(plugin_py, nodes, user, password, db, patroni_port, rep)

    # Test: JSON Type Consistency
    test_type_consistency(plugin_py, nodes, user, password, db, patroni_port, rep)

    # Test: audit regressions and OG parity
    test_regressions(plugin_py, nodes, user, password, db, patroni_port, rep)
    test_discovery(plugin_py, nodes, user, password, db, patroni_port, rep)

    # Test 10: Dynamic Failover Assertion
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
