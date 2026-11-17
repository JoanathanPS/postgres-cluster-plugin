#!/usr/bin/env python3
"""
Multi-Cluster Automated Verification Suite
Tests the plugin against:
  1. Plain-streaming 2-node cluster (docker compose in repo root)
     - Normal streaming verification
     - pg_promote failover
     - Split brain condition (2 primaries)
  2. Standalone PostgreSQL 14 container
  3. Standalone PostgreSQL 16 container
Guarantees clean environment teardown in try/finally blocks.
"""

import os
import sys
import json
import time
import subprocess

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLUGIN_PATH = os.path.join(REPO_ROOT, "upstream_layout", "postgres_cluster", "postgres_cluster.py")
if not os.path.exists(PLUGIN_PATH):
    PLUGIN_PATH = os.path.join(REPO_ROOT, "postgres_cluster", "postgres_cluster.py")

def run_cmd(cmd, check=True, cwd=REPO_ROOT, timeout=120):
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd, timeout=timeout)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed ({res.returncode}): {' '.join(cmd)}\nStderr: {res.stderr}\nStdout: {res.stdout}")
    return res

def run_plugin(nodes, username="site24x7", password="site24x7", db="postgres", patroni_port="8008", cluster_type="auto"):
    cmd = [
        sys.executable, PLUGIN_PATH,
        "--nodes", nodes,
        "--username", username,
        "--password", password,
        "--db", db,
        "--patroni_port", patroni_port,
        "--cluster_type", cluster_type
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
    try:
        data = json.loads(res.stdout)
    except Exception as e:
        print(f"Failed to parse JSON: {e}\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
        raise
    return data

def test_plain_streaming():
    print("\n" + "=" * 65)
    print(" 1. PLAIN-STREAMING 2-NODE CLUSTER TESTS")
    print("=" * 65)
    try:
        print("Starting 2-node streaming cluster (docker compose up -d)...")
        run_cmd(["docker", "compose", "up", "-d", "pg-primary", "pg-replica"])
        
        # Wait for healthy
        print("Waiting for streaming replication cluster to be ready...")
        for _ in range(30):
            res = run_cmd(["docker", "compose", "ps", "--format", "json"], check=False)
            if "pg-primary" in res.stdout and "pg-replica" in res.stdout:
                # check if postgres is accepting connections
                check_p = run_cmd(["docker", "exec", "pg-cluster-site24x7-pg-primary-1", "pg_isready", "-U", "site24x7"], check=False)
                if check_p.returncode == 0:
                    break
            time.sleep(2)
        else:
            print("Warning: timed out waiting for ready, continuing...")

        time.sleep(5)
        # Probe normal state
        print("Probing 2-node streaming replication...")
        data = run_plugin("127.0.0.1:5432,127.0.0.1:5433", username="site24x7", password="site24x7")
        print(f"  Cluster Type: {data.get('Cluster Type')}")
        print(f"  Nodes Up: {data.get('Nodes Up')}, Primary Count: {data.get('Primary Count')}")
        assert data.get("Nodes Up") == 2, f"Expected 2 nodes up, got {data.get('Nodes Up')}"
        assert data.get("Primary Count") == 1, f"Expected 1 primary, got {data.get('Primary Count')}"
        assert "streaming" in data.get("Cluster Type", "").lower(), f"Expected streaming replication, got {data.get('Cluster Type')}"
        assert data.get("Cluster Health") == 0, f"Expected healthy (0), got {data.get('Cluster Health')}"
        print("  [PASS] Normal 2-node streaming verified.")

        # Test promote replica -> split brain (both 5432 and 5433 are primary)
        print("Promoting pg-replica via SELECT pg_promote() to induce split-brain...")
        run_cmd(["docker", "exec", "pg-cluster-site24x7-pg-replica-1", "psql", "-U", "postgres", "-d", "postgres", "-c", "SELECT pg_promote();"])
        time.sleep(4)
        
        data_sb = run_plugin("127.0.0.1:5432,127.0.0.1:5433", username="site24x7", password="site24x7")
        print(f"  Split Brain Flag: {data_sb.get('Split Brain Flag')}, Primary Count: {data_sb.get('Primary Count')}")
        print(f"  Cluster Health: {data_sb.get('Cluster Health')}, Reason: {data_sb.get('Cluster Health Reason')}")
        assert data_sb.get("Split Brain Flag") == 1, f"Expected Split Brain Flag 1, got {data_sb.get('Split Brain Flag')}"
        assert data_sb.get("Cluster Health") == 2, f"Expected Health 2 (Critical), got {data_sb.get('Cluster Health')}"
        print("  [PASS] Split-brain detected and alerted as Critical health.")

    finally:
        print("Tearing down 2-node streaming cluster...")
        run_cmd(["docker", "compose", "down", "-v"], check=False)
        print("2-node streaming cluster cleanly destroyed.")

def test_standalone(version, port):
    c_name = f"test-standalone-pg{version}"
    print("\n" + "=" * 65)
    print(f" 2. STANDALONE POSTGRESQL {version} TEST (PORT {port})")
    print("=" * 65)
    try:
        print(f"Running standalone postgres:{version}...")
        run_cmd([
            "docker", "run", "-d",
            "--name", c_name,
            "-p", f"127.0.0.1:{port}:5432",
            "-e", "POSTGRES_USER=site24x7",
            "-e", "POSTGRES_PASSWORD=site24x7",
            "-e", "POSTGRES_DB=postgres",
            f"postgres:{version}"
        ])

        print(f"Waiting for {c_name} to be ready...")
        for _ in range(20):
            res = run_cmd(["docker", "exec", c_name, "pg_isready", "-U", "site24x7"], check=False)
            if res.returncode == 0:
                break
            time.sleep(1)
        time.sleep(2)

        data = run_plugin(f"127.0.0.1:{port}", username="site24x7", password="site24x7")
        print(f"  Cluster Type: {data.get('Cluster Type')}")
        print(f"  Nodes Up: {data.get('Nodes Up')}, Primary Count: {data.get('Primary Count')}")
        print(f"  Server Version: {data.get('Server Version')}")
        assert data.get("Nodes Up") == 1, f"Expected 1 node up, got {data.get('Nodes Up')}"
        assert data.get("Primary Count") == 1, f"Expected 1 primary, got {data.get('Primary Count')}"
        assert data.get("Cluster Type") == "standalone", f"Expected standalone, got {data.get('Cluster Type')}"
        assert data.get("Cluster Health") == 0, f"Expected healthy (0), got {data.get('Cluster Health')}"
        print(f"  [PASS] Standalone PostgreSQL {version} verified.")

    finally:
        print(f"Cleaning up {c_name}...")
        run_cmd(["docker", "rm", "-f", c_name], check=False)
        print(f"{c_name} removed.")

if __name__ == "__main__":
    try:
        test_plain_streaming()
        test_standalone(14, 5514)
        test_standalone(16, 5516)
        print("\n" + "=" * 65)
        print(" ALL MULTI-CLUSTER TESTS PASSED (0 FAILURES)")
        print("=" * 65)
    except Exception as e:
        print(f"\nTEST RUN FAILED: {e}")
        sys.exit(1)
