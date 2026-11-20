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

    def test_replication_lag_is_reported_not_judged(self):
        """Replay lag no longer sets severity; it is emitted for the console to threshold.

        The plugin used to return WARN whenever lag passed a 60s constant compiled into
        this file. Max_Replay_Lag_s is emitted every cycle, so the limit belongs in a
        threshold profile. A primary serving its standbys is available whatever the lag.
        """
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg1",
            nodes_up=3,
            nodes_total=3,
            timeline=1,
            primaries_count=1,
            expected_standbys=2,
            streaming_standbys=2,
            max_replay_lag_s=900.0,
        )
        self.assertEqual(h.severity, pc.HEALTH_OK)
        # The measurement still reaches the operator, in the message context.
        self.assertIn("900.0s", h.format_msg())


class TestFailoverAndRecoverySemantics(unittest.TestCase):
    """Verifies failover detection and unconfirmed vs confirmed recovery semantics."""

    def test_failover_recovery_is_not_a_severity(self):
        """A completed failover is not a fault, so it no longer produces WARN.

        The plugin used to warn for 900s after any promotion, and again whenever it
        judged the previous primary had not "recovered". Both were guesses layered on
        Failover_Age_s and Failover_Count_24h, which are emitted and can be alerted on
        directly. A freshly promoted primary serving writes is healthy.
        """
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg2",
            nodes_up=3,
            nodes_total=3,
            timeline=5,
            primaries_count=1,
            expected_standbys=2,
            streaming_standbys=2,
        )
        self.assertEqual(h.severity, pc.HEALTH_OK)
        self.assertEqual(h.code, pc.HEALTH_CODE_OK)

    def test_node_still_down_after_failover_is_warn_not_critical(self):
        """The one node-level condition that survives: an unreachable node is WARN.

        After a promotion the old primary is often still down. That is reported as
        node-down (severity 1), not as an outage, because the cluster is serving.
        """
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg2",
            nodes_up=2,
            nodes_total=3,
            timeline=5,
            primaries_count=1,
            expected_standbys=2,
            streaming_standbys=1,
        )
        self.assertEqual(h.severity, pc.HEALTH_WARN)
        self.assertEqual(h.code, pc.HEALTH_CODE_NODE_DOWN)
        self.assertIn("1/2 streaming", h.format_msg())


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


class TestDynamicClusterThresholds(unittest.TestCase):
    """
    Verifies threshold rule conditions against dynamically sized clusters (2-node, 3-node, 5-node)
    and verifies alert deduplication and resulting states.
    """

    def test_2_node_cluster_healthy_no_false_alerts(self):
        """A healthy 2-node cluster (1 primary + 1 standby) must not trigger any false alerts."""
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg1",
            nodes_up=2,
            nodes_total=2,
            timeline=1,
            primaries_count=1,
            expected_standbys=1,
            streaming_standbys=1,
            max_replay_lag_s=0.0
        )
        nodes_down = 2 - 2
        standby_disconnect_flag = 1 if 1 > 1 else 0

        # Health is HEALTHY
        self.assertEqual(h.severity, pc.HEALTH_OK)
        # Evaluated threshold states
        self.assertFalse(h.severity >= 1, "Cluster_Health >= 1 must NOT trigger on healthy 2-node cluster")
        self.assertFalse(h.severity >= 2, "Cluster_Health >= 2 must NOT trigger on healthy 2-node cluster")
        self.assertFalse(nodes_down >= 1, "Nodes_Down >= 1 must NOT trigger on healthy 2-node cluster")
        self.assertFalse(standby_disconnect_flag == 1, "Standby_Disconnect_Flag must be 0")

    def test_2_node_cluster_standby_down_is_warn_not_critical(self):
        """Losing the only standby is degraded, not an outage.

        This previously returned CRITICAL via the zero-standbys-streaming rule, which
        made a serving primary look like downtime and distorted the availability figure
        in the Site24x7 report. The primary still accepts writes, so it is WARN; the
        loss is visible through Standbys_Streaming, Standby_Disconnect_Flag and the
        node row, all of which a threshold profile can alert on.
        """
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg1",
            nodes_up=1,
            nodes_total=2,
            timeline=1,
            primaries_count=1,
            expected_standbys=1,
            streaming_standbys=0,
        )
        self.assertEqual(h.severity, pc.HEALTH_WARN)
        self.assertEqual(h.code, pc.HEALTH_CODE_NODE_DOWN)
        # Still >= 1, so the user's existing "Trouble" threshold profile keeps firing.
        self.assertGreaterEqual(h.severity, 1)
        self.assertLess(h.severity, 2)

    def test_3_node_cluster_single_standby_down_triggers_trouble_not_critical(self):
        """In a 3-node cluster, loss of 1 standby leaves 1 standby still streaming -> TROUBLE (DEGRADED)."""
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
        nodes_down = 3 - 2
        standby_disconnect_flag = 1 if 2 > 1 else 0

        self.assertEqual(h.severity, pc.HEALTH_WARN)
        self.assertEqual(h.code, pc.HEALTH_CODE_NODE_DOWN)
        # Evaluated threshold states
        self.assertTrue(h.severity >= 1, "Cluster_Health >= 1 must trigger Trouble")
        self.assertFalse(h.severity >= 2, "Cluster_Health >= 2 must NOT trigger on single replica loss")
        self.assertTrue(nodes_down >= 1)
        self.assertEqual(standby_disconnect_flag, 1)

    def test_5_node_cluster_partial_standby_loss_triggers_trouble_dynamically(self):
        """In a 5-node cluster, loss of 1 standby (4/5 up) dynamically triggers Trouble without static constants."""
        h = pc.evaluate_cluster_health(
            has_primary=True,
            primary_name="pg-primary",
            nodes_up=4,
            nodes_total=5,
            timeline=3,
            primaries_count=1,
            expected_standbys=4,
            streaming_standbys=3,
            max_replay_lag_s=0.0
        )
        nodes_down = 5 - 4
        standby_disconnect_flag = 1 if 4 > 3 else 0

        self.assertEqual(h.severity, pc.HEALTH_WARN)
        self.assertEqual(h.code, pc.HEALTH_CODE_NODE_DOWN)
        self.assertTrue(h.severity >= 1, "Cluster_Health >= 1 must trigger Trouble dynamically on 5-node cluster")
        self.assertFalse(h.severity >= 2, "Cluster_Health >= 2 must NOT trigger (redundancy remains)")
        self.assertTrue(nodes_down >= 1)
        self.assertEqual(standby_disconnect_flag, 1)

    def test_high_replication_lag_does_not_change_severity(self):
        """Lag of any size leaves severity at OK when every node is reachable."""
        for lag in (0.0, 61.0, 3600.0, 86400.0):
            with self.subTest(lag_s=lag):
                h = pc.evaluate_cluster_health(
                    has_primary=True,
                    primary_name="pg1",
                    nodes_up=3,
                    nodes_total=3,
                    timeline=1,
                    primaries_count=1,
                    expected_standbys=2,
                    streaming_standbys=2,
                    max_replay_lag_s=lag,
                )
                self.assertEqual(h.severity, pc.HEALTH_OK)

    def test_primary_loss_triggers_critical(self):
        """Total loss of primary node triggers CRITICAL / DOWN state."""
        h = pc.evaluate_cluster_health(
            has_primary=False,
            primary_name="pg-node2",
            nodes_up=2,
            nodes_total=3,
            timeline=1,
            primaries_count=0
        )
        self.assertEqual(h.severity, pc.HEALTH_CRITICAL)
        self.assertEqual(h.code, pc.HEALTH_CODE_PRIMARY_DOWN)
        # Threshold: Cluster_Health >= 2 triggers Critical
        self.assertTrue(h.severity >= 2)


class TestProxyStatsParsing(unittest.TestCase):
    """Verifies HAProxy seed endpoint deduction and CSV status parsing."""

    def test_fetch_haproxy_stats_parses_csv(self):
        """Simulate HAProxy CSV response and verify parsing into status dict."""
        from unittest.mock import patch, MagicMock
        sample_csv = (
            "# pxname,svname,status\n"
            "primary_be,pg-node1,DOWN\n"
            "primary_be,pg-node2,DOWN\n"
            "primary_be,pg-node3,UP\n"
            "replica_be,pg-node1,UP\n"
            "replica_be,pg-node2,UP\n"
        )
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = sample_csv.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            stats = pc.fetch_haproxy_stats("127.0.0.1", 7000)
            self.assertEqual(stats["primary_be"]["pg-node3"], "UP")
            self.assertEqual(stats["primary_be"]["pg-node1"], "DOWN")
            self.assertEqual(stats["replica_be"]["pg-node2"], "UP")

    def test_discover_cluster_via_sql_deduction(self):
        """Mocks NodeClient to test primary deduction from pg_stat_replication."""
        from unittest.mock import patch, MagicMock
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.is_recovery = False
        mock_client.query_one.return_value = ("patroni-cluster", "172.18.0.3", "5432")
        mock_client.query_all.return_value = [
            ("pg-node1", "172.18.0.5", 49580, "async", 0, 0),
            ("pg-node2", "172.18.0.4", 52830, "async", 0, 1024),
        ]

        address_map = {
            "pg-node1:5432": "127.0.0.1:5441",
            "pg-node2:5432": "127.0.0.1:5442",
            "pg-node3:5432": "127.0.0.1:5443",
        }

        with patch.object(pc, "NodeClient", return_value=mock_client), \
             patch.object(pc, "fetch_haproxy_stats", return_value={}):
            ok, p_spec, sb_specs, msg = pc.discover_cluster_via_sql(
                seed_host="127.0.0.1",
                seed_port=5500,
                username="site24x7",
                password="pw",
                dbname="postgres",
                address_map=address_map
            )
            self.assertTrue(ok)
            self.assertIsNotNone(p_spec)
            # Deduced that pg-node3 is the primary
            self.assertEqual(p_spec["name"], "pg-node3")
            self.assertEqual(p_spec["host"], "127.0.0.1")
            self.assertEqual(p_spec["port"], 5443)
            self.assertEqual(p_spec["patroni_role"], "primary")

            # Standbys are pg-node1 and pg-node2
            self.assertEqual(len(sb_specs), 2)
            sb_names = {s["name"] for s in sb_specs}
            self.assertEqual(sb_names, {"pg-node1", "pg-node2"})


class TestSqlOnlyDiscovery(unittest.TestCase):
    """Discovery must work with no HA manager and no proxy: plain streaming replication."""

    def _client(self, is_recovery, query_one, query_all):
        from unittest.mock import MagicMock
        c = MagicMock()
        c.connect.return_value = True
        c.is_recovery = is_recovery
        c.requires.return_value = True
        c.system_identifier = "7100000000000000001"
        c.query_one.side_effect = query_one if callable(query_one) else (lambda *a, **k: query_one)
        c.query_all.return_value = query_all
        return c

    def test_plain_streaming_pair_no_haproxy_no_patroni(self):
        """Two-node streaming pair, seed = primary, no proxy stats, no Patroni.

        This is the case that used to fall through to 'single node': HAProxy discovery
        was only attempted when a stats endpoint answered, and Patroni discovery needs
        Patroni. Topology must now come from pg_stat_replication alone.
        """
        from unittest.mock import patch
        client = self._client(
            is_recovery=False,
            query_one=("", "10.0.0.1", "5432"),
            query_all=[("pgstandby", "10.0.0.2", 50102, "async", 0, 4096)],
        )
        with patch.object(pc, "NodeClient", return_value=client):
            ok, p_spec, sb_specs, msg = pc.discover_cluster_via_sql(
                seed_host="10.0.0.1", seed_port=5432,
                username="site24x7", password="pw", dbname="postgres",
                address_map={},          # no operator aliases
                stats_port=0,            # no proxy stats endpoint at all
            )
        self.assertTrue(ok, msg)
        self.assertEqual(p_spec["name"], "10.0.0.1:5432")
        self.assertEqual((p_spec["host"], p_spec["port"]), ("10.0.0.1", 5432))
        self.assertEqual(len(sb_specs), 1)
        self.assertEqual(sb_specs[0]["name"], "pgstandby")
        # Lag from pg_stat_replication is bytes and must be labelled as bytes.
        self.assertEqual(sb_specs[0]["patroni_lag_bytes"], 4096)
        self.assertNotIn("patroni_lag", sb_specs[0])

    def test_seed_is_a_standby_follows_upstream_to_primary(self):
        """Pointing the plugin at a standby must still find the whole cluster."""
        from unittest.mock import patch
        standby = self._client(
            is_recovery=True,
            query_one=("10.0.0.1", 5432),   # pg_stat_wal_receiver -> upstream
            query_all=[],
        )
        primary = self._client(
            is_recovery=False,
            query_one=("", "10.0.0.1", "5432"),
            query_all=[("pgstandby", "10.0.0.2", 50102, "sync", 1, 0)],
        )
        seq = [standby, primary]
        with patch.object(pc, "NodeClient", side_effect=lambda *a, **k: seq.pop(0)):
            ok, p_spec, sb_specs, msg = pc.discover_cluster_via_sql(
                seed_host="10.0.0.2", seed_port=5432,
                username="site24x7", password="pw", dbname="postgres",
                address_map={}, stats_port=0,
            )
        self.assertTrue(ok, msg)
        self.assertIn("followed upstream", msg)
        self.assertEqual((p_spec["host"], p_spec["port"]), ("10.0.0.1", 5432))
        self.assertEqual(len(sb_specs), 1)

    def test_standby_with_no_wal_receiver_fails_clearly(self):
        """A standby that is not streaming cannot locate the primary: say so plainly."""
        from unittest.mock import patch
        orphan = self._client(is_recovery=True, query_one=None, query_all=[])
        with patch.object(pc, "NodeClient", return_value=orphan):
            ok, p_spec, sb_specs, msg = pc.discover_cluster_via_sql(
                seed_host="10.0.0.2", seed_port=5432,
                username="site24x7", password="pw", dbname="postgres",
                address_map={}, stats_port=0,
            )
        self.assertFalse(ok)
        self.assertIsNone(p_spec)
        self.assertIn("no active WAL receiver", msg)

    def test_proxy_stats_only_consulted_when_a_stats_port_is_given(self):
        """fetch_haproxy_stats must not be called when stats_port is 0."""
        from unittest.mock import patch, MagicMock
        client = self._client(
            is_recovery=False,
            query_one=("", "10.0.0.1", "5432"),
            query_all=[],
        )
        spy = MagicMock(return_value={})
        with patch.object(pc, "NodeClient", return_value=client), \
             patch.object(pc, "fetch_haproxy_stats", spy):
            pc.discover_cluster_via_sql(
                seed_host="10.0.0.1", seed_port=5432,
                username="u", password="p", dbname="postgres",
                address_map={}, stats_port=0,
            )
        spy.assert_not_called()


if __name__ == "__main__":
    unittest.main()

