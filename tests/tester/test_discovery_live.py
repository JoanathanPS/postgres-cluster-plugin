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
    ("plain streaming (both addresses listed)", "pg-cluster-site24x7_default", "pg-cluster-site24x7-pg-primary-1", "pg-primary:5432:none,pg-replica:5432:none", "site24x7", lambda: dotenv("MONITOR_PASSWORD"), "postgres", 2, 1, "streaming"),
    ("repmgr (seed = standby; primary, 2 standbys and a witness)", "tb-repmgr_default", "repmgr-node2", "repmgr-node2:5432:none", "site24x7", lambda: "site24x7", "postgres", 4, 1, "repmgr"),
    ("multi-master logical mesh", "pg-multimaster_default", "pg-mm1", "pg-mm1:5432:none", "site24x7", lambda: env_password("pg-mm1"), "postgres", 3, 3, "Multi-Master"),
    ("pg_auto_failover (both data nodes listed)", "tb-pgaf_default", "tb-pgaf-pgaf-node1-1", "pgaf-node1:5432:none,pgaf-node2:5432:none", "docker", lambda: "", "postgres", 2, 1, "pg_auto_failover"),
    ("stolon (all three keepers listed)", "tb-stolon_default", "tb-stolon-stolon-keeper1-1", "stolon-keeper1:5432:none,stolon-keeper2:5432:none,stolon-keeper3:5432:none", "postgres", lambda: "pgpass", "postgres", 3, 1, "Stolon"),
    ("citus (seed = coordinator)", "tb-citus_default", "tb-citus-citus-coordinator-1", "citus-coordinator:5432:none", "postgres", lambda: "pgpass", "postgres", 3, 3, "Citus"),
    ("pgpool-II (seed = the pgpool address)", "tb-pgpool_default", "tb-pgpool-pgpool-1", "pgpool:9999:none", "site24x7", lambda: "", "postgres", 3, 1, "pgpool"),
    ("cloudnativepg", "kind", "cnpg-test-control-plane", "cnpg-test-ro:5432:none", "postgres", lambda: "", "postgres", 2, 1, "CloudNative"),
]


def run_bed(name, net, seed, user, pw, db):
    """Runs the plugin once from inside the bed's network and returns its stdout."""
    if name == "cloudnativepg":
        return run_in_kubernetes()
    cmd = ["docker", "run", "--rm", "--network", net, "-v", f"{PLUGIN_DIR}:/p:ro", "python:3.12-slim", "sh", "-c",
           f"pip install -q psycopg2-binary 2>/dev/null; python /p/postgres_cluster.py --nodes {seed} --username {user} --password '{pw}' --db {db}"]
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def run_in_kubernetes():
    """CloudNativePG: run the plugin as a pod in the kind cluster, seeded with the read-only service (any replica)."""
    import base64
    k = ["kubectl", "--context", "kind-cnpg-test"]
    pw = base64.b64decode(subprocess.run(k + ["get", "secret", "cnpg-test-superuser", "-o", "jsonpath={.data.password}"],
                                         capture_output=True, text=True).stdout.strip() or b"").decode()
    cm = subprocess.run(k + ["create", "configmap", "pg-plugin", f"--from-file=postgres_cluster.py={os.path.join(PLUGIN_DIR, 'postgres_cluster.py')}",
                             "--dry-run=client", "-o", "yaml"], capture_output=True, text=True).stdout
    subprocess.run(k + ["apply", "-f", "-"], input=cm, capture_output=True, text=True)
    subprocess.run(k + ["delete", "pod", "plugin-test", "--ignore-not-found", "--wait=true"], capture_output=True, text=True)
    pod = f"""apiVersion: v1
kind: Pod
metadata: {{name: plugin-test}}
spec:
  restartPolicy: Never
  containers:
  - name: p
    image: python:3.12-slim
    command: ["sh", "-c", "pip install -q psycopg2-binary 2>/dev/null; python /p/postgres_cluster.py --nodes cnpg-test-ro:5432:none --username postgres --password '{pw}' --db postgres"]
    volumeMounts: [{{name: code, mountPath: /p}}]
  volumes: [{{name: code, configMap: {{name: pg-plugin}}}}]
"""
    subprocess.run(k + ["apply", "-f", "-"], input=pod, capture_output=True, text=True)
    subprocess.run(k + ["wait", "--for=jsonpath={.status.phase}=Succeeded", "pod/plugin-test", "--timeout=240s"], capture_output=True, text=True)
    return subprocess.run(k + ["logs", "plugin-test"], capture_output=True, text=True).stdout


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
        out = run_bed(name, net, seed, user, pw, db)
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
