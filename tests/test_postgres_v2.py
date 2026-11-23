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

    def test_finalize_removes_unemitted_tab_entries(self):
        p = pg.base_payload(pg.resolve_args({}))
        p["Uptime"] = 10
        p["Locks Count"] = 3
        out = pg.finalize(p)
        self.assertEqual(out["tabs"]["Activity"]["tablist"], ["Locks Count"])
        self.assertNotIn("BG Writer", out["tabs"])
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


class FakeCursor(object):
    """Answers each catalogue query with a row of 1s; tables get one row."""

    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.description = None
        self.rows = []

    def execute(self, sql):
        if self.fail_on and self.fail_on in sql:
            raise Exception("permission denied for function pg_ls_waldir")
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

    def __init__(self, fail_on=None):
        self.fail_on = fail_on

    def cursor(self):
        return FakeCursor(self.fail_on)

    def close(self):
        pass


class RunTests(unittest.TestCase):

    def run_with(self, fail_on=None):
        fake = mock.Mock()
        fake.connect.return_value = FakeConn(fail_on)
        with mock.patch.object(pg, "psycopg2", fake), \
                mock.patch.object(pg, "HAVE_PSYCOPG2", True), \
                mock.patch.object(pg, "save_state", return_value=True), \
                mock.patch.object(pg, "load_state", return_value={}):
            return pg.run({"host": "h", "port": "5432", "username": "u", "password": "p"})

    def test_healthy_poll_is_up_and_valid(self):
        out = self.run_with()
        self.assertEqual(out["status"], 1)
        self.assertEqual(out["Node Role"], "primary")
        self.assertEqual(out["Failed Queries"], 0)
        self.assertEqual(pg.validate_output(out), [])

    def test_failed_query_drops_only_its_metrics(self):
        out = self.run_with(fail_on="pg_ls_waldir")
        self.assertEqual(out["status"], 1)
        self.assertNotIn("WAL Directory Size", out)
        self.assertIn("Total Commits", out)
        self.assertEqual(out["Failed Queries"], 1)
        self.assertIn("permission denied", out["msg"])

    def test_first_poll_has_no_rates(self):
        out = self.run_with()
        self.assertNotIn("Transactions Per Sec", out)
        self.assertNotIn("Transactions Per Sec", str(out["tabs"]))


if __name__ == "__main__":
    unittest.main()
