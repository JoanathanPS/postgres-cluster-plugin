"""Unit tests for postgres/postgres.py (plugin version 2)."""

import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "postgres"))

import postgres as pg  # noqa: E402

# Version 1 metric names that version 2 still sends (reference/postgres/postgres.py).
# v1-only metrics covered by newer ones, and running totals replaced by their
# "Per Sec" / "New ..." versions, are not sent (see V1_DROPPED).
V1_METRICS = [
    "Table Count", "Active Queries", "Active Waiting Queries", "Transactions Open",
    "Transactions Idle In Transaction", "Active Connections", "Total Commits",
    "Total Rollbacks", "Checkpoints Timed",
    "Checkpoint Write Time", "Checkpoint Sync Time", "Buffers Checkpoint", "Buffers Clean",
    "Maxwritten Clean", "Buffers Alloc", "Locks Count", "Max Connections",
    "Total Block Hits", "Server Version", "Uptime", "Database Count",
    "Total Sessions", "Total Sessions Abandoned", "Total Sessions Fatal",
    "Total Sessions Killed",
]
V1_DROPPED = ["Index Rows Read", "Index Rows Fetched", "Heap Blocks Read", "Heap Blocks Hit",
              "Cache Hit Ratio", "Total Rows Inserted", "Total Rows Updated",
              "Total Rows Deleted", "Total Rows Fetched", "Total Rows Returned",
              "Total Block Reads", "Index Scans", "Total Conflicts", "Checkpoints Req"]
V1_METRICS_BEFORE_17 = ["Buffers Backend", "Buffers Backend Fsync"]


class CatalogueTests(unittest.TestCase):

    def test_kept_v1_metrics_are_in_the_catalogue(self):
        names = {m.name for m in pg.all_metric_defs()}
        for name in V1_METRICS + V1_METRICS_BEFORE_17:
            self.assertIn(name, names)
        for name in V1_DROPPED:
            self.assertNotIn(name, names)

    def test_table_names(self):
        names = {t.name for t in pg.TABLES}
        self.assertIn("Stats_per_DB", names)
        self.assertIn("Transactions_and_Sessions_per_Database", names)   # v1's typo fixed

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

    def run_with(self, fail_on=None, error="permission denied for function pg_ls_waldir", prev=None,
                 first=False):
        """prev=None means a later poll of a known monitor; first=True its very first poll."""
        if prev is None:
            prev = {} if first else {"denied": []}
        fake = mock.Mock()
        fake.connect.return_value = FakeConn(fail_on, error)
        with mock.patch.object(pg, "psycopg2", fake), \
                mock.patch.object(pg, "HAVE_PSYCOPG2", True), \
                mock.patch.object(pg, "save_state", return_value=True), \
                mock.patch.object(pg, "load_state", return_value=prev), \
                mock.patch.object(pg, "RATE_SAMPLE_S", 0.6):
            return pg.run({"host": "h", "port": "5432", "username": "u", "password": "p"})

    def test_healthy_poll_is_up_and_valid(self):
        out = self.run_with()
        self.assertEqual(out["status"], 1)
        info = out["Cluster_Info"][0]                    # text values live in this table
        self.assertEqual(info["node_role"], "primary")
        self.assertTrue(info["cluster_type"])           # the fake server answers every probe
        for name in pg.CLUSTER_INFO_TEXT:
            self.assertNotIn(name, out)
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

    def test_unexpected_error_still_returns_valid_output(self):
        """The Linux agent calls run() directly, without the __main__ guard."""
        with mock.patch.object(pg, "collect", side_effect=RuntimeError("boom password=x")):
            out = pg.run({"host": "h"})
        self.assertEqual(out["status"], 0)
        self.assertIn("plugin error: boom", out["msg"])
        self.assertNotIn("password=x", out["msg"])

    def test_optional_table_failure_is_not_a_failed_query(self):
        """pg_stat_statements installed but not preloaded errors on every read."""
        top = next(t for t in pg.TABLES if t.name == "Top_Queries")
        with mock.patch.object(top, "when", lambda node: True):
            out = self.run_with(fail_on="pg_stat_statements WHERE",
                                error="pg_stat_statements must be loaded via shared_preload_libraries")
        self.assertEqual(out["Failed Queries"], 0)
        self.assertNotIn("Top_Queries", out)
        self.assertNotIn("msg", out)

    def test_archive_ready_needs_its_own_permission_only(self):
        archiver = next(q for q in pg.QUERIES if q.key == "archiver")
        ready = next(q for q in pg.QUERIES if q.key == "archive_ready")
        self.assertNotIn("pg_ls_archive_statusdir", archiver.pick((16, 0)).sql)
        self.assertIn("pg_ls_archive_statusdir", ready.pick((16, 0)).sql)
        self.assertIsNone(ready.pick((11, 0)))

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

    def test_later_poll_sends_real_counts_and_leaves_out_what_does_not_apply(self):
        out = self.run_with()          # fake server: primary, archive_mode off, a later poll
        for name in ("Archived Count", "Archive Ready Files"):
            self.assertEqual(out[name], 0, name)          # really nothing archived
        self.assertEqual(out["Archiving"], "Off")         # yes/no states are text
        self.assertEqual(out["WAL Receiver"], "Not a standby")
        for name in ("Last Archive Age", "Replay Lag", "Replay Backlog",
                     "Last WAL Message Age", "Max Standby Replay Lag", "Last Failover Age"):
            self.assertNotIn(name, out)                   # does not apply: "No Data"
        for name in pg.HIDDEN_COUNTERS:
            self.assertNotIn(name, out)                   # used for rates, not sent
        self.assertEqual(out["Index Hit Percent"], 1.0)   # fake server: a real value

    def test_first_poll_registers_every_metric_and_table(self):
        out = self.run_with(first=True)
        sent = {k for k in out if k not in pg.RESERVED_KEYS}
        names = {m.name for m in pg.all_metric_defs() if m.kind is not str}
        self.assertEqual(names - sent, set())
        for table in ("Replication_Links", "Events", "Top_Queries", "Cluster_Info", "Nodes"):
            self.assertTrue(out.get(table), table)
        self.assertEqual(pg.validate_output(out), [])
        self.assertEqual(out["Last Failover Age"], 0)      # stand-in, first poll only

class TruthfulZeroTests(unittest.TestCase):

    def test_archiving_on_keeps_real_values(self):
        node = mock.Mock(is_recovery=True, settings={"archive_mode": "on"})
        self.assertEqual(pg.truthful_zeros(node, {}), {})  # archiving on: only real counts
    def test_ages_are_never_zero_stand_ins(self):
        """A 0 age reads as "just happened" and silences "age above X" alerts."""
        for node in (mock.Mock(is_recovery=True, settings={"archive_mode": "on"}),
                     mock.Mock(is_recovery=False, settings={"archive_mode": "off"})):
            zeros = pg.truthful_zeros(node, {"Subscriptions": 0, "Tables Never Vacuumed": 0})
            for name in ("Last WAL Message Age", "Last Archive Age",
                         "Last Subscription Message Age", "Oldest Table Vacuum Age"):
                self.assertNotIn(name, zeros, name)
    def test_existing_values_are_never_overwritten(self):
        node = mock.Mock(is_recovery=False, settings={"archive_mode": "off"})
        self.assertNotIn("Archived Count", pg.truthful_zeros(node, {"Archived Count": 7}))

    def test_cluster_without_standbys_leaves_lag_out(self):
        view = pg.ClusterView([pg.node_row("a", "primary", "up", True)], links=None, primary_name="a")
        out = pg.cluster_metrics(view, "standalone", [], 100.0)
        self.assertEqual((out["Standbys Streaming"], out["Failovers 24h"]), (0, 0))   # real counts
        for name in ("Max Standby Replay Lag", "Max Standby Backlog", "Last Failover Age"):
            self.assertNotIn(name, out)                   # nothing to measure

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

    def test_citus_worker_finds_itself_by_group_not_address(self):
        """A worker reached at an address that differs from its pg_dist_node entry is
        still its own row, not an extra coordinator."""
        reg = [("citus-coordinator", 5432, 0, "primary", True),
               ("citus-worker1", 5432, 1, "primary", True),
               ("citus-worker2", 5432, 2, "primary", True)]
        seed = SeedStub(host="127.0.0.1", port=5481, answers={
            "pg_dist_local_group": [(1,)], "pg_dist_node": reg})
        rows = pg.CitusAdapter().nodes(seed, ctx_for(seed)).nodes
        self.assertEqual([(r["name"], r["role"]) for r in rows],
                         [("citus-coordinator", "coordinator"), ("citus-worker1", "worker"),
                          ("citus-worker2", "worker")])
        self.assertNotIn("_probe", rows[1])                          # matched as the seed

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


class PatroniHttpTests(unittest.TestCase):
    """fetch_json against a real local HTTP server."""

    def serve(self, need_auth=None):
        import http.server, threading, json as _json
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if need_auth and self.headers.get("Authorization") != need_auth:
                    self.send_response(401); self.end_headers(); return
                body = _json.dumps({"members": [{"name": "n1"}]}).encode()
                self.send_response(200); self.end_headers(); self.wfile.write(body)
            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def test_plain_http(self):
        port = self.serve()
        self.assertEqual(pg.fetch_json("127.0.0.1", port, "/cluster")["members"][0]["name"], "n1")

    def test_basic_auth_header_is_sent(self):
        import base64
        port = self.serve(need_auth="Basic " + base64.b64encode(b"mon:secret").decode())
        self.assertIsNone(pg.fetch_json("127.0.0.1", port, "/cluster"))      # refused without it
        out = pg.fetch_json("127.0.0.1", port, "/cluster", username="mon", password="secret")
        self.assertEqual(out["members"][0]["name"], "n1")

    def test_bad_client_cert_path_fails_softly(self):
        self.assertIsNone(pg.fetch_json("127.0.0.1", 1, "/cluster", scheme="https",
                                        certfile="/no/such/cert.pem"))

    def test_options_reach_the_args(self):
        a = pg.resolve_args({"patroni_cafile": "/etc/ca.pem", "patroni_username": "mon",
                             "patroni_password": '"secret"'})
        self.assertEqual((a["patroni_cafile"], a["patroni_username"], a["patroni_password"]),
                         ("/etc/ca.pem", "mon", "secret"))


class StandaloneNotApplicableTests(unittest.TestCase):

    def test_names_are_real_metrics(self):
        names = {m.name for m in pg.all_metric_defs()}
        self.assertEqual(pg.STANDALONE_NOT_APPLICABLE - names, set())

