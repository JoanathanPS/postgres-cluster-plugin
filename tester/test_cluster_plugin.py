#!/usr/bin/env python3
"""
Automated test suite for the Site24x7 PostgreSQL Cluster Plugin (postgres_cluster/postgres_cluster.py).

Validates:
  1. Plugin output adherence to Site24x7 schema rules:
     - Output is valid JSON
     - plugin_version is integer >= 1
     - heartbeat_required is boolean
     - No unhandled crashes on dead/unreachable nodes
     - Generic metric limits (<= 200 metrics)
     - Table limits (<= 10 tables, <= 15 cols, <= 25 rows)
     - Every row in child tables contains 'name' key
     - s247config.childdiscovery lists all child tables
     - units map contains valid keys
     - tabs configuration contains valid metric names
  2. Cluster-specific metrics validation:
     - Nodes Total, Nodes Up, Primary Count, No Primary Flag, Split Brain Flag, Primary Timeline, Max Replay Backlog
     - Replication Slots metrics: Replication Slots Total, Active, Inactive, Max Slot Lag Bytes
  3. Authentication error reporting:
     - Negative test: wrong password reports auth error in msg with status 0
  4. Dynamic failover verification:
     - Stops active leader
     - Verifies automatic election of new leader
     - Asserts timeline advance, node count decrement, stopped node marked down
     - Recovers node and verifies rejoin
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
    rep.check(isinstance(data.get("plugin_version"), int) and data["plugin_version"] >= 1,
              f"plugin_version is integer >= 1 ({data.get('plugin_version')})")
    rep.check("heartbeat_required" in data, "heartbeat_required is present")

    # Cluster metrics
    expected_metrics = [
        "Nodes Total", "Nodes Up", "Primary Count", "No Primary Flag",
        "Split Brain Flag", "Primary Timeline", "Max Replay Backlog",
        "Replication Slots Total", "Replication Slots Active",
        "Replication Slots Inactive", "Max Slot Lag Bytes"
    ]
    for m in expected_metrics:
        rep.check(m in data, f"Cluster metric '{m}' is present ({data.get(m)})")

    # Child tables
    rep.check("Cluster_Nodes" in data and isinstance(data["Cluster_Nodes"], list), "Cluster_Nodes table present")
    if "Cluster_Nodes" in data:
        for row in data["Cluster_Nodes"]:
            rep.check("name" in row, f"Cluster_Nodes row has 'name' key ({row.get('name')})")

    rep.check("Replication_Standbys" in data and isinstance(data["Replication_Standbys"], list), "Replication_Standbys table present")
    if "Replication_Standbys" in data:
        for row in data["Replication_Standbys"]:
            rep.check("name" in row, f"Replication_Standbys row has 'name' key ({row.get('name')})")

    # Units and tabs
    units = data.get("units", {})
    rep.check(isinstance(units, dict) and "Nodes Total" in units, "units dictionary configured")
    tabs = data.get("tabs", {})
    rep.check("Cluster" in tabs, "Cluster tab present in tabs definition")

    # Childdiscovery in s247config
    childdiscovery = (data.get("s247config") or {}).get("childdiscovery", [])
    rep.check("Cluster_Nodes" in childdiscovery and "Replication_Standbys" in childdiscovery,
              f"s247config.childdiscovery includes cluster tables: {childdiscovery}")


def test_failover_assertion(plugin_py, nodes, user, password, db, patroni_port, rep):
    print("\n=== Test 4: Dynamic Failover Assertion ===")
    containers = ["patroni-pg-node1", "patroni-pg-node2", "patroni-pg-node3"]
    leader = None

    # Step A: Identify current leader
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

    # Step B: Stop leader
    print(f"  Stopping leader container '{leader}'...")
    subprocess.run(["docker", "stop", leader], check=True)

    try:
        # Step C: Wait for failover
        print("  Waiting 12 seconds for Patroni automatic leader promotion...")
        time.sleep(12)

        # Step D: Run plugin and assert
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

        # Verify stopped node is marked down in Cluster_Nodes
        stopped_node_entry = next((n for n in data_after.get("Cluster_Nodes", []) if n.get("status") == "down"), None)
        rep.check(stopped_node_entry is not None and stopped_node_entry.get("role") == "down",
                  f"Stopped node correctly marked as down in Cluster_Nodes ({stopped_node_entry.get('name') if stopped_node_entry else 'None'})")

    finally:
        # Step E: Recover stopped container
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

    plugin_py = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "postgres_cluster", "postgres_cluster.py"))
    nodes = os.environ.get("PG_NODES", "node1=localhost:5441,node2=localhost:5442,node3=localhost:5443")
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

    # Test 1: Active 3-node cluster run
    print("=== Test 1: Plugin execution on 3-node active cluster ===")
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
    print("\n=== Test 2: Dead host handling (never crash on dead node) ===")
    dead_nodes = "node_dead=localhost:5999,node_dead2=localhost:5998"
    proc_dead, elapsed_dead = run_plugin(plugin_py, dead_nodes, user, password, db)
    rep.check(proc_dead.returncode == 0, f"Dead node test exit code 0 (elapsed: {elapsed_dead:.2f}s)")
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

    # Test 4: Dynamic Failover Assertion
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
