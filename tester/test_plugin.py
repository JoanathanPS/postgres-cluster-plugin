#!/usr/bin/env python3
"""
Test harness for the official Site24x7 PostgreSQL plugin (postgres/postgres.py)
against a primary + streaming-replica PostgreSQL cluster.

For every node it:
  1. runs postgres.py exactly as documented (python postgres.py --host --port
     --username --password --db) with the agent's default 50 s timeout;
  2. checks the JSON against the Site24x7 plugin output rules
     (plugin_version, heartbeat_required, status/msg, units, metric/table limits);
  3. checks the node's role in the cluster (primary / standby, streaming state).
It also runs one negative test (wrong password must give status 0 + msg).

Runs inside the plugin-test container (docker compose run --rm plugin-test) or
directly on Windows/Linux:
  python tester/test_plugin.py --plugin-dir postgres \
      --node pg_primary=localhost:5432 --node pg_replica=localhost:5433 [--db appdb]
Credentials: MONITOR_USER / MONITOR_PASSWORD environment variables.

This verifies the plugin locally. It does NOT prove a monitor is registered in
the Site24x7 web console; only the Site24x7 agent can do that.
"""
import argparse
import json
import os
import subprocess
import sys
import time

# Metrics the plugin README documents. Some depend on the server version:
#   "Buffers Backend*"  -> not on PG >= 17 (moved out of pg_stat_bgwriter)
#   "Total Sessions*"   -> only on PG >= 14
#   "Active Waiting Queries" -> PG >= 9.6
ALWAYS_EXPECTED = [
    "Table Count", "Active Queries", "Transactions Open",
    "Transactions Idle In Transaction", "Active Connections", "Total Commits",
    "Total Rollbacks", "Total Conflicts", "Checkpoints Timed", "Checkpoints Req",
    "Checkpoint Write Time", "Checkpoint Sync Time", "Buffers Checkpoint",
    "Buffers Clean", "Maxwritten Clean", "Buffers Alloc", "Locks Count",
    "Max Connections", "Total Rows Inserted", "Total Rows Updated",
    "Total Rows Deleted", "Total Rows Fetched", "Total Rows Returned",
    "Total Block Reads", "Total Block Hits", "Index Scans", "Index Rows Read",
    "Index Rows Fetched", "Server Version", "Uptime", "Database Count",
    "Heap Blocks Read", "Heap Blocks Hit", "Cache Hit Ratio",
    "Active Waiting Queries",
]
PG_LT_17 = ["Buffers Backend", "Buffers Backend Fsync"]
PG_GE_14 = ["Total Sessions", "Total Sessions Abandoned", "Total Sessions Fatal",
            "Total Sessions Killed"]
TABLES = ["Tranasctions_and_Session_per_Database", "Stats_per_DB"]  # spelling is upstream's
RESERVED = {"plugin_version", "heartbeat_required", "status", "msg", "units",
            "tabs", "s247config", "displayname"}

# Limits from https://www.site24x7.com/help/admin/adding-a-monitor/plugins/custom-plugins.html
MAX_METRICS, MAX_TABLES, MAX_COLS, MAX_ROWS = 200, 10, 15, 25
MAX_NAME_LEN, MAX_STR_LEN = 520, 100
AGENT_TIMEOUT_S = 50


class Report:
    def __init__(self):
        self.failures, self.warnings = [], []

    def ok(self, msg):
        print(f"  [PASS] {msg}")

    def fail(self, msg):
        self.failures.append(msg)
        print(f"  [FAIL] {msg}")

    def warn(self, msg):
        self.warnings.append(msg)
        print(f"  [WARN] {msg}")

    def check(self, cond, msg):
        (self.ok if cond else self.fail)(msg)
        return cond


def run_plugin(plugin_py, host, port, user, password, db):
    cmd = [sys.executable, plugin_py, "--host", host, "--port", str(port),
           "--username", user, "--password", password, "--db", db]
    start = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=AGENT_TIMEOUT_S)
    return proc, time.monotonic() - start


def validate_output(name, data, rep):
    rep.check(isinstance(data.get("plugin_version"), int) and data["plugin_version"] >= 1,
              f"plugin_version is a whole number ({data.get('plugin_version')!r})")
    rep.check("heartbeat_required" in data,
              f"heartbeat_required present ({data.get('heartbeat_required')!r})")

    status = data.get("status", 1)
    msg = data.get("msg", "")
    if not rep.check(status != 0, "status is not 0 (monitor would be UP)"):
        print(f"         msg: {msg}")
    if msg:
        rep.warn(f"plugin returned msg (some queries failed): {msg}")

    version_str = data.get("Server Version", "")
    try:
        major = int(version_str.split(".")[0])
    except ValueError:
        major = 0
    expected = list(ALWAYS_EXPECTED)
    if 0 < major < 17:
        expected += PG_LT_17
    if major >= 14:
        expected += PG_GE_14
    missing = [k for k in expected if k not in data]
    rep.check(not missing, f"all {len(expected)} documented metrics for PG {major} present"
              + (f" - missing: {missing}" if missing else ""))

    metrics = {k: v for k, v in data.items()
               if k not in RESERVED and not isinstance(v, (list, dict))}
    rep.check(len(metrics) <= MAX_METRICS, f"{len(metrics)} generic metrics (limit {MAX_METRICS})")
    nulls = [k for k, v in metrics.items() if v in (None, "None")]
    if nulls:
        rep.warn(f"metrics reported as 'None': {nulls} - the 'db' being monitored has no "
                 "user tables/indexes; point db= at an application database")
    non_numeric = [k for k, v in metrics.items()
                   if k != "Server Version" and k not in nulls and not _is_number(v)]
    rep.check(not non_numeric, "every metric except Server Version is numeric"
              + (f" - non-numeric: {non_numeric}" if non_numeric else ""))
    too_long = [k for k, v in metrics.items() if isinstance(v, str) and len(v) > MAX_STR_LEN]
    rep.check(not too_long, f"string metrics <= {MAX_STR_LEN} chars")

    tables = {k: v for k, v in data.items() if isinstance(v, list)}
    rep.check(len(tables) <= MAX_TABLES, f"{len(tables)} tables (limit {MAX_TABLES})")
    for t in TABLES:
        rows = data.get(t)
        if not rep.check(isinstance(rows, list) and len(rows) > 0, f"table '{t}' has rows"):
            continue
        cols = set().union(*(r.keys() for r in rows))
        rep.check("name" in cols, f"  '{t}': every row has a 'name' key")
        rep.check(len(cols) <= MAX_COLS, f"  '{t}': {len(cols)} columns (limit {MAX_COLS})")
        rep.check(len(rows) <= MAX_ROWS, f"  '{t}': {len(rows)} rows (limit {MAX_ROWS})")
        bad = [r.get("name") for r in rows if len(str(r.get("name", ""))) > MAX_NAME_LEN]
        rep.check(not bad, f"  '{t}': name <= {MAX_NAME_LEN} chars")
        rep.check(all(r.get("name") not in (None, "", "None") for r in rows),
                  f"  '{t}': no empty/None row names")
        str_cols = sorted(c for c in cols if c != "name"
                          and any(isinstance(r.get(c), str) for r in rows))
        if str_cols:
            rep.warn(f"'{t}': {len(str_cols)} columns are emitted as JSON strings "
                     f"(upstream uses str()); values are numeric text, e.g. "
                     f"{str_cols[0]}={rows[0].get(str_cols[0])!r}")

    child = (data.get("s247config") or {}).get("childdiscovery", [])
    rep.check(sorted(child) == sorted(TABLES), "s247config.childdiscovery lists both tables")
    units = data.get("units", {})
    rep.check(isinstance(units, dict) and all(k in data for k in units),
              f"units map ({len(units)} entries) only references emitted metrics")
    for tab, spec in (data.get("tabs") or {}).items():
        unknown = [k for k in spec.get("tablist", []) if k not in data]
        if unknown:
            rep.warn(f"tab '{tab}' lists attributes not emitted on this server: {unknown}")
    return major


def _is_number(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def cluster_checks(nodes, user, password, rep):
    """Replication health, using the same least-privilege monitoring account."""
    try:
        import psycopg2
    except ImportError:
        rep.fail("psycopg2 not installed - cannot run cluster checks")
        return
    roles = {}
    for name, (host, port) in nodes.items():
        try:
            conn = psycopg2.connect(host=host, port=port, user=user, password=password,
                                    dbname="postgres", connect_timeout=10)
        except Exception as e:  # noqa: BLE001
            rep.fail(f"{name}: cannot connect for cluster checks: {e}")
            continue
        with conn, conn.cursor() as cur:
            cur.execute("SELECT pg_is_in_recovery()")
            in_recovery = cur.fetchone()[0]
            roles[name] = "standby" if in_recovery else "primary"
            print(f"  {name}: role = {roles[name]}")
            if in_recovery:
                cur.execute("SELECT status, sender_host, slot_name FROM pg_stat_wal_receiver")
                row = cur.fetchone()
                rep.check(row is not None and row[0] == "streaming",
                          f"{name}: WAL receiver status = {row[0] if row else None} "
                          f"(sender {row[1] if row else '-'}, slot {row[2] if row else '-'})")
                cur.execute("SELECT COALESCE(EXTRACT(EPOCH FROM now() - "
                            "pg_last_xact_replay_timestamp()), 0)::numeric(10,1)")
                print(f"  {name}: seconds since last replayed transaction = {cur.fetchone()[0]}"
                      " (grows when the primary is idle; not by itself a fault)")
            else:
                cur.execute("SELECT application_name, client_addr, state, sync_state, "
                            "pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) "
                            "FROM pg_stat_replication")
                rows = cur.fetchall()
                rep.check(any(r[2] == "streaming" for r in rows),
                          f"{name}: {len(rows)} replica(s) connected: "
                          + ", ".join(f"{r[1]} state={r[2]} sync={r[3]} replay_lag_bytes={r[4]}"
                                      for r in rows))
        conn.close()
    if len(roles) == len(nodes):
        rep.check(list(roles.values()).count("primary") == 1,
                  f"exactly one primary in the cluster ({roles})")


def parse_nodes(items):
    nodes = {}
    for item in items:
        for part in filter(None, (p.strip() for p in item.split(","))):
            name, _, hp = part.partition("=")
            host, _, port = hp.rpartition(":")
            nodes[name] = (host, int(port))
    return nodes


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--plugin-dir", default=os.environ.get("PLUGIN_DIR", "postgres"))
    ap.add_argument("--node", action="append",
                    help="section=host:port (repeatable). Default: $PG_NODES")
    ap.add_argument("--db", default=os.environ.get("PLUGIN_DB", "appdb"),
                    help="database the plugin connects to (db= in postgres.cfg). Default: appdb")
    ap.add_argument("--output-dir", default=os.environ.get("OUTPUT_DIR"))
    args = ap.parse_args()

    user = os.environ.get("MONITOR_USER", "site24x7")
    password = os.environ.get("MONITOR_PASSWORD")
    if not password:
        sys.exit("MONITOR_PASSWORD is not set")
    nodes = parse_nodes(args.node or [os.environ.get("PG_NODES",
                        "pg_primary=localhost:5432,pg_replica=localhost:5433")])
    plugin_py = os.path.join(args.plugin_dir, "postgres.py")
    if not os.path.isfile(plugin_py):
        sys.exit(f"plugin not found: {plugin_py}")

    rep = Report()
    print(f"Plugin: {plugin_py}\nUser:   {user}\nDB:     {args.db}\nNodes:  {nodes}\n")

    for name, (host, port) in nodes.items():
        print(f"=== {name} ({host}:{port}) ===")
        try:
            proc, elapsed = run_plugin(plugin_py, host, port, user, password, args.db)
        except subprocess.TimeoutExpired:
            rep.fail(f"{name}: plugin exceeded the agent's {AGENT_TIMEOUT_S}s timeout")
            continue
        rep.check(proc.returncode == 0, f"exit code {proc.returncode}, ran in {elapsed:.2f}s"
                  + (f"\n         stderr: {proc.stderr.strip()}" if proc.stderr.strip() else ""))
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            rep.fail(f"stdout is not valid JSON: {e}\n{proc.stdout[:500]}")
            continue
        rep.ok("stdout is valid JSON")
        validate_output(name, data, rep)
        sample = {k: data.get(k) for k in ("Server Version", "Uptime", "Active Connections",
                                            "Database Count", "Total Commits", "Cache Hit Ratio")}
        print(f"  sample: {json.dumps(sample)}")
        if args.output_dir:
            path = os.path.join(args.output_dir, f"{name}.json")
            try:
                os.makedirs(args.output_dir, exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
                print(f"  full output written to {path}")
            except OSError as e:
                rep.warn(f"could not save full output to {path}: {e}")
        print()

    print("=== negative test: wrong password ===")
    host, port = next(iter(nodes.values()))
    proc, _ = run_plugin(plugin_py, host, port, user, password + "_wrong", args.db)
    try:
        bad = json.loads(proc.stdout)
        rep.check(bad.get("status") == 0 and "authentication failed" in bad.get("msg", ""),
                  f"status=0 with msg: {bad.get('msg', '').strip()[:120]}")
    except json.JSONDecodeError:
        rep.fail("wrong-password run did not print JSON")
    print()

    print("=== cluster / replication checks ===")
    cluster_checks(nodes, user, password, rep)

    print(f"\nRESULT: {len(rep.failures)} failure(s), {len(rep.warnings)} warning(s)")
    for f in rep.failures:
        print(f"  FAIL: {f}")
    sys.exit(1 if rep.failures else 0)


if __name__ == "__main__":
    main()
