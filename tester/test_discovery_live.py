"""
Live discovery test: for every running test bed, run the plugin INSIDE the bed's Docker network with ONE seed
address and check that all nodes are found, the roles are right and the cluster type is detected.

    python tester\\test_discovery_live.py            # tests every bed that is running
    python tester\\test_discovery_live.py patroni    # only beds whose name contains "patroni"

Beds that are not running are reported as SKIP (never as PASS). Needs Docker. Prints a final RESULT line.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PLUGIN_DIR = os.path.join(ROOT, "upstream_layout", "postgres_cluster")


def env_password(container, var="POSTGRES_PASSWORD"):
    out = subprocess.run(["docker", "inspect", container, "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith(var + "="):
            return line.split("=", 1)[1]
    return None


def dotenv(name):
    try:
        for line in open(os.path.join(ROOT, ".env")):
            if line.startswith(name + "="):
                return line.strip().split("=", 1)[1]
    except OSError:
        pass
    return None


# name, docker network, a running container of the bed, seed (host:pg_port:patroni_port), user, password, db,
# expected total nodes, expected primaries, expected type (substring)
BEDS = [
    ("patroni (seed = one member)", "patroni-cluster_default", "patroni-pg-node1", "pg-node1:5432:8008", "site24x7", lambda: "site24x7", "appdb", 3, 1, "Patroni"),
    ("plain streaming (seed = standby)", "pg-cluster-site24x7_default", "pg-cluster-site24x7-pg-replica-1", "pg-replica:5432:none", "site24x7", lambda: dotenv("MONITOR_PASSWORD"), "postgres", 2, 1, "streaming"),
    ("plain streaming (seed = primary)", "pg-cluster-site24x7_default", "pg-cluster-site24x7-pg-primary-1", "pg-primary:5432:none", "site24x7", lambda: dotenv("MONITOR_PASSWORD"), "postgres", 2, 1, "streaming"),
    ("repmgr (seed = standby)", "tb-repmgr_default", "tb-repmgr-repmgr-node2-1", "repmgr-node2:5432:none", "site24x7", lambda: "site24x7", "postgres", 3, 1, "repmgr"),
    ("multi-master logical mesh", "pg-multimaster_default", "pg-mm1", "pg-mm1:5432:none", "site24x7", lambda: env_password("pg-mm1"), "postgres", 2, 2, "Multi-Master"),
    ("pg_auto_failover (seed = data node)", "tb-pgaf_default", "tb-pgaf-pgaf-node1-1", "pgaf-node1:5432:none", "docker", lambda: "", "postgres", 2, 1, "pg_auto_failover"),
    ("stolon (seed = keeper)", "tb-stolon_default", "tb-stolon-stolon-keeper1-1", "stolon-keeper1:5432:none", "postgres", lambda: "pgpass", "postgres", 3, 1, "Stolon"),
    ("citus (seed = coordinator)", "tb-citus_default", "tb-citus-citus-coordinator-1", "citus-coordinator:5432:none", "postgres", lambda: "pgpass", "postgres", 3, 3, "Citus"),
    ("cloudnativepg", "kind", "cnpg-test-control-plane", None, None, None, None, 3, 1, "CloudNative"),
]


def running(container):
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container], capture_output=True, text=True)
    return r.stdout.strip() == "true"


def main():
    flt = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    failures, passed, skipped = [], 0, 0
    for name, net, cont, seed, user, pwf, db, n_nodes, n_prim, typ in BEDS:
        if flt and flt not in name.lower():
            continue
        if seed is None or not running(cont):
            print(f"[SKIP] {name}: bed not running")
            skipped += 1
            continue
        pw = pwf()
        cmd = ["docker", "run", "--rm", "--network", net, "-v", f"{PLUGIN_DIR}:/p:ro", "python:3.12-slim", "sh", "-c",
               f"pip install -q psycopg2-binary 2>/dev/null; python /p/postgres_cluster.py --nodes {seed} --username {user} --password '{pw}' --db {db}"]
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
        line = next((l for l in out.splitlines() if l.startswith("{")), None)
        if not line:
            failures.append(f"{name}: no JSON output")
            print(f"[FAIL] {name}: no JSON output")
            continue
        j = json.loads(line)
        nodes = j.get("Cluster_Nodes", [])
        got_type = (j.get("Cluster_Info") or [{}])[0].get("cluster_type", "")
        problems = []
        if len(nodes) != n_nodes:
            problems.append(f"nodes {len(nodes)} != {n_nodes}")
        if j.get("Primary Count") != n_prim:
            problems.append(f"primaries {j.get('Primary Count')} != {n_prim}")
        if typ.lower() not in got_type.lower():
            problems.append(f"type '{got_type}' lacks '{typ}'")
        if j.get("Nodes Up") != n_nodes:
            problems.append(f"nodes up {j.get('Nodes Up')} != {n_nodes}")
        if j.get("Split Brain Flag") and n_prim == 1:
            problems.append("false split brain")
        desc = f"{len(nodes)} nodes [{', '.join(n['name'] + ':' + n['role'] for n in nodes)}] type='{got_type}' health={j.get('Cluster Health')}"
        if problems:
            failures.append(f"{name}: {'; '.join(problems)}")
            print(f"[FAIL] {name}: {'; '.join(problems)} | {desc}")
        else:
            passed += 1
            print(f"[PASS] {name}: {desc}")
    print(f"\nRESULT: {len(failures)} failure(s), {passed} passed, {skipped} skipped")
    for f in failures:
        print("  FAIL:", f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
