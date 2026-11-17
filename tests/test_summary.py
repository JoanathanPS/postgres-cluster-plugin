#!/usr/bin/env python3
"""
Unit and integration tests for PostgreSQL Cluster Plugin Summary Tab Redesign.

Verifies:
  1. Summary Metric Selection & Tab Placement (untabbed whitelist promotion).
  2. Output validation with strict EMITTED_METRIC_NO_TAB and whitelist support.
  3. Structured message generation and 180-character ceiling compliance.
  4. Fully healthy cluster state (0 = HEALTHY).
  5. Degraded cluster: one replica unavailable (1 = DEGRADED).
  6. Critical outage: primary unavailable (2 = CRITICAL).
  7. Successful automatic failover detection.
  8. Unconfirmed vs Confirmed failover recovery semantics.
  9. Standby replication lag warning.
 10. Multi-cycle state persistence of unrecovered failover nodes.
"""

import copy
import os
import sys
import tempfile
import unittest

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "postgres_cluster"))

import postgres_cluster as pc


class TestSummaryTabPromotion(unittest.TestCase):
    """Verifies that the 4 agreed Summary metrics are untabbed, while all others are tabbed."""

    def test_summary_metrics_untabbed_in_payload(self):
        """The 4 promoted metrics must exist in payload and units, but NOT in any tab's tablist."""
        payload = pc.get_empty_payload()

        tabs = payload.get("tabs", {})
        tabbed_metrics = set()
        for t_info in tabs.values():
            tabbed_metrics.update(t_info.get("tablist", []))

        # Expected 4 untabbed Summary metrics
        expected_summary = {"Cluster_Health", "Nodes_Up", "Standbys_Streaming", "Max_Replay_Lag_s"}
        self.assertEqual(pc.SUMMARY_METRICS, expected_summary)

        for sm in expected_summary:
            self.assertIn(sm, payload, f"Summary metric '{sm}' missing from payload")
            self.assertIn(sm, payload["units"], f"Summary metric '{sm}' missing from units")
            self.assertNotIn(sm, tabbed_metrics, f"Summary metric '{sm}' must NOT be in any tablist (must be untabbed)")

    def test_all_custom_tabs_preserved(self):
        """All 9 custom tabs must remain defined and maintain their strict order."""
        payload = pc.get_empty_payload()
        tabs = payload.get("tabs", {})
        self.assertEqual(list(tabs.keys()), pc.TAB_ORDER)
        self.assertEqual(len(tabs), 9)

    def test_validate_output_whitelist_enforcement(self):
        """validate_output must pass for SUMMARY_METRICS and reject unauthorized untabbed metrics."""
        payload = pc.get_empty_payload()
        self.assertEqual(pc.validate_output(payload), [])

        # Add unauthorized untabbed metric
        payload["Unauthorized_Metric"] = 123
        payload["units"]["Unauthorized_Metric"] = "count"
        violations = pc.validate_output(payload)
        self.assertTrue(any("EMITTED_METRIC_NO_TAB" in v for v in violations))

        # Remove unit for an authorized Summary metric
        payload_missing_unit = pc.get_empty_payload()
        del payload_missing_unit["units"]["Nodes_Up"]
        violations = pc.validate_output(payload_missing_unit)
        self.assertTrue(any("SUMMARY_METRIC_NO_UNIT" in v for v in violations))


class TestSummaryOperationalMessage(unittest.TestCase):
    """Verifies message formatting, priority hierarchy, and strict length bounds."""

    def test_healthy_cluster_message(self):
        """Healthy cluster: HEALTHY c0 with primary, streaming replica count, lag, and Attention: None."""
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg-node3",
            nodes_up=3,
            nodes_total=3,
            timeline=2,
            primaries_count=1,
            expected_standbys=2,
            streaming_standbys=2,
            max_replay_lag_s=0.0
        )
        self.assertEqual(h.severity, pc.HEALTH_OK)
        self.assertEqual(h.code, pc.HEALTH_CODE_OK)

        msg = h.format_msg()
        self.assertLessEqual(len(msg), pc.MAX_MSG_CHARS)
        self.assertTrue(msg.startswith("HEALTHY c0:"))
        self.assertIn("Cluster healthy: 3/3 nodes active", msg)
        self.assertIn("primary: pg-node3", msg)
        self.assertIn("2/2 streaming (lag: 0.0s)", msg)
        self.assertIn("Attention: None", msg)

    def test_one_replica_unavailable_degraded(self):
        """One replica unavailable: DEGRADED c10 with 2/3 up, 1/2 streaming, and offline node hint."""
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg-node3",
            nodes_up=2,
            nodes_total=3,
            timeline=2,
            primaries_count=1,
            expected_standbys=2,
            streaming_standbys=1,
            max_replay_lag_s=0.0
        )
        self.assertEqual(h.severity, pc.HEALTH_WARN)
        self.assertEqual(h.code, pc.HEALTH_CODE_NODE_DOWN)

        msg = h.format_msg()
        self.assertLessEqual(len(msg), pc.MAX_MSG_CHARS)
        self.assertTrue(msg.startswith("DEGRADED c10:"))
        self.assertIn("1 cluster node(s) unreachable (2/3 up)", msg)
        self.assertIn("primary: pg-node3", msg)
        self.assertIn("1/2 streaming", msg)
        self.assertIn("hint: inspect offline node postmaster", msg)

    def test_primary_unavailable_critical(self):
        """Primary unavailable: CRITICAL c1 with failover candidate hint."""
        h = pc.evaluate_cluster_health(
            has_primary=False,
            primary_name="pg-node2",
            primary_last_seen_s=45,
            nodes_up=2,
            nodes_total=3,
            timeline=1,
            primaries_count=0,
            has_failover_candidate=True
        )
        self.assertEqual(h.severity, pc.HEALTH_CRITICAL)
        self.assertEqual(h.code, pc.HEALTH_CODE_PRIMARY_DOWN)

        msg = h.format_msg()
        self.assertLessEqual(len(msg), pc.MAX_MSG_CHARS)
        self.assertTrue(msg.startswith("CRITICAL c1:"))
        self.assertIn("no primary reachable", msg)
        self.assertIn("hint: patronictl list; failover --candidate", msg)

    def test_replication_lag_warning_degraded(self):
        """High replication lag: DEGRADED c11 with lag details and saturation hint."""
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg-node3",
            nodes_up=3,
            nodes_total=3,
            timeline=2,
            primaries_count=1,
            expected_standbys=2,
            streaming_standbys=2,
            max_replay_lag_s=85.4,
            replay_warn_s=60.0
        )
        self.assertEqual(h.severity, pc.HEALTH_WARN)
        self.assertEqual(h.code, pc.HEALTH_CODE_STANDBY_LAG_HIGH)

        msg = h.format_msg()
        self.assertLessEqual(len(msg), pc.MAX_MSG_CHARS)
        self.assertTrue(msg.startswith("DEGRADED c11:"))
        self.assertIn("standby replay lag exceeds threshold (lag: 85.4s)", msg)
        self.assertIn("hint: check standby I/O saturation", msg)


class TestFailoverAndRecoverySemantics(unittest.TestCase):
    """Verifies failover detection and unconfirmed vs confirmed recovery semantics."""

    def test_failover_recovery_unconfirmed(self):
        """When previous primary has not re-joined as a streaming standby, state remains DEGRADED."""
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg-node3",
            nodes_up=2,
            nodes_total=3,
            timeline=2,
            primaries_count=1,
            expected_standbys=2,
            streaming_standbys=1,
            failover_age_s=180,
            failover_window_s=900,
            prev_primary_name="pg-node2",
            prev_primary_recovered=False
        )
        # Higher precedence Rule 7 (node down) or Rule 11 (recent failover) triggers WARN
        self.assertEqual(h.severity, pc.HEALTH_WARN)

        # When all nodes are reachable but previous primary is not streaming (unrecovered)
        h2 = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg-node3",
            nodes_up=3,
            nodes_total=3,
            timeline=2,
            primaries_count=1,
            expected_standbys=2,
            streaming_standbys=1,
            failover_age_s=1200,  # Expired window
            failover_window_s=900,
            prev_primary_name="pg-node2",
            prev_primary_recovered=False
        )
        self.assertEqual(h2.severity, pc.HEALTH_WARN)
        self.assertEqual(h2.code, pc.HEALTH_CODE_RECENT_FAILOVER)
        msg2 = h2.format_msg()
        self.assertIn("failover recovery incomplete: pg-node2 not streaming", msg2)
        self.assertIn("hint: verify pg-node2 re-joins as standby", msg2)

    def test_failover_recovery_confirmed(self):
        """When previous primary has successfully re-joined as a streaming replica, recovery is confirmed."""
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg-node3",
            nodes_up=3,
            nodes_total=3,
            timeline=2,
            primaries_count=1,
            expected_standbys=2,
            streaming_standbys=2,
            failover_age_s=180,
            failover_window_s=900,
            prev_primary_name="pg-node2",
            prev_primary_recovered=True
        )
        self.assertEqual(h.severity, pc.HEALTH_WARN)
        self.assertEqual(h.code, pc.HEALTH_CODE_RECENT_FAILOVER)
        msg = h.format_msg()
        self.assertIn("pg-node2 recovered as standby", msg)
        self.assertIn("Attention: None", msg)

        # After window expires with confirmed recovery -> Fully HEALTHY (0)
        h_recovered = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg-node3",
            nodes_up=3,
            nodes_total=3,
            timeline=2,
            primaries_count=1,
            expected_standbys=2,
            streaming_standbys=2,
            failover_age_s=1200,  # Window expired
            failover_window_s=900,
            prev_primary_name="pg-node2",
            prev_primary_recovered=True
        )
        self.assertEqual(h_recovered.severity, pc.HEALTH_OK)
        self.assertEqual(h_recovered.code, pc.HEALTH_CODE_OK)
        msg_rec = h_recovered.format_msg()
        self.assertTrue(msg_rec.startswith("HEALTHY c0:"))
        self.assertIn("primary: pg-node3 | 2/2 streaming (lag: 0.0s)", msg_rec)


class TestStateStorePersistence(unittest.TestCase):
    """Verifies that state store retains previous primary name across collection cycles."""

    def test_state_store_retains_primary_across_cycles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = pc.StateStore(
                plugin_file=__file__,
                cluster_id="summary_test_cluster",
                name="postgres_cluster",
                seed="127.0.0.1",
                state_dir=tmpdir
            )
            store.probe()

            # Cycle 1: pg-node2 is primary
            state1 = {"primary_name": "pg-node2", "nodes": {}}
            self.assertTrue(store.save(state1))

            # Cycle 2: load state and verify previous primary is pg-node2
            loaded_state = store.load()
            self.assertEqual(loaded_state.get("primary_name"), "pg-node2")

            # Cycle 2 saves new primary pg-node3
            state2 = {"primary_name": "pg-node3", "nodes": {}}
            self.assertTrue(store.save(state2))

            # Cycle 3 loads pg-node3
            loaded_state3 = store.load()
            self.assertEqual(loaded_state3.get("primary_name"), "pg-node3")


if __name__ == "__main__":
    unittest.main()
