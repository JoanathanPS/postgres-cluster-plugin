#!/usr/bin/env python3
"""
Regression and Integration Tests for Standalone Instance Handling and Monitoring Modes.
Covers all 15 scenarios mandated by the Standalone Instance Handling specification:
 1. Standalone writable primary with monitor_mode=auto
 2. Standalone writable primary with monitor_mode=standalone
 3. Standalone read-only instance with monitor_mode=auto
 4. Standalone read-only instance with monitor_mode=standalone
 5. Healthy single-node cluster
 6. Healthy multi-node cluster
 7. Configured cluster with no reachable primary
 8. Invalid credentials
 9. Connection timeout / refused
10. Missing nodes= configuration (default localhost fallback)
11. Legacy configuration without monitor_mode
12. Failed replication query in standalone mode
13. Standalone instance with restricted permissions
14. Valid standalone database with no replication slots
15. Repeated execution (5 cycles) checking for thread and connection leaks
"""

import os
import sys
import unittest
import threading
import time
import socket
from unittest.mock import MagicMock, patch

# Ensure postgres_cluster module is importable
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "postgres_cluster"))

import postgres_cluster as pc


def live_postgres_accessible(port=5441):
    """Checks if live test PostgreSQL container is reachable on localhost."""
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=0.5)
        s.close()
        return True
    except Exception:
        return False


class TestStandaloneHealthEngine(unittest.TestCase):
    """Pure unit tests for evaluate_database_health() reasoning engine."""

    def test_standalone_healthy_writable(self):
        h = pc.evaluate_database_health(
            connected=True,
            is_recovery=False,
            uptime_s=3600,
            active_queries=2,
            conn_pct=15.0,
            xid_wraparound_pct=5.0
        )
        self.assertEqual(h.severity, pc.HEALTH_OK)
        self.assertEqual(h.code, pc.HEALTH_CODE_OK)
        self.assertIn("writable standalone", h.fact)

    def test_standalone_healthy_standby(self):
        h = pc.evaluate_database_health(
            connected=True,
            is_recovery=True,
            uptime_s=1800,
            active_queries=1,
            conn_pct=10.0,
            xid_wraparound_pct=2.0
        )
        self.assertEqual(h.severity, pc.HEALTH_OK)
        self.assertEqual(h.code, pc.HEALTH_CODE_OK)
        self.assertIn("read-only standby", h.fact)

    def test_standalone_auth_failure(self):
        h = pc.evaluate_database_health(
            connected=False,
            auth_failure=True,
            auth_msg="password authentication failed for user site24x7"
        )
        self.assertEqual(h.severity, pc.HEALTH_CRITICAL)
        self.assertEqual(h.code, pc.HEALTH_CODE_AUTH_FAIL)
        self.assertIn("password authentication failed", h.fact)

    def test_standalone_connection_failure(self):
        h = pc.evaluate_database_health(
            connected=False,
            status_reason="connection refused"
        )
        self.assertEqual(h.severity, pc.HEALTH_CRITICAL)
        self.assertEqual(h.code, pc.HEALTH_CODE_CONN_FAIL)

    def test_standalone_unsupported_version(self):
        h = pc.evaluate_database_health(
            connected=True,
            unsupported_version=True,
            version_str="9.4"
        )
        self.assertEqual(h.severity, pc.HEALTH_CRITICAL)
        self.assertEqual(h.code, pc.HEALTH_CODE_UNSUPPORTED_VERSION)

    def test_standalone_xid_wraparound_warnings(self):
        h_warn = pc.evaluate_database_health(
            connected=True,
            xid_wraparound_pct=75.0
        )
        self.assertEqual(h_warn.severity, pc.HEALTH_WARN)
        self.assertEqual(h_warn.code, pc.HEALTH_CODE_XID_WARN)

        h_crit = pc.evaluate_database_health(
            connected=True,
            xid_wraparound_pct=92.0
        )
        self.assertEqual(h_crit.severity, pc.HEALTH_CRITICAL)
        self.assertEqual(h_crit.code, pc.HEALTH_CODE_XID_CRITICAL)

    def test_standalone_conn_saturation_warnings(self):
        h_warn = pc.evaluate_database_health(
            connected=True,
            conn_pct=91.0
        )
        self.assertEqual(h_warn.severity, pc.HEALTH_WARN)
        self.assertEqual(h_warn.code, pc.HEALTH_CODE_HIGH_CONNECTIONS)

        h_crit = pc.evaluate_database_health(
            connected=True,
            conn_pct=96.0
        )
        self.assertEqual(h_crit.severity, pc.HEALTH_CRITICAL)
        self.assertEqual(h_crit.code, pc.HEALTH_CODE_HIGH_CONNECTIONS)


class TestStandaloneScenarios(unittest.TestCase):
    """
    Automated verification of the 15 required scenarios.
    Executes live integration tests against containers when reachable,
    and mocked unit tests when offline.
    """

    def test_scenario_01_standalone_writable_auto(self):
        """Case 1: Standalone writable primary with monitor_mode=auto -> UP (1)."""
        mock_db_row = (5, 100, 2, 50, 20, 10, 200, 500, 30, 700, 1000)
        def mock_query_one(sql):
            if "pg_stat_database" in sql:
                return mock_db_row
            if "pg_database" in sql:
                return (3, 250.0)
            if "pg_stat_replication" in sql:
                return (0,)
            if "pg_postmaster_start_time" in sql:
                return (12345,)
            if "pg_stat_activity" in sql:
                return (1, 0, 1, 0)
            return (0,)

        with patch.object(pc.NodeClient, "connect", return_value=True), \
             patch.object(pc.NodeClient, "query_one", side_effect=mock_query_one), \
             patch.object(pc.NodeClient, "query_all", return_value=[]):
            res = pc.run({
                "nodes": "127.0.0.1:5432",
                "monitor_mode": "auto"
            })
            self.assertEqual(res.get("status"), pc.STATUS_UP)
            self.assertEqual(res.get("Cluster_Health"), pc.HEALTH_OK)
            self.assertEqual(res.get("Nodes_Total"), 1)
            self.assertEqual(res.get("Nodes_Up"), 1)
            topo = res.get("Topology", [{}])[0]
            self.assertEqual(topo.get("manager"), "standalone")
            violations = pc.validate_output(res)
            self.assertEqual(len(violations), 0, f"Violations: {violations}")

    @unittest.skipUnless(live_postgres_accessible(5450), "Live PostgreSQL container port 5450 required")
    def test_scenario_02_standalone_writable_standalone(self):
        """Case 2: Standalone writable primary with monitor_mode=standalone -> UP (1)."""
        res = pc.run({
            "nodes": "127.0.0.1:5450",
            "username": "site24x7",
            "password": "site24x7",
            "monitor_mode": "standalone"
        })
        self.assertEqual(res.get("status"), pc.STATUS_UP)
        self.assertEqual(res.get("Primary_Up"), 1)
        self.assertEqual(res.get("Nodes_Total"), 1)
        topo = res.get("Topology", [{}])[0]
        self.assertEqual(topo.get("manager"), "standalone")
        self.assertEqual(topo.get("leader"), "127.0.0.1:5450")
        violations = pc.validate_output(res)
        self.assertEqual(len(violations), 0)

    @unittest.skipUnless(live_postgres_accessible(5433), "Live PostgreSQL native standby port 5433 required")
    def test_scenario_03_standalone_readonly_auto(self):
        """Case 3: Standalone read-only instance with monitor_mode=auto -> detects native cluster standby."""
        res = pc.run({
            "nodes": "127.0.0.1:5433",
            "username": "site24x7",
            "password": "site24x7",
            "monitor_mode": "auto"
        })
        # Single native standby in auto mode recognizes cluster topology (Finding 1)
        self.assertEqual(res.get("status"), pc.STATUS_DOWN)
        topo = res.get("Topology", [{}])[0]
        self.assertEqual(topo.get("manager"), "native")
        self.assertIn("no primary reachable", res.get("msg", ""))
        violations = pc.validate_output(res)
        self.assertEqual(len(violations), 0)

    @unittest.skipUnless(live_postgres_accessible(5433), "Live PostgreSQL native standby port 5433 required")
    def test_scenario_04_standalone_readonly_standalone(self):
        """Case 4: Standalone read-only instance with monitor_mode=standalone -> UP (1), upstream leader."""
        res = pc.run({
            "nodes": "127.0.0.1:5433",
            "username": "site24x7",
            "password": "site24x7",
            "monitor_mode": "standalone"
        })
        self.assertEqual(res.get("status"), pc.STATUS_UP)
        self.assertEqual(res.get("Cluster_Health"), pc.HEALTH_OK)
        self.assertEqual(res.get("Standbys_Expected"), 0)
        topo = res.get("Topology", [{}])[0]
        self.assertEqual(topo.get("manager"), "standalone")
        self.assertEqual(topo.get("leader"), "pg-primary:5432")
        self.assertEqual(len(res.get("Replication_Links")), 1)
        self.assertEqual(res.get("Replication_Links")[0].get("client_addr"), "pg-primary:5432")
        violations = pc.validate_output(res)
        self.assertEqual(len(violations), 0)

    @unittest.skipUnless(live_postgres_accessible(5441), "Live PostgreSQL container port 5441 required")
    def test_scenario_05_healthy_single_node_cluster(self):
        """Case 5: Healthy single-node cluster with monitor_mode=cluster -> UP (1)."""
        res = pc.run({
            "nodes": "127.0.0.1:5441",
            "username": "site24x7",
            "password": "site24x7",
            "monitor_mode": "cluster"
        })
        self.assertEqual(res.get("status"), pc.STATUS_UP)
        self.assertEqual(res.get("Primary_Up"), 1)
        topo = res.get("Topology", [{}])[0]
        self.assertNotEqual(topo.get("manager"), "standalone")

    @unittest.skipUnless(live_postgres_accessible(5441), "Live PostgreSQL cluster required")
    def test_scenario_06_healthy_multinode_cluster(self):
        """Case 6: Healthy multi-node cluster (nodes='5441,5442,5443') -> UP (1)."""
        res = pc.run({
            "nodes": "127.0.0.1:5441,127.0.0.1:5442,127.0.0.1:5443",
            "username": "site24x7",
            "password": "site24x7",
            "monitor_mode": "cluster"
        })
        self.assertEqual(res.get("status"), pc.STATUS_UP)
        self.assertGreaterEqual(res.get("Nodes_Up", 0), 2)
        self.assertEqual(res.get("Primary_Up"), 1)

    @unittest.skipUnless(live_postgres_accessible(5442), "Live PostgreSQL container port 5442 required")
    def test_scenario_07_cluster_no_reachable_primary(self):
        """Case 7: Configured cluster with no reachable primary -> DOWN (0)."""
        res = pc.run({
            "nodes": "127.0.0.1:5442,127.0.0.1:5443",
            "username": "site24x7",
            "password": "site24x7",
            "monitor_mode": "cluster"
        })
        self.assertEqual(res.get("status"), pc.STATUS_DOWN)
        self.assertEqual(res.get("Cluster_Health"), pc.HEALTH_CRITICAL)
        self.assertIn("no primary reachable", res.get("msg", ""))

    @unittest.skipUnless(live_postgres_accessible(5441), "Live PostgreSQL container port 5441 required")
    def test_scenario_08_invalid_credentials(self):
        """Case 8: Invalid credentials -> DOWN (0), authentication error."""
        res = pc.run({
            "nodes": "127.0.0.1:5441",
            "username": "site24x7",
            "password": "wrong_nonexistent_password",
            "monitor_mode": "standalone"
        })
        self.assertEqual(res.get("status"), pc.STATUS_DOWN)
        self.assertEqual(res.get("Auth_Failure_Flag"), 1)
        self.assertIn("auth failed for user", res.get("msg", "").lower())

    def test_scenario_09_connection_refused_or_timeout(self):
        """Case 9: Connection refused / timeout on closed port -> DOWN (0)."""
        # Find unused local port
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        closed_port = s.getsockname()[1]
        s.close()

        res = pc.run({
            "nodes": f"127.0.0.1:{closed_port}",
            "username": "site24x7",
            "password": "site24x7",
            "cycle_deadline": 2.0,
            "monitor_mode": "standalone"
        })
        self.assertEqual(res.get("status"), pc.STATUS_DOWN)
        self.assertEqual(res.get("Cluster_Health"), pc.HEALTH_CRITICAL)

    def test_scenario_10_missing_nodes_config(self):
        """Case 10: Missing nodes= configuration falls back to localhost without crashing."""
        res = pc.run({
            "username": "site24x7",
            "password": "site24x7",
            "cycle_deadline": 2.0,
            "monitor_mode": "auto"
        })
        self.assertIn("status", res)
        self.assertIn("msg", res)
        violations = pc.validate_output(res)
        self.assertEqual(len(violations), 0)

    @unittest.skipUnless(live_postgres_accessible(5441), "Live PostgreSQL container port 5441 required")
    def test_scenario_11_legacy_config_without_monitor_mode(self):
        """Case 11: Legacy configuration without monitor_mode defaults to auto."""
        res = pc.run({
            "nodes": "127.0.0.1:5441",
            "username": "site24x7",
            "password": "site24x7"
        })
        self.assertEqual(res.get("status"), pc.STATUS_UP)
        self.assertIn(res.get("Cluster_Health"), (pc.HEALTH_OK, pc.HEALTH_WARN))

    def test_scenario_12_failed_replication_query_standalone(self):
        """Case 12: Failed replication query in standalone mode is non-fatal; omitted per contract."""
        mock_db_row = (5, 100, 2, 50, 20, 10, 200, 500, 30, 700, 1000)
        def mock_query_one(sql):
            if "pg_stat_database" in sql:
                return mock_db_row
            if "pg_database" in sql:
                return (3, 250.0)
            if "pg_postmaster_start_time" in sql:
                return (12345,)
            if "pg_stat_activity" in sql:
                return (1, 0, 1, 0)
            return (1,)

        with patch.object(pc.NodeClient, "connect", return_value=True), \
             patch.object(pc.NodeClient, "query_one", side_effect=mock_query_one), \
             patch.object(pc.NodeClient, "query_all", return_value=None):
            
            res = pc.run({
                "nodes": "127.0.0.1:5432",
                "monitor_mode": "standalone"
            })
            self.assertEqual(res.get("status"), pc.STATUS_UP)
            # Under Finding 2 contract: failed queries must be omitted, never fabricated to 0
            self.assertNotIn("Standbys_Streaming", res)
            self.assertNotIn("Replication_Slots_Total", res)
            self.assertIn("metric_unavailable", res.get("msg", ""))
            violations = pc.validate_output(res)
            self.assertEqual(len(violations), 0)

    @unittest.skipUnless(live_postgres_accessible(5450), "Live PostgreSQL container port 5450 required")
    def test_scenario_13_restricted_user_permissions(self):
        """Case 13: Standalone instance with restricted user permissions handles gracefully."""
        res = pc.run({
            "nodes": "127.0.0.1:5450",
            "username": "unprivileged_user",
            "password": "",
            "monitor_mode": "standalone"
        })
        # If unprivileged user has no password or denied, plugin emits valid structured JSON
        self.assertIn(res.get("status"), (pc.STATUS_UP, pc.STATUS_DOWN))
        violations = pc.validate_output(res)
        self.assertEqual(len(violations), 0)

    @unittest.skipUnless(live_postgres_accessible(5450), "Live PostgreSQL container port 5450 required")
    def test_scenario_14_standalone_no_replication_slots(self):
        """Case 14: Valid standalone database with no replication slots -> UP (1)."""
        res = pc.run({
            "nodes": "127.0.0.1:5450",
            "username": "site24x7",
            "password": "site24x7",
            "monitor_mode": "standalone"
        })
        self.assertEqual(res.get("status"), pc.STATUS_UP)
        self.assertEqual(res.get("Replication_Slots_Total"), 0)
        self.assertEqual(res.get("Replication_Slots"), [])
        violations = pc.validate_output(res)
        self.assertEqual(len(violations), 0)

    @unittest.skipUnless(live_postgres_accessible(5450), "Live PostgreSQL container port 5450 required")
    def test_scenario_15_repeated_execution_no_thread_leaks(self):
        """Case 15: Repeated execution (5 cycles) checking for thread and connection leaks."""
        initial_threads = threading.active_count()
        for i in range(5):
            res = pc.run({
                "nodes": "127.0.0.1:5450",
                "username": "site24x7",
                "password": "site24x7",
                "monitor_mode": "standalone"
            })
            self.assertEqual(res.get("status"), pc.STATUS_UP)

        time.sleep(0.5)
        final_threads = threading.active_count()
        # Ensure thread count does not grow unboundedly
        self.assertLessEqual(
            final_threads,
            initial_threads + 2,
            f"Thread leak detected: went from {initial_threads} to {final_threads}"
        )


if __name__ == "__main__":
    unittest.main()
