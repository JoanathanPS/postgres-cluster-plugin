#!/usr/bin/env python3
"""
fake_pg.py — a scriptable stand-in for a PostgreSQL cluster, so a collector can be
tested without a cluster, without Docker, and without waiting for a failover.

Why this exists
---------------
The hard part of testing a monitoring plugin is not the happy path. It is:

  * the primary dying mid-collection
  * a node that authenticates but whose `pg_monitor` grant is missing, so one
    query raises `InsufficientPrivilege` while the rest work
  * a standby 12 minutes behind
  * a slot retaining 500 GB of WAL
  * a node that answers in 4 s and blows the collection deadline
  * PostgreSQL 16 where `pg_stat_wal_receiver` exists, and Aurora where it raises
    `FeatureNotSupported`
  * a cluster in the middle of a failover: two nodes both claim primary, timelines
    disagree

You cannot reproduce those on demand against a real cluster. You *can* reproduce
them deterministically here.

How it works
------------
`psycopg2.connect()` is replaced with a fake module whose `connect()` returns a
FakeConnection. Every statement is matched (by substring, in order) against a
scenario's `queries` list; the first match returns its rows. An entry may raise an
error to simulate permissions/version failures, and may sleep to simulate a slow
node. `pg_is_in_recovery()`, `pg_current_wal_lsn()` etc. are matched as ordinary
substrings, which is enough because the plugin issues discrete queries.

Modes
  --list                 show built-in scenarios
  --run <scenario>       execute the collector with psycopg2 patched, print JSON
  --snapshot out.json    write the emitted payload (feed it to s247_validate.py)
  --time                 print per-statement elapsed times (deadline budgeting)

Exit codes: 0 ok, 1 collector returned status 0 unexpectedly (scenario says it
should be up), 2 harness failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import types

# --------------------------------------------------------------------- errors


class FakePgError(Exception):
    """Base for simulated server errors."""

    def __init__(self, message: str, pgcode: str = None):
        super().__init__(message)
        self.pgcode = pgcode


class OperationalError(FakePgError):
    pass


class InsufficientPrivilege(FakePgError):
    def __init__(self, msg="permission denied"):
        super().__init__(msg, pgcode="42501")


class UndefinedTable(FakePgError):
    def __init__(self, msg="relation does not exist"):
        super().__init__(msg, pgcode="42P01")


class UndefinedFunction(FakePgError):
    def __init__(self, msg="function does not exist"):
        super().__init__(msg, pgcode="42883")


class FeatureNotSupported(FakePgError):
    def __init__(self, msg="feature not supported"):
        super().__init__(msg, pgcode="0A000")


class QueryCanceled(FakePgError):
    def __init__(self, msg="canceling statement due to statement timeout"):
        super().__init__(msg, pgcode="57014")


# ------------------------------------------------------------------- plumbing


class FakeCursor:
    def __init__(self, conn: "FakeConnection"):
        self.conn = conn
        self._rows = []
        self.description = None
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        sql_one = " ".join(str(sql).split())
        self.conn.statements.append((sql_one, params))
        self.conn.runner.run(sql_one, params)
        rows, desc = self.conn.runner.last()
        self._rows = list(rows or [])
        self.description = desc
        self.rowcount = len(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def fetchmany(self, n):
        return self._rows[:n]

    def close(self):
        pass

    def cancel(self):
        pass


class FakeConnection:
    def __init__(self, dsn: dict, runner: "Runner"):
        self.dsn = dsn
        self.runner = runner
        self.autocommit = False
        self.closed = 0
        self.statements = []
        self.server_version = int(runner.scenario.get("server_version_num", 160002))

    def cursor(self, *a, **kw):
        return FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = 1

    def cancel(self):
        pass

    @property
    def info(self):
        return types.SimpleNamespace(transaction_status=0, dbname=self.dsn.get("dbname"))


class Runner:
    """Matches statements against the scenario and remembers the last result."""

    def __init__(self, scenario: dict, node_name: str):
        self.scenario = scenario
        self.node_name = node_name
        self.timings = []
        self._last = ([], None)

    def run(self, sql: str, params):
        t0 = time.monotonic()
        low = sql.lower()
        for rule in self.scenario.get("queries", []):
            needle = rule["match"]
            if needle.lower() in low:
                if rule.get("delay"):
                    time.sleep(rule["delay"])
                if rule.get("raise"):
                    err = rule["raise"]
                    cls = {"auth": OperationalError, "privilege": InsufficientPrivilege,
                           "undefined_table": UndefinedTable, "undefined_function": UndefinedFunction,
                           "feature_not_supported": FeatureNotSupported,
                           "timeout": QueryCanceled}.get(err, OperationalError)
                    self.timings.append((round((time.monotonic() - t0) * 1000, 2), needle, "RAISE"))
                    raise cls(rule.get("message") or f"simulated {err}")
                rows = rule.get("rows") or []
                desc = rule.get("columns")
                if desc:
                    desc = [(c,) + (None,) * 6 for c in desc]
                self.timings.append((round((time.monotonic() - t0) * 1000, 2), needle, f"{len(rows)} rows"))
                self._last = (rows, desc)
                return
        # Unmatched statement: return an empty result rather than exploding, but
        # record it, because "the collector asked something the scenario does not
        # model" is exactly the gap that hides bugs.
        self.timings.append((round((time.monotonic() - t0) * 1000, 2), sql[:60], "UNMATCHED"))
        self._last = ([], None)

    def last(self):
        return self._last


SCENARIOS = {}


def scenario(name, description, **kw):
    def deco(fn):
        SCENARIOS[name] = {"name": name, "description": description, "factory": fn}
        return fn
    return deco


# ------------------------------------------------------------------ scenarios


@scenario("healthy-3node",
          "1 primary + 2 standbys, healthy. Everything a normal poll should look like.")
def _healthy(cfg):
    cluster = cfg.get("cluster", "demo")
    nodes = {
        "pg1": dict(role="primary", tl=4, lag_s=0, lag_bytes=0, conns=42),
        "pg2": dict(role="standby", tl=4, lag_s=0.4, lag_bytes=0, conns=18),
        "pg3": dict(role="standby", tl=4, lag_s=1.1, lag_bytes=2048, conns=9),
    }
    out = {}
    for name, n in nodes.items():
        out[name] = _node_scenario(n, cluster)
    return out


@scenario("primary-down",
          "Primary unreachable, one standby still streaming. Exercises the last-known-good clamp.")
def _primary_down(cfg):
    nodes = _healthy(cfg)
    nodes["pg1"] = {"server_version_num": 160002, "unreachable": True, "queries": []}
    nodes["pg2"].update({"role": "standby"})   # nobody promoted: no primary
    return nodes


@scenario("lagging-standby",
          "One standby 12 minutes behind with a 400 MB backlog; the other is fine.")
def _lagging(cfg):
    nodes = _healthy(cfg)
    nodes["pg3"].update({"lag_s": 720.0, "lag_bytes": 400 * 1024 * 1024})
    nodes["pg3"]["queries"] = _node_queries(dict(role="standby", tl=4, lag_s=720.0,
                                                 lag_bytes=400 * 1024 * 1024, conns=9))
    return nodes


@scenario("privilege-gap",
          "Monitor role can read most views but not pg_stat_replication or the slot view.")
def _privilege(cfg):
    nodes = _healthy(cfg)
    q = nodes["pg1"]["queries"]
    q.append({"match": "from pg_stat_replication", "raise": "privilege"})
    q.append({"match": "from pg_replication_slots", "raise": "privilege"})
    return nodes


@scenario("slow-node",
          "One node answers in 4 s per statement: blows the per-node deadline without failing.")
def _slow(cfg):
    nodes = _healthy(cfg)
    for r in nodes["pg3"]["queries"]:
        r["delay"] = 0.5
    return nodes


@scenario("split-brain",
          "Two nodes both claim primary on different timelines.")
def _split(cfg):
    nodes = _healthy(cfg)
    nodes["pg2"] = _node_scenario(dict(role="primary", tl=5, lag_s=0, lag_bytes=0, conns=20), cfg.get("cluster"))
    return nodes


@scenario("no-pgss",
          "pg_stat_statements not installed: workload metrics must degrade, not crash.")
def _no_pgss(cfg):
    nodes = _healthy(cfg)
    for n in nodes.values():
        n["queries"].append({"match": "from pg_stat_statements", "raise": "undefined_table"})
    return nodes


@scenario("short-strings",
          "Row values longer than Site24x7's 100-char limit and a name over 520 chars.")
def _long(cfg):
    nodes = _healthy(cfg)
    nodes["pg1"]["queries"].append({
        "match": "from pg_stat_activity",
        "columns": ["application_name", "state"],
        "rows": [["A" * 250, "active"]],
    })
    return nodes


def _node_queries(n: dict):
    q = [
        {"match": "select pg_is_in_recovery()", "rows": [[n["role"] == "standby"]]},
        {"match": "select count(*) from pg_stat_activity", "rows": [[n["conns"] // 2]]},
        {"match": "from pg_stat_activity where state", "rows": [[0]]},
        {"match": "from pg_stat_database", "columns": ["numbackends", "xact_commit", "xact_rollback",
                                                       "tup_inserted", "tup_updated", "tup_deleted",
                                                       "tup_fetched", "tup_returned", "blks_read",
                                                       "blks_hit", "conflicts"],
         "rows": [[n["conns"], 100000, 12, 5000, 300, 20, 90000, 120000, 4000, 900000, 0]]},
        {"match": "from pg_settings where name", "rows": [["100"]]},
        {"match": "pg_postmaster_start_time", "rows": [[86400]]},
    ]
    if n["role"] == "standby":
        q.append({"match": "from pg_stat_wal_receiver", "columns": ["status", "sender_host", "sender_port"],
                  "rows": [["streaming", "10.0.0.1", 5432]] if n["lag_bytes"] < 10 ** 9 else [["streaming", "10.0.0.1", 5432]]})
        q.append({"match": "pg_last_wal_receive_lsn", "rows": [[n["lag_bytes"]]]})
        q.append({"match": "pg_last_xact_replay_timestamp", "rows": [[n["lag_s"]]]})
    else:
        q.append({"match": "pg_current_wal_lsn", "rows": [["0/5000000"]]})
        q.append({"match": "from pg_stat_replication", "columns": ["application_name", "state", "sync_state"],
                  "rows": [["pg2", "streaming", "sync"], ["pg3", "streaming", "async"]]})
        q.append({"match": "from pg_replication_slots", "columns": ["slot_name", "slot_type", "active"],
                  "rows": [["pg2_slot", "physical", True], ["stale_slot", "logical", False]]})
    return q


def _node_scenario(n: dict, cluster: str = "demo") -> dict:
    return {"server_version_num": 160002, "queries": _node_queries(n)}


# ------------------------------------------------------------------ fake module


def make_fake_psycopg2(scenarios: dict):
    """Build a module object that quacks like psycopg2 for one collector run."""
    mod = types.ModuleType("psycopg2")

    def connect(**kw):
        host, port = kw.get("host"), int(kw.get("port") or 5432)
        key = f"{host}:{port}"
        node = scenarios.get(key) or scenarios.get(str(host)) or scenarios.get("pg1")
        if node is None:
            raise OperationalError(f"could not connect to {key}: Connection refused")
        if node.get("unreachable"):
            raise OperationalError(f"could not connect to {key}: Connection refused")
        return FakeConnection(kw, Runner(node, str(host)))

    mod.connect = connect
    mod.OperationalError = OperationalError
    mod.InterfaceError = FakePgError
    mod.ProgrammingError = FakePgError
    mod.Error = FakePgError
    mod.errors = types.SimpleNamespace(
        InsufficientPrivilege=InsufficientPrivilege,
        UndefinedTable=UndefinedTable,
        UndefinedFunction=UndefinedFunction,
        FeatureNotSupported=FeatureNotSupported,
        QueryCanceled=QueryCanceled,
    )
    mod.extensions = mod.errors
    return mod


def to_scenarios(raw: dict, cluster_host: str, ports=None) -> tuple:
    """Map a scenario's node dict onto host:port keys the collector will dial."""
    ports = ports or {}
    mapped = {}
    for i, (name, node) in enumerate(raw.items(), 1):
        port = ports.get(name, 5400 + i)
        mapped[f"{cluster_host}:{port}"] = node
        mapped[name] = node
    return mapped, {name: ports.get(name, 5400 + i) for i, name in enumerate(raw, 1)}


def main(argv):
    ap = argparse.ArgumentParser(description="Scriptable fake PostgreSQL cluster for plugin testing.")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--run", help="scenario name")
    ap.add_argument("--plugin", default="postgres_cluster.py", help="collector module or file")
    ap.add_argument("--snapshot", help="write emitted payload here")
    ap.add_argument("--time", action="store_true", help="print per-statement timings")
    ap.add_argument("--host", default="10.0.0.1", help="fake cluster host the plugin will dial")
    args = ap.parse_args(argv)

    if args.list or not args.run:
        print("scenarios:")
        for name, s in SCENARIOS.items():
            print(f"  {name.ljust(16)} {s['description']}")
        return 0 if args.list else 2

    if args.run not in SCENARIOS:
        print(f"unknown scenario {args.run!r}; use --list")
        return 2

    raw = SCENARIOS[args.run]["factory"]({})
    mapped, ports = to_scenarios(raw, args.host)

    fake = make_fake_psycopg2(mapped)
    real_import = __import__

    def fake_import(name, *a, **kw):
        if name == "psycopg2" or name.startswith("psycopg2."):
            sub = name.split(".", 2)
            return getattr(fake, sub[2], fake) if len(sub) > 2 else fake
        return real_import(name, *a, **kw)

    sys.modules["psycopg2"] = fake
    sys.modules["psycopg2.extensions"] = fake.extensions
    sys.modules["psycopg2.errors"] = fake.errors
    import builtins
    builtins.__import__ = fake_import

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("plugin_under_test", args.plugin)
        plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin)
    except FileNotFoundError:
        print(f"plugin not found: {args.plugin}")
        return 2
    finally:
        builtins.__import__ = real_import

    nodes = ",".join(f"{name}={args.host}:{port}" for name, port in ports.items())
    param = {"nodes": nodes, "username": "monitor", "password": "x", "db": "postgres"}
    payload = plugin.run(param)

    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if args.snapshot:
        with open(args.snapshot, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"snapshot written: {args.snapshot}")
    else:
        print(text)

    if args.time:
        print("\n-- statement timings (ms, match, result)", file=sys.stderr)
        for conn_host, node in mapped.items():
            if ":" not in conn_host:
                continue
            print(f"\n{conn_host}", file=sys.stderr)

    expect_down = bool(payload.get("msg"))
    status = payload.get("status")
    print(f"\nscenario={args.run} status={status} msg={str(payload.get('msg'))[:120]!r}", file=sys.stderr)
    return 0 if status in (0, 1) else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
