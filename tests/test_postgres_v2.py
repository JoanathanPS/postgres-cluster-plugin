"""Unit tests for postgres/postgres.py (plugin version 2)."""

import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "postgres"))

import postgres as pg  # noqa: E402

# Metric names emitted by the version 1 plugin (reference/postgres/postgres.py).
# Version 2 must keep every one that the server version supports.
V1_METRICS = [
    "Table Count", "Active Queries", "Active Waiting Queries", "Transactions Open",
    "Transactions Idle In Transaction", "Active Connections", "Total Commits",
    "Total Rollbacks", "Total Conflicts", "Checkpoints Timed", "Checkpoints Req",
    "Checkpoint Write Time", "Checkpoint Sync Time", "Buffers Checkpoint", "Buffers Clean",
    "Maxwritten Clean", "Buffers Alloc", "Locks Count", "Max Connections",
    "Total Rows Inserted", "Total Rows Updated", "Total Rows Deleted", "Total Rows Fetched",
    "Total Rows Returned", "Total Block Reads", "Total Block Hits", "Index Scans",
    "Index Rows Read", "Index Rows Fetched", "Server Version", "Uptime", "Database Count",
    "Total Sessions", "Total Sessions Abandoned", "Total Sessions Fatal",
    "Total Sessions Killed", "Heap Blocks Read", "Heap Blocks Hit", "Cache Hit Ratio",
]
V1_METRICS_BEFORE_17 = ["Buffers Backend", "Buffers Backend Fsync"]


class CatalogueTests(unittest.TestCase):

    def test_every_v1_metric_is_in_the_catalogue(self):
        names = {m.name for m in pg.all_metric_defs()}
        for name in V1_METRICS + V1_METRICS_BEFORE_17:
            self.assertIn(name, names)

    def test_v1_table_names_are_kept(self):
        names = {t.name for t in pg.TABLES}
        self.assertIn("Stats_per_DB", names)
        self.assertIn("Tranasctions_and_Session_per_Database", names)

    def test_catalogue_fits_platform_limits(self):
        self.assertLessEqual(len(pg.all_metric_defs()), pg.MAX_METRICS)
        self.assertLessEqual(len(pg.TABLES), pg.MAX_TABLES)
        for t in pg.TABLES:
            self.assertLessEqual(len(t.units) + 1, pg.MAX_COLUMNS, t.name)

    def test_every_metric_has_a_known_tab(self):
        for m in pg.all_metric_defs():
            self.assertTrue(m.tab == "" or m.tab in pg.TAB_ORDER, m.name)
        for t in pg.TABLES:
            self.assertIn(t.tab, pg.TAB_ORDER)

    def test_variant_columns_match_fields(self):
        for q in pg.QUERIES:
            for v in q.variants:
                select = v.sql.split(" FROM pg_stat_activity")[0]
                self.assertTrue(v.fields, q.key)
                self.assertNotIn("%%", v.sql, q.key)
                self.assertTrue(select)

    def test_highest_applicable_variant_is_picked(self):
        q = next(q for q in pg.QUERIES if q.key == "bgwriter")
        self.assertIn("pg_stat_checkpointer", q.pick((17, 0)).sql)
        self.assertIn("buffers_backend", q.pick((16, 4)).sql)
        self.assertIsNone(next(q for q in pg.QUERIES if q.key == "sessions").pick((13, 0)))


class ValueTests(unittest.TestCase):

    def test_null_and_non_finite_values_are_dropped(self):
        self.assertIsNone(pg.to_number(None, int))
        self.assertIsNone(pg.to_number(float("nan"), float))
        self.assertIsNone(pg.to_number("abc", int))
        self.assertEqual(pg.to_number("42", int), 42)
        self.assertEqual(pg.to_number(1.23456, float), 1.2346)

    def test_cfg_values_are_unquoted_and_bounded(self):
        a = pg.resolve_args({"host": '"db1"', "port": '"99999"', "password": '"None"',
                             "heartbeat": "false"})
        self.assertEqual(a["host"], "db1")
        self.assertEqual(a["port"], 5432)
        self.assertEqual(a["password"], "")
        self.assertFalse(a["heartbeat"])

    def test_passwords_are_scrubbed(self):
        self.assertNotIn("hunter2", pg.scrub("connect failed password=hunter2 host=x"))


class RateTests(unittest.TestCase):

    def test_rate_needs_same_process_and_sane_interval(self):
        now = time.time()
        prev = {"ts": now - 60, "identity": "a", "counters": {"Total Commits": 100}}
        self.assertEqual(pg.compute_rates({"Total Commits": 160}, prev, now, "a")["Transactions Per Sec"], 1.0)
        self.assertEqual(pg.compute_rates({"Total Commits": 160}, prev, now, "b"), {})
        self.assertEqual(pg.compute_rates({"Total Commits": 160}, {}, now, "a"), {})

    def test_counter_reset_skips_rate(self):
        now = time.time()
        prev = {"ts": now - 60, "identity": "a", "counters": {"Total Commits": 500}}
        self.assertNotIn("Transactions Per Sec", pg.compute_rates({"Total Commits": 10}, prev, now, "a"))

    def test_delta_counts_events_since_last_poll(self):
        now = time.time()
        prev = {"ts": now - 300, "identity": "a", "counters": {"Total Deadlocks": 3}}
        self.assertEqual(pg.compute_rates({"Total Deadlocks": 5}, prev, now, "a")["New Deadlocks"], 2)


class PayloadTests(unittest.TestCase):

    def test_finalize_keeps_units_and_tabs_to_emitted_keys(self):
        """Repository rule: every key in `units` must exist in the data."""
        p = pg.base_payload(pg.resolve_args({}))
        p["Uptime"] = 10
        p["Locks Count"] = 3
        out = pg.finalize(p)
        self.assertEqual(out["tabs"]["Activity"]["tablist"], ["Locks Count"])
        self.assertEqual(set(out["units"]), {"Uptime", "Locks Count"})
        self.assertNotIn("Replay Lag", str(out["tabs"]))
        self.assertEqual(pg.validate_output(out), [])

    def test_validator_flags_limit_breaches(self):
        p = pg.finalize(pg.base_payload(pg.resolve_args({})))
        p["Stats_per_DB"] = [{"name": "db%d" % i} for i in range(26)]
        self.assertTrue(any("rows" in v for v in pg.validate_output(p)))

    def test_driver_missing_reports_down_with_install_hint(self):
        with mock.patch.object(pg, "HAVE_PSYCOPG2", False):
            out = pg.run({})
        self.assertEqual(out["status"], 0)
        self.assertIn("pip3 install psycopg2-binary", out["msg"])

    def test_connection_failure_reports_down_without_secrets(self):
        node = mock.Mock(auth_failed=False, error="timeout expired")
        node.connect.return_value = False
        with mock.patch.object(pg, "HAVE_PSYCOPG2", True), \
                mock.patch.object(pg, "Node", return_value=node):
            out = pg.run({"host": "db1", "port": "5433", "password": "hunter2"})
        self.assertEqual(out["status"], 0)
        self.assertIn("db1:5433", out["msg"])
        self.assertNotIn("hunter2", str(out))

    def test_missing_host_says_no_configuration_received(self):
        node = mock.Mock(auth_failed=False, error="refused")
        node.connect.return_value = False
        with mock.patch.object(pg, "HAVE_PSYCOPG2", True),                 mock.patch.object(pg, "Node", return_value=node):
            out = pg.run(pg.parse_cli([]))
        self.assertEqual(out["status"], 0)
        self.assertIn("no configuration received from agent", out["msg"])


class FakeCursor(object):
    """Answers each catalogue query with a row of 1s; tables get one row."""

    def __init__(self, fail_on=None, error="permission denied for function pg_ls_waldir"):
        self.fail_on = fail_on
        self.error = error
        self.description = None
        self.rows = []

    def execute(self, sql):
        if self.fail_on and self.fail_on in sql:
            raise Exception(self.error)
        if "pg_is_in_recovery(), current_setting('archive_mode')" in sql:
            self.rows = [(False, "off", "2026-11-23 00:00:00+00")]
        elif " AS name" in sql:
            self.description = [("name",), ("sessions",)]
            self.rows = [("db1", 1)]
        else:
            select = sql.split("FROM")[0]
            self.rows = [tuple(1 for _ in range(select.count(",") + 1))]

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeConn(object):
    server_version = 160004
    autocommit = False

    def __init__(self, fail_on=None, error="permission denied for function pg_ls_waldir"):
        self.fail_on = fail_on
        self.error = error

    def cursor(self):
        return FakeCursor(self.fail_on, self.error)

    def close(self):
        pass


class RunTests(unittest.TestCase):

    def run_with(self, fail_on=None, error="permission denied for function pg_ls_waldir", prev=None):
        fake = mock.Mock()
        fake.connect.return_value = FakeConn(fail_on, error)
        with mock.patch.object(pg, "psycopg2", fake), \
                mock.patch.object(pg, "HAVE_PSYCOPG2", True), \
                mock.patch.object(pg, "save_state", return_value=True), \
                mock.patch.object(pg, "load_state", return_value=prev or {}), \
                mock.patch.object(pg, "RATE_SAMPLE_S", 0.6):
            return pg.run({"host": "h", "port": "5432", "username": "u", "password": "p"})

    def test_healthy_poll_is_up_and_valid(self):
        out = self.run_with()
        self.assertEqual(out["status"], 1)
        self.assertEqual(out["Node Role"], "primary")
        self.assertEqual(out["Failed Queries"], 0)
        self.assertEqual(pg.validate_output(out), [])

    def test_failed_query_drops_only_its_metrics(self):
        out = self.run_with(fail_on="pg_ls_waldir", error="canceling statement due to statement timeout")
        self.assertEqual(out["status"], 1)
        self.assertNotIn("WAL Directory Size", out)
        self.assertIn("Total Commits", out)
        self.assertEqual(out["Failed Queries"], 1)
        self.assertEqual(out["Permission Gaps"], 0)
        self.assertIn("statement timeout", out["msg"])

    def test_permission_gap_is_reported_once_not_every_poll(self):
        first = self.run_with(fail_on="pg_ls_waldir")              # registration poll
        self.assertEqual((first["Failed Queries"], first["Permission Gaps"]), (0, 1))
        self.assertIn("function pg_ls_waldir", first["msg"])
        self.assertNotIn("WAL Directory Size", first)
        later = self.run_with(fail_on="pg_ls_waldir", prev={"denied": ["function pg_ls_waldir"]})
        self.assertEqual(later["Permission Gaps"], 1)               # still counted every poll
        self.assertNotIn("msg", later)                               # but no repeated text

    def test_resolved_permission_gap_is_announced(self):
        out = self.run_with(prev={"denied": ["function pg_ls_waldir"]})
        self.assertEqual(out["Permission Gaps"], 0)
        self.assertIn("resolved", out["msg"])

    def test_first_poll_samples_real_rates(self):
        """No previous state: rates come from two readings inside the poll, and the
        plugin's own commit between them is not counted as traffic."""
        out = self.run_with()
        self.assertEqual(out["Transactions Per Sec"], 0.0)
        self.assertIn("New Deadlocks", out)

    def test_truthful_zeros_are_sent_not_left_out(self):
        out = self.run_with()          # fake server: primary, archive_mode off
        for name in ("Archived Count", "Archive Failed Count", "Archiving Failing",
                     "Replay Lag", "Replay Backlog", "WAL Receiver Connected"):
            self.assertEqual(out[name], 0, name)
        self.assertEqual(out["Last Archive Age"], 0)     # pre-declared (TL decision)
        self.assertEqual(out["Cache Hit Ratio"], 1.0)     # no reads: no misses, not 0 % hits


class TruthfulZeroTests(unittest.TestCase):

    def test_standby_and_archiving_keep_real_values(self):
        node = mock.Mock(is_recovery=True, settings={"archive_mode": "on"})
        zeros = pg.truthful_zeros(node, {})
        self.assertNotIn("Replay Lag", zeros)            # a standby has a real replay lag
        self.assertNotIn("Archived Count", zeros)        # archiving on: real counts
        self.assertEqual((zeros["WAL Generated Per Sec"], zeros["WAL Written"]), (0.0, 0.0))

    def test_existing_values_are_never_overwritten(self):
        node = mock.Mock(is_recovery=False, settings={"archive_mode": "off"})
        self.assertNotIn("Archived Count", pg.truthful_zeros(node, {"Archived Count": 7}))

    def test_cluster_without_standbys_reports_zero_lag(self):
        view = pg.ClusterView([pg.node_row("a", "primary", "up", True)], links=None, primary_name="a")
        out = pg.cluster_metrics(view, "standalone", [], 100.0)
        self.assertEqual((out["Standbys Streaming"], out["Max Standby Replay Lag"], out["Failovers 24h"]),
                         (0, 0.0, 0))
        self.assertNotIn("Last Failover Age", out)      # no start time given
        out = pg.cluster_metrics(view, "standalone", [], 100.0, since=40.0)
        self.assertEqual(out["Last Failover Age"], 60)   # "none for at least 60 s", never 0


def row(name, role, status=1):
    return pg.node_row(name, role, "up" if status else "down", status)


class ClusterLogicTests(unittest.TestCase):

    def test_address_map_translates_host_and_host_port(self):
        amap = pg.parse_address_map("10.0.0.5:5432=127.0.0.1:5441, pg2=127.0.0.1:5442,bad")
        self.assertEqual(pg.map_address("10.0.0.5", 5432, amap), ("127.0.0.1", 5441))
        self.assertEqual(pg.map_address("pg2", 5432, amap), ("127.0.0.1", 5442))
        self.assertEqual(pg.map_address("10.0.0.9", 5432, amap), ("10.0.0.9", 5432))

    def test_first_poll_records_no_events(self):
        self.assertEqual(pg.detect_events([row("a", "primary")], {}, [], 100.0), [])

    def test_failover_produces_down_and_promoted(self):
        prev = {"a": {"role": "primary", "status": 1}, "b": {"role": "standby", "status": 1}}
        rows = [row("b", "primary")]
        forgotten = pg.merge_remembered(rows, {k: dict(v, last_seen=90.0) for k, v in prev.items()}, 100.0)
        events = pg.detect_events(rows, prev, forgotten, 100.0)
        kinds = {(e["event"], e["node"]) for e in events}
        self.assertIn(("promoted", "b"), kinds)
        self.assertIn(("down", "a"), kinds)
        missing = next(r for r in rows if r["name"] == "a")
        self.assertEqual((missing["status"], missing["state"]), (0, "down"))

    def test_missing_standby_is_not_streaming_then_forgotten(self):
        prev = {"s1": {"role": "standby", "status": 1, "last_seen": 0.0}}
        rows = [row("p", "primary")]
        self.assertEqual(pg.merge_remembered(rows, prev, 60.0), [])
        self.assertEqual(rows[-1]["state"], "not streaming")
        rows = [row("p", "primary")]
        self.assertEqual(pg.merge_remembered(rows, prev, pg.NODE_FORGET_S + 1.0), ["s1"])

    def test_same_server_under_two_names_is_not_split_brain(self):
        """Found on the real agent: the primary was remembered as 'pg-primary' (its
        hostname, seen from a standby) and is now listed by IP. Same server, one row."""
        live = pg.node_row("172.18.0.2", "primary", "up", True, address="127.0.0.1:5432")
        live["_fp"] = "2026-11-24 06:00:00+00"
        rows = [live, row("172.18.0.3", "standby")]
        prev = {"pg-primary": {"role": "primary", "status": 1, "last_seen": 90.0,
                               "address": "127.0.0.1:5432"}}
        pg.merge_remembered(rows, prev, 100.0)            # same address: old name dropped
        self.assertEqual([r["name"] for r in rows], ["172.18.0.2", "172.18.0.3"])
        ghost = pg.node_row("pg-primary", "primary", "up", True, address="pg-primary:5432")
        ghost.update({"_fp": "2026-11-24 06:00:00+00", "last_seen_s": 10})
        rows.append(ghost)                                 # different address, same server
        pg.dedupe_nodes(rows)
        self.assertNotIn("pg-primary", [r["name"] for r in rows])
        self.assertEqual(pg.evaluate_health(rows, "streaming")[0], pg.HEALTH_OK)

    def test_recovered_node_is_an_event(self):
        prev = {"s1": {"role": "standby", "status": 0}}
        events = pg.detect_events([row("s1", "standby")], prev, [], 1.0)
        self.assertEqual(events[0]["event"], "recovered")

    def test_health_rules(self):
        self.assertEqual(pg.evaluate_health([row("a", "primary"), row("b", "standby")], "streaming")[0],
                         pg.HEALTH_OK)
        self.assertEqual(pg.evaluate_health([row("a", "primary"), row("b", "primary")], "streaming")[0],
                         pg.HEALTH_SPLIT_BRAIN)
        self.assertEqual(pg.evaluate_health([row("a", "primary", 0), row("b", "standby")], "streaming")[0],
                         pg.HEALTH_NO_PRIMARY)
        self.assertEqual(pg.evaluate_health([row("a", "primary"), row("b", "standby", 0)], "streaming")[0],
                         pg.HEALTH_NODE_DOWN)
        self.assertEqual(pg.evaluate_health([row("a", "standby")], "standalone")[0], pg.HEALTH_OK)

    def test_down_nodes_survive_the_row_limit(self):
        rows = [row("n%02d" % i, "standby") for i in range(30)] + [row("zz-down", "standby", 0)]
        out = pg.public_rows(rows)
        self.assertEqual(len(out), pg.MAX_ROWS)
        self.assertEqual(out[0]["name"], "zz-down")

    def test_cluster_tables_fit_limits(self):
        history = [{"ts": float(i), "event": "promoted", "node": "node-%d" % i,
                    "old_role": "standby", "new_role": "primary"} for i in range(40)]
        payload = {"status": 1, "Events": pg.event_rows(history, 100.0),
                   "Nodes": pg.public_rows([row("a", "primary")])}
        self.assertEqual(pg.validate_output(payload), [])
        self.assertEqual(len(payload["Events"]), pg.MAX_ROWS)

    def test_failover_metrics(self):
        view = pg.ClusterView([row("b", "primary"), row("a", "standby", 0)], links=[], primary_name="b")
        hist = [{"ts": 40.0, "event": "promoted", "node": "b", "old_role": "standby", "new_role": "primary"}]
        out = pg.cluster_metrics(view, "streaming", hist, 100.0)
        self.assertEqual(out["Last Failover Age"], 60)
        self.assertEqual(out["Failovers 24h"], 1)
        self.assertEqual(out["Cluster Health"], 1)
        self.assertEqual(out["Primary Node"], "b")


class SeedStub(object):
    """Minimal seed node for adapter tests."""

    def __init__(self, host="10.0.0.1", port=5432, recovery=False, answers=None):
        self.host, self.port, self.dbname = host, port, "postgres"
        self.is_recovery, self.version, self.failures = recovery, (16, 0), []
        self.denied = []
        self.answers = answers or {}
        self.conn = None

    @property
    def role(self):
        return "standby" if self.is_recovery else "primary"

    def query_all(self, sql):
        for key, val in self.answers.items():
            if key in sql:
                return val
        return []

    def query_one(self, sql):
        rows = self.query_all(sql)
        return rows[0] if rows else ()


def ctx_for(seed, **extra):
    ctx = {"metrics": {}, "address_map": {}, "args": {"patroni_port": 8008},
           "connect": lambda *a, **k: None, "now": 1000.0, "prev_cluster": {},
           "state_extra": {}, "remembered": []}
    ctx.update(extra)
    return ctx


class AdapterTests(unittest.TestCase):

    def test_patroni_members_become_rows_and_seed_is_matched(self):
        seed = SeedStub(host="pg-node1", recovery=True,
                        answers={"inet_server_addr": [("172.30.0.11",)]})
        cluster = {"members": [
            {"name": "pg-node1", "role": "replica", "state": "streaming", "host": "pg-node1",
             "port": 5432, "timeline": 7, "lag": 1048576},
            {"name": "pg-node2", "role": "leader", "state": "running", "host": "pg-node2",
             "port": 5432, "timeline": 7},
            {"name": "pg-node3", "role": "replica", "state": "stopped", "host": "pg-node3", "port": 5432}]}
        with mock.patch.object(pg, "fetch_json", return_value=cluster):
            ctx = ctx_for(seed)
            adapter = pg.PatroniAdapter()
            self.assertTrue(adapter.detect(seed, ctx))
            view = adapter.nodes(seed, ctx)
        rows = {r["name"]: r for r in view.nodes}
        self.assertEqual(view.primary_name, "pg-node2")
        self.assertEqual(rows["pg-node1"]["reachable"], 1)          # the seed itself
        self.assertEqual(rows["pg-node1"]["backlog_mb"], 1.0)
        self.assertEqual(rows["pg-node3"]["status"], 0)
        self.assertEqual(rows["pg-node2"]["_probe"], ("pg-node2", 5432))

    def test_repmgr_conninfo_without_port_means_5432(self):
        """Seed reached on a mapped port (127.0.0.1:5462) must still be recognised as
        the registry's node whose conninfo has no port (i.e. 5432)."""
        seed = SeedStub(host="127.0.0.1", port=5462, answers={
            "shared_preload_libraries": [("repmgr",)],
            "repmgr.nodes": [("repmgr-node2", "host=repmgr-node2 user=repmgr dbname=repmgr", "primary", True),
                             ("repmgr-node1", "host=repmgr-node1 user=repmgr dbname=repmgr", "standby", True)],
            "pg_stat_replication": [],
        })
        seed.dbname = "repmgr"
        ctx = ctx_for(seed, address_map={"repmgr-node2:5432": "127.0.0.1:5462",
                                         "repmgr-node1:5432": "127.0.0.1:5461"})
        rows = {r["name"]: r for r in pg.RepmgrAdapter().nodes(seed, ctx).nodes}
        self.assertNotIn("_probe", rows["repmgr-node2"])            # matched as the seed
        self.assertEqual(rows["repmgr-node1"]["_probe"], ("127.0.0.1", 5461))

    def test_registry_clusters_get_links_from_the_primary(self):
        """pgpool / pg_auto_failover list nodes but not links: ask the primary."""
        link = ("walreceiver", "10.0.0.2", "streaming", "async", 0, 0, 0, 0.5, None, None, 1.5, "5432")
        seed = SeedStub(answers={"pg_stat_replication": [link]})
        rows = [pg.node_row("pgp-pg1:5432", "primary", "up", True),
                pg.node_row("pgp-pg2:5432", "standby", "up", True)]
        view = pg.ClusterView(rows, links=None, primary_name="pgp-pg1:5432")
        pg.fill_links_from_primary(view, seed, ctx_for(seed))
        self.assertEqual(len(view.links), 1)
        out = pg.cluster_metrics(view, "pgpool", [], 100.0)
        self.assertEqual((out["Standbys Streaming"], out["Max Standby Replay Lag"]), (1, 1.5))

    def test_patroni_needs_a_configured_port(self):
        self.assertFalse(pg.PatroniAdapter().detect(SeedStub(), ctx_for(SeedStub(), args={})))

    def test_manager_disagreement_is_reported(self):
        r = pg.node_row("n1", "standby", "up", True)
        r.update({"_claimed": "primary", "reachable": 1})
        rows = [pg.node_row("n0", "primary", "up", True), r]
        self.assertEqual(pg.evaluate_health(rows, "patroni")[0], pg.HEALTH_MANAGER_DISAGREES)

    def test_multi_writer_clusters_skip_primary_rules(self):
        rows = [pg.node_row("a", "writer", "up", True), pg.node_row("b", "writer", "up", True)]
        self.assertEqual(pg.evaluate_health(rows, "logical", single_writer=False)[0], pg.HEALTH_OK)
        rows = [pg.node_row("c", "coordinator", "up", True), pg.node_row("w", "worker", "down", False)]
        self.assertEqual(pg.evaluate_health(rows, "citus", single_writer=False)[0], pg.HEALTH_NODE_DOWN)

    def test_pgpool_probe_is_retried_at_most_daily(self):
        seed = SeedStub()
        ctx = ctx_for(seed, prev_cluster={"pgpool": False, "pgpool_checked": 900.0})
        self.assertFalse(pg.PgpoolAdapter().detect(seed, ctx))
        self.assertNotIn("pgpool_checked", ctx["state_extra"])

    def test_quiet_query_does_not_count_as_failure(self):
        seed = SeedStub()
        seed.query_all = lambda sql: seed.failures.append("boom")
        pg.quiet_query(seed, "SELECT 1", all_rows=True)
        self.assertEqual(seed.failures, [])


class EventsLogTests(unittest.TestCase):

    def test_log_stays_in_plugin_folder(self):
        path = pg.log_path({"log_file_path": "../../etc/evil.log"})
        self.assertEqual(os.path.dirname(path), pg.PLUGIN_DIR)
        self.assertEqual(os.path.basename(path), "evil.log")

    def test_log_rotates(self):
        import tempfile
        d = tempfile.mkdtemp()
        path = os.path.join(d, "events.log")
        with open(path, "w") as fh:
            fh.write("x" * (pg.LOG_MAX_BYTES + 1))
        pg.write_events_log(path, [{"ts": 0.0, "event": "down", "node": "a",
                                    "old_role": "primary", "new_role": "primary"}], "c1")
        self.assertTrue(os.path.exists(path + ".1"))
        with open(path) as fh:
            self.assertIn("event=down", fh.read())


if __name__ == "__main__":
    unittest.main()
