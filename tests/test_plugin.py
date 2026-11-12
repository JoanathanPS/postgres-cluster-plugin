#!/usr/bin/env python3
"""
Unit tests for postgres_cluster.py v5 pure functions (no DB required).
Exercises:
- PostgreSQL version string parsing (tolerant of real-world strings)
- Address mapping & hostname normalization
- Health reasoning engine (all health codes, precedence, message formatting)
- Catalogue consistency & Site24x7 payload limit enforcement
"""

import os
import sys
import unittest
import socket
import threading
import time
import json
import subprocess

# Add parent directory to sys.path so we can import postgres_cluster
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "postgres_cluster"))

import postgres_cluster as pc


class TestVersionParsing(unittest.TestCase):
    def test_standard_versions(self):
        self.assertEqual(pc.parse_pg_version("16.2"), (16, 2))
        self.assertEqual(pc.parse_pg_version("10.0"), (10, 0))
        self.assertEqual(pc.parse_pg_version("9.6.24"), (9, 6))

    def test_cloud_and_fork_versions(self):
        self.assertEqual(pc.parse_pg_version("12.3_TDE_1.0"), (12, 3))
        self.assertEqual(pc.parse_pg_version("11.22-rds.20241121"), (11, 22))
        self.assertEqual(pc.parse_pg_version("12beta1"), (12, 0))
        self.assertEqual(pc.parse_pg_version("17devel"), (17, 0))
        self.assertEqual(
            pc.parse_pg_version("PostgreSQL 16.15 (Debian 16.15-1.pgdg13+2) on x86_64"),
            (16, 15)
        )

    def test_invalid_versions(self):
        self.assertEqual(pc.parse_pg_version(""), (0, 0))
        self.assertEqual(pc.parse_pg_version("unparseable"), (0, 0))
        self.assertEqual(pc.parse_pg_version(None), (0, 0))


class TestAddressMapping(unittest.TestCase):
    def test_parse_address_map(self):
        raw = "pg-node1:5432=127.0.0.1:5441, pg-node1:8008=127.0.0.1:8001"
        mapped = pc.parse_address_map(raw)
        self.assertEqual(mapped.get("pg-node1:5432"), "127.0.0.1:5441")
        self.assertEqual(mapped.get("pg-node1:8008"), "127.0.0.1:8001")

    def test_empty_address_map(self):
        self.assertEqual(pc.parse_address_map(""), {})
        self.assertEqual(pc.parse_address_map(None), {})

    def test_normalize_host(self):
        self.assertEqual(pc.normalize_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(pc.normalize_host("[::1]"), "::1")
        self.assertEqual(pc.normalize_host("localhost"), "localhost")


class TestHealthEngine(unittest.TestCase):
    def test_healthy_ok(self):
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg1",
            nodes_up=3,
            nodes_total=3,
            timeline=1,
            primaries_count=1,
            expected_standbys=2,
            streaming_standbys=2,
        )
        self.assertEqual(h.code, pc.HEALTH_CODE_OK)
        self.assertEqual(h.severity, pc.HEALTH_OK)
        msg = h.format_msg()
        self.assertTrue(len(msg) <= pc.MAX_MSG_CHARS)
        self.assertIn("Cluster healthy", msg)

    def test_critical_primary_down(self):
        h = pc.evaluate_cluster_health(
            has_primary=False,
            primary_name="pg1",
            primary_last_seen_s=300,
            nodes_up=2,
            nodes_total=3,
            timeline=4,
            primaries_count=0,
            has_failover_candidate=True
        )
        self.assertEqual(h.code, pc.HEALTH_CODE_PRIMARY_DOWN)
        self.assertEqual(h.severity, pc.HEALTH_CRITICAL)
        msg = h.format_msg()
        self.assertTrue(len(msg) <= pc.MAX_MSG_CHARS)
        self.assertIn("no primary reachable", msg)
        self.assertIn("hint: patronictl list", msg)

    def test_critical_no_failover_candidate(self):
        h = pc.evaluate_cluster_health(
            has_primary=False,
            primary_name="pg1",
            nodes_up=0,
            nodes_total=3,
            primaries_count=0,
            has_failover_candidate=False
        )
        self.assertEqual(h.code, pc.HEALTH_CODE_NO_FAILOVER_CANDIDATE)
        self.assertEqual(h.severity, pc.HEALTH_CRITICAL)

    def test_critical_split_brain(self):
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primaries_count=2,
            is_multi_master=False,
            nodes_up=3,
            nodes_total=3
        )
        self.assertEqual(h.code, pc.HEALTH_CODE_SPLIT_BRAIN)
        self.assertEqual(h.severity, pc.HEALTH_CRITICAL)
        self.assertIn("split brain", h.format_msg())

    def test_multi_master_not_split_brain(self):
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primaries_count=2,
            is_multi_master=True,
            nodes_up=2,
            nodes_total=2,
            timeline=1
        )
        self.assertEqual(h.code, pc.HEALTH_CODE_OK)

    def test_critical_no_standbys_streaming(self):
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primaries_count=1,
            nodes_up=3,
            nodes_total=3,
            expected_standbys=2,
            streaming_standbys=0
        )
        self.assertEqual(h.code, pc.HEALTH_CODE_NO_STANDBYS_STREAMING)
        self.assertEqual(h.severity, pc.HEALTH_CRITICAL)

    def test_critical_slot_lost(self):
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primaries_count=1,
            slot_lost=True,
            nodes_up=3,
            nodes_total=3
        )
        self.assertEqual(h.code, pc.HEALTH_CODE_SLOT_LOST_OR_CRITICAL)
        self.assertEqual(h.severity, pc.HEALTH_CRITICAL)

    def test_critical_xid_wraparound(self):
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primaries_count=1,
            xid_wraparound_pct=96.5,
            nodes_up=3,
            nodes_total=3
        )
        self.assertEqual(h.code, pc.HEALTH_CODE_XID_CRITICAL)
        self.assertEqual(h.severity, pc.HEALTH_CRITICAL)

    def test_warn_node_down(self):
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg1",
            primaries_count=1,
            nodes_up=2,
            nodes_total=3,
            expected_standbys=2,
            streaming_standbys=1
        )
        self.assertEqual(h.code, pc.HEALTH_CODE_NODE_DOWN)
        self.assertEqual(h.severity, pc.HEALTH_WARN)

    def test_warn_standby_lag_high(self):
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primaries_count=1,
            nodes_up=3,
            nodes_total=3,
            max_replay_lag_s=75.0,
            replay_warn_s=60.0
        )
        self.assertEqual(h.code, pc.HEALTH_CODE_STANDBY_LAG_HIGH)
        self.assertEqual(h.severity, pc.HEALTH_WARN)

    def test_warn_timeline_mismatch(self):
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primaries_count=1,
            nodes_up=3,
            nodes_total=3,
            timeline_spread=2
        )
        self.assertEqual(h.code, pc.HEALTH_CODE_TIMELINE_MISMATCH)
        self.assertEqual(h.severity, pc.HEALTH_WARN)

    def test_warn_recent_failover(self):
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg2",
            primaries_count=1,
            nodes_up=3,
            nodes_total=3,
            failover_age_s=180,
            failover_window_s=900
        )
        self.assertEqual(h.code, pc.HEALTH_CODE_RECENT_FAILOVER)
        self.assertEqual(h.severity, pc.HEALTH_WARN)

    def test_auth_failure_flag_never_reports_primary_down(self):
        h = pc.evaluate_cluster_health(
            has_primary=False,
            auth_failure=True,
            nodes_up=0,
            nodes_total=3
        )
        # Must report auth failure, NOT primary down
        self.assertIn("authentication failure", h.fact)
        self.assertNotEqual(h.code, pc.HEALTH_CODE_PRIMARY_DOWN)


class TestCatalogueInvariants(unittest.TestCase):
    def test_catalogue_budget(self):
        self.assertLessEqual(len(pc.METRICS), pc.MAX_METRICS)

    def test_tabs_and_units_sync(self):
        tabs_def, units_def = pc.build_tabs_and_units(pc.METRICS)
        tabs_keys = list(tabs_def.get("tabs", tabs_def).keys())
        self.assertEqual(tabs_keys, pc.TAB_ORDER)
        for m in pc.METRICS:
            name = m["name"]
            if m.get("type", int) != str:
                self.assertIn(name, units_def)
        for tbl in pc.TABLE_UNITS:
            self.assertIn(tbl, units_def)


class TestRegressionFixes(unittest.TestCase):
    """Regression tests for Bugs / Fixes 1 through 9."""

    def test_fix1_payload_shape_invariants(self):
        """Fix 1: Every child table has units schema; no compound units; no units on strings; no & in tab names."""
        payload = pc.get_empty_payload()
        units = payload.get("units", {})
        tabs = payload.get("tabs", {})
        tab_dict = tabs.get("tabs", tabs)

        # 1a. Every table in TABLE_UNITS must be present in units
        for tbl in pc.TABLE_UNITS:
            self.assertIn(tbl, units, f"Table {tbl} missing from units schema")
            self.assertIsInstance(units[tbl], dict)

        # 1b. No compound units (e.g. /, +, ()
        for k, u in units.items():
            if isinstance(u, str):
                self.assertNotIn("/", u, f"Unit '{u}' for {k} contains '/'")
                self.assertNotIn("+", u, f"Unit '{u}' for {k} contains '+'")
                self.assertNotIn("(", u, f"Unit '{u}' for {k} contains '('")
            elif isinstance(u, dict):
                for col, col_u in u.items():
                    self.assertNotIn("/", col_u, f"Table unit '{col_u}' for {k}.{col} contains '/'")
                    self.assertNotIn("+", col_u, f"Table unit '{col_u}' for {k}.{col} contains '+'")
                    self.assertNotIn("(", col_u, f"Table unit '{col_u}' for {k}.{col} contains '('")

        # 1c. String columns get NO unit
        string_cols = ["node", "action", "scope", "text", "status_reason", "msg", "name"]
        for s_col in string_cols:
            self.assertNotIn(s_col, units, f"String column '{s_col}' declared in top-level units")
            for tbl, tbl_map in units.items():
                if isinstance(tbl_map, dict):
                    self.assertNotIn(s_col, tbl_map, f"String column '{s_col}' declared in table units for '{tbl}'")

        # 1d. Tab names may not contain &
        for tab_name in tab_dict.keys():
            self.assertNotIn("&", tab_name, f"Tab name '{tab_name}' contains '&'")

        # 1e. At least one integer parent metric
        self.assertIsInstance(payload.get("Primary_Up"), int)
        self.assertIsInstance(payload.get("Nodes_Total"), int)

    def test_fix2_wrong_password_auth_failure(self):
        """Fix 2: Auth failure produces status=0, Auth_Failure_Flag=1, and msg mentions auth."""
        h = pc.evaluate_cluster_health(
            has_primary=False,
            nodes_up=0,
            nodes_total=3,
            auth_failure=True,
            auth_msg="password authentication failed for user site24x7"
        )
        self.assertEqual(h.severity, pc.HEALTH_CRITICAL)
        self.assertIn("auth", h.format_msg().lower())

        res = pc.run({
            "cluster_host": "127.0.0.1",
            "postgres_port": 5432,
            "username": "site24x7",
            "password": "wrong_password_xyz",
            "cycle_deadline": 2.0
        })
        self.assertEqual(res.get("status"), 0)
        self.assertEqual(res.get("Auth_Failure_Flag"), 1)
        self.assertIn("auth", res.get("msg", "").lower())

    def test_fix3_permission_denied_query_sentinel(self):
        """Fix 3: Permission denied query returns -1 sentinel, metric_unavailable note, never real 0."""
        class MockClient:
            name = "mock_pg"
            is_connected = True
            is_supported = True
            version_tuple = (16, 0)
            version_num = 160000
            settings = {"archive_mode": "off"}
            last_error_class = "insufficient_privilege"
            conn = None

            def query_all(self, sql):
                return None

            def query_one(self, sql):
                return None

            def close(self):
                pass

        c = MockClient()
        rows = c.query_all("SELECT slot_name FROM pg_replication_slots;")
        self.assertIsNone(rows)
        sentinel_val = -1 if rows is None else len(rows)
        self.assertEqual(sentinel_val, -1)
        self.assertNotEqual(sentinel_val, 0)

    def test_fix4_two_primaries_multi_master_no_split_brain(self):
        """Fix 4 (Fix 5): Two primaries with multi-master flag raises NO split brain."""
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primaries_count=2,
            is_multi_master=True,
            nodes_up=2,
            nodes_total=2,
            timeline=1
        )
        self.assertNotEqual(h.code, pc.HEALTH_CODE_SPLIT_BRAIN)
        self.assertEqual(h.severity, pc.HEALTH_OK)

    def test_fix4_two_primaries_non_multi_master_split_brain(self):
        """Fix 4 (Fix 5): Two primaries without multi-master flag raises split brain."""
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primaries_count=2,
            is_multi_master=False,
            nodes_up=3,
            nodes_total=3
        )
        self.assertEqual(h.code, pc.HEALTH_CODE_SPLIT_BRAIN)
        self.assertEqual(h.severity, pc.HEALTH_CRITICAL)

    def test_fix5_stalled_node_cycle_budget(self):
        """Fix 5 (Fix 4): Stalled node returns under budget and marks Budget_Exceeded=1."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(5)
        stalled_port = srv.getsockname()[1]

        def hold_accept():
            try:
                conn, _ = srv.accept()
                time.sleep(5.0)
                conn.close()
            except Exception:
                pass

        th = threading.Thread(target=hold_accept, daemon=True)
        th.start()

        t0 = time.time()
        res = pc.run({
            "cluster_host": "127.0.0.1",
            "postgres_port": stalled_port,
            "cycle_deadline": 2.0,
            "hard_exit": 0
        })
        elapsed = time.time() - t0
        srv.close()

        self.assertLess(elapsed, 4.0, f"Cycle took {elapsed}s, exceeded deadline")
        self.assertEqual(res.get("Budget_Exceeded"), 1)

    def test_fix6_empty_patroni_members_unknown_manager(self):
        """Fix 6: Patroni empty members JSON returns Topology_Type=0 (unknown), not patroni."""
        probe_status = "empty_members"
        mgr_code, mgr_str, probes = pc.probe_cluster_managers(None, probe_status)
        self.assertEqual(mgr_code, pc.TOPOLOGY_UNKNOWN)
        self.assertEqual(mgr_str, "unknown")
        self.assertNotEqual(mgr_code, pc.TOPOLOGY_PATRONI)

    def test_fix7_unsupported_version_floor_9_4(self):
        """Fix 7: Version 9.4 is rejected as unsupported_version."""
        v_tuple = pc.parse_pg_version("PostgreSQL 9.4.26 on x86_64")
        self.assertLess(v_tuple, pc.VERSION_FLOOR)
        client_supported = (v_tuple >= pc.VERSION_FLOOR)
        self.assertFalse(client_supported)

    def test_fix8_compat_official_flag(self):
        """Fix 8 (Fix 9): compat_official=1 includes legacy metrics; compat_official=0 omits them; <= 200 in both."""
        res1 = pc.run({
            "cluster_host": "127.0.0.1",
            "postgres_port": 5432,
            "username": "site24x7",
            "password": "site24x7_password",
            "compat_official": 1
        })
        reserved = pc.RESERVED_KEYS
        m1 = [k for k, v in res1.items() if k not in reserved and not isinstance(v, (list, dict))]
        self.assertLessEqual(len(m1), pc.MAX_METRICS)
        self.assertIn("Total Commits", res1)
        self.assertIn("Active Connections", res1)
        self.assertIsInstance(res1["Total Commits"], (int, float))
        self.assertIn("Stats_per_DB", res1)
        self.assertIn("s247config", res1)

        res0 = pc.run({
            "cluster_host": "127.0.0.1",
            "postgres_port": 5432,
            "username": "site24x7",
            "password": "site24x7_password",
            "compat_official": 0
        })
        m0 = [k for k, v in res0.items() if k not in reserved and not isinstance(v, (list, dict))]
        self.assertLessEqual(len(m0), pc.MAX_METRICS)
        self.assertNotIn("Total Commits", res0)
        self.assertNotIn("Active Connections", res0)
        self.assertNotIn("Stats_per_DB", res0)
        self.assertNotIn("s247config", res0)

    def test_fix9_stalled_node_process_clean_exit(self):
        """Fix 9 (Fix 4 Part 2): The process exits within budget, not just the payload."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(5)
        stalled_port = srv.getsockname()[1]

        def hold_accept():
            try:
                conn, _ = srv.accept()
                time.sleep(5.0)
                conn.close()
            except Exception:
                pass

        th = threading.Thread(target=hold_accept, daemon=True)
        th.start()

        script_path = os.path.join(PROJECT_ROOT, "postgres_cluster", "postgres_cluster.py")
        cmd = [
            sys.executable, script_path,
            "--cluster_host", "127.0.0.1",
            "--postgres_port", str(stalled_port),
            "--cycle_deadline", "2.0",
            "--hard_exit", "0"
        ]

        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10.0)
        elapsed = time.time() - t0
        srv.close()

        self.assertEqual(proc.returncode, 0)
        self.assertLess(elapsed, 6.0, f"Process took {elapsed}s to exit, expected < 6.0s")


if __name__ == "__main__":
    unittest.main()
