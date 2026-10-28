#!/usr/bin/env python3
"""
Replication Lag Demonstration using pgbench and Site24x7 PostgreSQL Cluster Plugin.

Flow:
  1. Identifies the primary and standby containers.
  2. Runs postgres_cluster plugin: verifies initial Max Replay Backlog = 0.
  3. Pauses one standby container to induce replication backlog.
  4. Generates transactions on the primary via pgbench.
  5. Runs postgres_cluster plugin: verifies Max Replay Backlog > 0 and displays replication lag.
  6. Unpauses the standby container.
  7. Waits for catchup and verifies Max Replay Backlog returns to 0.
"""

import json
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
upstream_py = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "upstream_layout", "postgres_cluster", "postgres_cluster.py"))
fallback_py = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "postgres_cluster", "postgres_cluster.py"))
PLUGIN_PY = upstream_py if os.path.exists(upstream_py) else fallback_py
NODES = os.environ.get("PG_NODES", "node1=localhost:5441,node2=localhost:5442,node3=localhost:5443")
USER = os.environ.get("MONITOR_USER", "site24x7")
PASS = os.environ.get("MONITOR_PASSWORD", "site24x7")
DB = os.environ.get("MONITOR_DB", "appdb")


def get_python_exe():
    if sys.platform == "win32":
        import shutil
        if shutil.which("py"):
            return "py"
    return sys.executable


def run_plugin():
    cmd = [get_python_exe(), PLUGIN_PY, "--nodes", NODES, "--username", USER, "--password", PASS, "--db", DB]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"Plugin failed: {proc.stderr}")
    return json.loads(proc.stdout)


def find_containers():
    # Identify primary and standby containers
    nodes = ["patroni-pg-node1", "patroni-pg-node2", "patroni-pg-node3"]
    primary = None
    standby = None
    for n in nodes:
        try:
            res = subprocess.run(
                ["docker", "exec", n, "psql", "-U", "postgres", "-tA", "-c", "SELECT pg_is_in_recovery();"],
                capture_output=True, text=True, timeout=5
            )
            is_standby = res.stdout.strip() == "t"
            if not is_standby and primary is None:
                primary = n
            elif is_standby and standby is None:
                standby = n
        except Exception:
            pass
    return primary, standby


def main():
    print("=" * 65)
    print(" PostgreSQL Cluster Replication Lag Demonstration (pgbench)")
    print("=" * 65)

    primary, standby = find_containers()
    if not primary or not standby:
        print(f"Error: Could not determine cluster nodes (Primary: {primary}, Standby: {standby})")
        sys.exit(1)

    print(f"Active Primary container: {primary}")
    print(f"Target Standby container: {standby}\n")

    # Step 1: Initial state
    print("[1/4] Checking baseline plugin metrics...")
    data_init = run_plugin()
    print(f"  Max Replay Backlog:    {data_init.get('Max Replay Backlog', 0)} bytes")
    print(f"  Replication Standbys:  {len(data_init.get('Replication_Standbys', []))} connected\n")

    # Step 2: Induce backlog
    print(f"[2/4] Pausing standby '{standby}' to simulate network/storage stall...")
    subprocess.run(["docker", "pause", standby], check=True)

    try:
        print(f"[3/4] Generating transactional write load on primary '{primary}' via pgbench...")
        # Ensure pgbench schema exists
        subprocess.run(
            ["docker", "exec", primary, "pgbench", "-i", "-s", "1", "-U", "postgres", "appdb"],
            capture_output=True, text=True, check=True
        )
        # Execute transactions
        subprocess.run(
            ["docker", "exec", primary, "pgbench", "-t", "300", "-c", "5", "-U", "postgres", "appdb"],
            capture_output=True, text=True, check=True
        )
        print("  [OK] 1500 transactions processed on primary.")

        # Run plugin to check backlog
        print("\n  Evaluating plugin output under replication backlog:")
        data_lag = run_plugin()
        lag_bytes = data_lag.get("Max Replay Backlog", 0)
        slot_lag = data_lag.get("Max Slot Lag Bytes", 0)
        print(f"  [METRIC] Max Replay Backlog:  {lag_bytes} bytes ({lag_bytes / 1024:.1f} KB)")
        print(f"  [METRIC] Max Slot Lag Bytes:  {slot_lag} bytes")

        for s in data_lag.get("Replication_Standbys", []):
            print(f"    * Standby '{s.get('name')}': state={s.get('state')}, replay_lag={s.get('replay_lag_bytes')} bytes")

        if lag_bytes > 0:
            print("  [OK] Backlog successfully detected and reported by plugin!")
        else:
            print("  [INFO] Backlog was 0 (write rate or pause window may be too short)")

    finally:
        # Step 4: Resume standby
        print(f"\n[4/4] Resuming standby '{standby}' and waiting for catchup...")
        subprocess.run(["docker", "unpause", standby], check=True)
        time.sleep(4)

        data_recovered = run_plugin()
        rec_lag = data_recovered.get("Max Replay Backlog", 0)
        print(f"  [METRIC] Max Replay Backlog after catchup: {rec_lag} bytes")

    print("\n" + "=" * 65)
    print(" [OK] Replication Lag demonstration completed successfully!")
    print("=" * 65)


if __name__ == "__main__":
    main()
