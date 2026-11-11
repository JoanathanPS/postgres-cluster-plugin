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
        self.assertEqual(list(tabs_def["tabs"].keys()), pc.TAB_ORDER)
        for m in pc.METRICS:
            name = m["name"]
            self.assertIn(name, units_def)


if __name__ == "__main__":
    unittest.main()
