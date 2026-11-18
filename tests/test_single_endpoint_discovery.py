#!/usr/bin/env python3
"""
Unit and integration tests for PostgreSQL Cluster single-endpoint discovery
and intelligent port resolution.

Covers all 7 failover and discovery scenarios:
  1. All nodes running (single endpoint discovery)
  2. Original primary down at startup (discovers promoted primary, marks downed node DOWN, cluster UP)
  3. Replica promoted to primary (new primary identified, timeline updated)
  4. Old primary returns (rejoins as replica, status updated)
  5. Replicas unavailable (primary running, cluster records Standbys_Streaming = 0)
  6. Entry point unreachable (connection error handled gracefully, status DOWN, no crash)
  7. Node unreachable during collection (individual node DOWN, overall cluster UP)
Plus port mapping tests (address_map short port, node_ports list, patroni_ports list, CIDR stripping).
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "postgres_cluster"))

import postgres_cluster as pc


class TestPortResolutionAndMapping(unittest.TestCase):
    """Tests for parse_port_list and resolve_mapped_endpoint."""

    def test_parse_port_list_csv(self):
        ports = pc.parse_port_list("5441,5442,5443")
        self.assertEqual(ports, [5441, 5442, 5443])

    def test_parse_port_list_range(self):
        ports = pc.parse_port_list("8001-8003")
        self.assertEqual(ports, [8001, 8002, 8003])

    def test_parse_port_list_list_and_ints(self):
        self.assertEqual(pc.parse_port_list([5441, "5442", 5443]), [5441, 5442, 5443])
        self.assertEqual(pc.parse_port_list(5432), [5432])
        self.assertEqual(pc.parse_port_list(""), [])
        self.assertEqual(pc.parse_port_list(None), [])

    def test_resolve_mapped_endpoint_address_map_short_port(self):
        addr_map = {"pg-node1": "5441", "pg-node2": "5442"}
        h, p = pc.resolve_mapped_endpoint(
            name="pg-node1",
            host="172.18.0.2",
            port=5432,
            address_map=addr_map,
            cluster_host="127.0.0.1",
        )
        self.assertEqual(h, "127.0.0.1")
        self.assertEqual(p, 5441)

    def test_resolve_mapped_endpoint_address_map_host_port(self):
        addr_map = {"pg-node1": "10.0.0.10:5433"}
        h, p = pc.resolve_mapped_endpoint(
            name="pg-node1",
            host="172.18.0.2",
            port=5432,
            address_map=addr_map,
            cluster_host="127.0.0.1",
        )
        self.assertEqual(h, "10.0.0.10")
        self.assertEqual(p, 5433)

    def test_resolve_mapped_endpoint_node_ports_trailing_index(self):
        node_ports = [5441, 5442, 5443]
        h1, p1 = pc.resolve_mapped_endpoint(
            name="pg-node1",
            host="172.18.0.2",
            port=5432,
            address_map={},
            cluster_host="192.168.1.100",
            node_ports=node_ports,
        )
        self.assertEqual(h1, "192.168.1.100")
        self.assertEqual(p1, 5441)

        h2, p2 = pc.resolve_mapped_endpoint(
            name="pg-node2",
            host="172.18.0.3",
            port=5432,
            address_map={},
            cluster_host="192.168.1.100",
            node_ports=node_ports,
        )
        self.assertEqual(h2, "192.168.1.100")
        self.assertEqual(p2, 5442)

    def test_resolve_mapped_endpoint_fallback(self):
        h, p = pc.resolve_mapped_endpoint(
            name="standalone-db",
            host="10.5.0.1",
            port=5432,
            address_map={},
            cluster_host="127.0.0.1",
        )
        self.assertEqual(h, "10.5.0.1")
        self.assertEqual(p, 5432)


class TestSingleEndpointDiscoveryScenarios(unittest.TestCase):
    """Tests all 7 discovery and failover scenarios."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _mock_node_client(self, name, is_primary=False, uptime=3600, version=170000, streaming_peers=None):
        client = MagicMock()
        client.name = str(name)
        client.connected = True
        client.connect.return_value = True
        client.is_supported = True
        client.auth_failed = False
        client.auth_error = ""
        client.version_tuple = (17, 0)
        client.version_num = version
        client.server_version_str = "17.0"
        client.warnings = []
        client.last_error_class = None
        client.is_recovery = not is_primary
        client.settings = {"max_connections": 100}

        def mock_query_one(sql, *args):
            s = sql.strip().lower()
            if "recovery_min_apply_delay" in s:
                return ("0",)
            if "pg_postmaster_start_time" in s:
                return (uptime,)
            if "timeline_id" in s:
                return (1,)
            if "pg_stat_database" in s:
                return (5, 1000, 10, 500, 200, 50, 2000, 10000, 100, 900, 50000)
            if "pg_is_in_recovery" in s:
                return (not is_primary,)
            if "count(*)" in s:
                return (0,)
            if "current_wal_lsn" in s or "pg_current_wal_lsn" in s:
                return (83886080,)
            return (0,)

        def mock_query_all(sql, *args):
            s = sql.strip().lower()
            if "pg_stat_replication" in s:
                peers = streaming_peers if streaming_peers is not None else ["pg-node2", "pg-node3"]
                return [
                    (p, f"172.18.0.{i+3}", "streaming", "async", 0, 0, 0, 0, 0)
                    for i, p in enumerate(peers)
                ]
            return []

        client.query_one.side_effect = mock_query_one
        client.query_all.side_effect = mock_query_all
        return client

    @patch("postgres_cluster.fetch_patroni_cluster")
    @patch("postgres_cluster.NodeClient")
    def test_scenario_1_all_nodes_running(self, mock_client_cls, mock_fetch_patroni):
        """Scenario 1: All nodes running (single endpoint discovery via patroni_ports)."""
        patroni_resp = {
            "members": [
                {"name": "pg-node1", "role": "leader", "state": "running", "timeline": 1, "host": "172.18.0.2", "port": 5432},
                {"name": "pg-node2", "role": "replica", "state": "running", "timeline": 1, "lag": 0, "host": "172.18.0.3", "port": 5432},
                {"name": "pg-node3", "role": "replica", "state": "running", "timeline": 1, "lag": 0, "host": "172.18.0.4", "port": 5432},
            ]
        }
        mock_fetch_patroni.return_value = ("positive", patroni_resp)

        clients = {
            "pg-node1": self._mock_node_client("pg-node1", is_primary=True, streaming_peers=["pg-node2", "pg-node3"]),
            "pg-node2": self._mock_node_client("pg-node2", is_primary=False),
            "pg-node3": self._mock_node_client("pg-node3", is_primary=False),
        }
        mock_client_cls.side_effect = lambda **kwargs: clients.get(kwargs.get("name"), self._mock_node_client(kwargs.get("name")))

        res = pc.run({
            "cluster_host": "127.0.0.1",
            "patroni_ports": "8001,8002,8003",
            "node_ports": "5441,5442,5443",
            "cluster_name": "test_cluster_s1",
            "state_dir": self.temp_dir,
        })

        self.assertEqual(res["status"], pc.STATUS_UP)
        self.assertEqual(res["Primary_Node"], "pg-node1")
        self.assertEqual(res["Primary_Up"], 1)
        self.assertEqual(res["Standbys_Streaming"], 2)

    @patch("postgres_cluster.fetch_patroni_cluster")
    @patch("postgres_cluster.NodeClient")
    def test_scenario_2_original_primary_down_at_startup(self, mock_client_cls, mock_fetch_patroni):
        """Scenario 2: Original primary down at startup (discovers promoted primary, marks downed node DOWN, cluster UP)."""
        def patroni_side_effect(host, port, timeout=1.0):
            if port == 8001:
                return "connection_error", None
            return "positive", {
                "members": [
                    {"name": "pg-node1", "role": "replica", "state": "stopped", "timeline": 1, "host": "172.18.0.2", "port": 5432},
                    {"name": "pg-node2", "role": "leader", "state": "running", "timeline": 2, "host": "172.18.0.3", "port": 5432},
                    {"name": "pg-node3", "role": "replica", "state": "running", "timeline": 2, "lag": 0, "host": "172.18.0.4", "port": 5432},
                ]
            }
        mock_fetch_patroni.side_effect = patroni_side_effect

        def client_side_effect(**kwargs):
            name = kwargs.get("name")
            if name == "pg-node1":
                c = MagicMock()
                c.name = str(name)
                c.connect.return_value = False
                c.auth_failed = False
                c.auth_error = ""
                c.warnings = ["connection refused to pg-node1"]
                return c
            return self._mock_node_client(name, is_primary=(name == "pg-node2"), streaming_peers=["pg-node3"])
        mock_client_cls.side_effect = client_side_effect

        res = pc.run({
            "cluster_host": "127.0.0.1",
            "patroni_ports": "8001,8002,8003",
            "node_ports": "5441,5442,5443",
            "cluster_name": "test_cluster_s2",
            "state_dir": self.temp_dir,
        })

        self.assertEqual(res["status"], pc.STATUS_UP)
        self.assertEqual(res["Primary_Node"], "pg-node2")
        self.assertEqual(res["Primary_Timeline"], 2)
        self.assertEqual(res["Primary_Up"], 1)

        nodes_map = {n["name"]: n for n in res["Cluster_Nodes"]}
        self.assertEqual(nodes_map["pg-node1"]["status"], pc.STATUS_DOWN)
        self.assertEqual(nodes_map["pg-node2"]["status"], pc.STATUS_UP)
        self.assertEqual(nodes_map["pg-node3"]["status"], pc.STATUS_UP)

    @patch("postgres_cluster.fetch_patroni_cluster")
    @patch("postgres_cluster.NodeClient")
    def test_scenario_3_replica_promoted_to_primary(self, mock_client_cls, mock_fetch_patroni):
        """Scenario 3: Replica promoted to primary (new primary identified, timeline updated)."""
        patroni_resp = {
            "members": [
                {"name": "pg-node1", "role": "replica", "state": "stopped", "timeline": 1, "host": "172.18.0.2", "port": 5432},
                {"name": "pg-node2", "role": "leader", "state": "running", "timeline": 3, "host": "172.18.0.3", "port": 5432},
                {"name": "pg-node3", "role": "replica", "state": "running", "timeline": 3, "lag": 0, "host": "172.18.0.4", "port": 5432},
            ]
        }
        mock_fetch_patroni.return_value = ("positive", patroni_resp)

        def client_side_effect(**kwargs):
            name = kwargs.get("name")
            if name == "pg-node1":
                c = MagicMock()
                c.name = str(name)
                c.connect.return_value = False
                c.auth_failed = False
                c.auth_error = ""
                c.warnings = ["connection refused"]
                return c
            return self._mock_node_client(name, is_primary=(name == "pg-node2"), streaming_peers=["pg-node3"])
        mock_client_cls.side_effect = client_side_effect

        res = pc.run({
            "cluster_host": "127.0.0.1",
            "patroni_ports": "8002",
            "node_ports": "5441,5442,5443",
            "cluster_name": "test_cluster_s3",
            "state_dir": self.temp_dir,
        })

        self.assertEqual(res["Primary_Node"], "pg-node2")
        self.assertEqual(res["Primary_Timeline"], 3)
        self.assertEqual(res["Primary_Up"], 1)
        self.assertEqual(res["status"], pc.STATUS_UP)

    @patch("postgres_cluster.fetch_patroni_cluster")
    @patch("postgres_cluster.NodeClient")
    def test_scenario_4_old_primary_returns(self, mock_client_cls, mock_fetch_patroni):
        """Scenario 4: Old primary returns (rejoins as replica, status updated to UP)."""
        patroni_resp = {
            "members": [
                {"name": "pg-node1", "role": "replica", "state": "running", "timeline": 3, "lag": 0, "host": "172.18.0.2", "port": 5432},
                {"name": "pg-node2", "role": "leader", "state": "running", "timeline": 3, "host": "172.18.0.3", "port": 5432},
                {"name": "pg-node3", "role": "replica", "state": "running", "timeline": 3, "lag": 0, "host": "172.18.0.4", "port": 5432},
            ]
        }
        mock_fetch_patroni.return_value = ("positive", patroni_resp)

        clients = {
            "pg-node1": self._mock_node_client("pg-node1", is_primary=False),
            "pg-node2": self._mock_node_client("pg-node2", is_primary=True, streaming_peers=["pg-node1", "pg-node3"]),
            "pg-node3": self._mock_node_client("pg-node3", is_primary=False),
        }
        mock_client_cls.side_effect = lambda **kwargs: clients.get(kwargs.get("name"), self._mock_node_client(kwargs.get("name")))

        res = pc.run({
            "cluster_host": "127.0.0.1",
            "patroni_ports": "8002",
            "node_ports": "5441,5442,5443",
            "cluster_name": "test_cluster_s4",
            "state_dir": self.temp_dir,
        })

        nodes_map = {n["name"]: n for n in res["Cluster_Nodes"]}
        self.assertEqual(nodes_map["pg-node1"]["status"], pc.STATUS_UP)
        self.assertEqual(nodes_map["pg-node1"]["role"], pc.ROLE_STANDBY)
        self.assertEqual(res["Primary_Node"], "pg-node2")
        self.assertEqual(res["status"], pc.STATUS_UP)

    @patch("postgres_cluster.fetch_patroni_cluster")
    @patch("postgres_cluster.NodeClient")
    def test_scenario_5_replicas_unavailable(self, mock_client_cls, mock_fetch_patroni):
        """Scenario 5: Replicas unavailable (primary running, cluster records Standbys_Streaming = 0)."""
        patroni_resp = {
            "members": [
                {"name": "pg-node1", "role": "leader", "state": "running", "timeline": 1, "host": "172.18.0.2", "port": 5432},
                {"name": "pg-node2", "role": "replica", "state": "stopped", "timeline": 1, "host": "172.18.0.3", "port": 5432},
                {"name": "pg-node3", "role": "replica", "state": "stopped", "timeline": 1, "host": "172.18.0.4", "port": 5432},
            ]
        }
        mock_fetch_patroni.return_value = ("positive", patroni_resp)

        def client_side_effect(**kwargs):
            name = kwargs.get("name")
            if name == "pg-node1":
                return self._mock_node_client("pg-node1", is_primary=True, streaming_peers=[])
            c = MagicMock()
            c.name = str(name)
            c.connect.return_value = False
            c.auth_failed = False
            c.auth_error = ""
            c.warnings = ["connection failed"]
            return c
        mock_client_cls.side_effect = client_side_effect

        res = pc.run({
            "cluster_host": "127.0.0.1",
            "patroni_ports": "8001",
            "node_ports": "5441,5442,5443",
            "cluster_name": "test_cluster_s5",
            "state_dir": self.temp_dir,
        })

        # Primary is alive, standbys disconnected
        self.assertEqual(res["Primary_Up"], 1)
        self.assertEqual(res["Primary_Node"], "pg-node1")
        self.assertEqual(res["Standbys_Streaming"], 0)
        self.assertEqual(res["Health_Code"], pc.HEALTH_CODE_NO_STANDBYS_STREAMING)

    @patch("postgres_cluster.fetch_patroni_cluster")
    @patch("postgres_cluster.NodeClient")
    def test_scenario_6_entry_point_unreachable(self, mock_client_cls, mock_fetch_patroni):
        """Scenario 6: Entry point unreachable (connection error handled gracefully, status DOWN, no crash)."""
        mock_fetch_patroni.return_value = ("connection_error", None)

        def client_side_effect(**kwargs):
            c = MagicMock()
            c.name = str(kwargs.get("name", "unreachable_node"))
            c.connect.return_value = False
            c.auth_failed = False
            c.auth_error = ""
            c.warnings = ["connect timeout to entry point"]
            return c
        mock_client_cls.side_effect = client_side_effect

        res = pc.run({
            "cluster_host": "192.0.2.1",
            "patroni_ports": "8001",
            "node_ports": "5441",
            "cluster_name": "test_cluster_s6",
            "state_dir": self.temp_dir,
        })

        self.assertEqual(res["status"], pc.STATUS_DOWN)
        self.assertEqual(res["plugin_version"], pc.PLUGIN_VERSION)
        self.assertTrue(res["heartbeat_required"])
        self.assertTrue(len(res["msg"]) > 0)

    @patch("postgres_cluster.fetch_patroni_cluster")
    @patch("postgres_cluster.NodeClient")
    def test_scenario_7_node_unreachable_during_collection(self, mock_client_cls, mock_fetch_patroni):
        """Scenario 7: Node unreachable during collection (individual node DOWN, overall cluster UP)."""
        patroni_resp = {
            "members": [
                {"name": "pg-node1", "role": "leader", "state": "running", "timeline": 1, "host": "172.18.0.2", "port": 5432},
                {"name": "pg-node2", "role": "replica", "state": "running", "timeline": 1, "lag": 0, "host": "172.18.0.3", "port": 5432},
                {"name": "pg-node3", "role": "replica", "state": "running", "timeline": 1, "lag": 0, "host": "172.18.0.4", "port": 5432},
            ]
        }
        mock_fetch_patroni.return_value = ("positive", patroni_resp)

        def client_side_effect(**kwargs):
            name = kwargs.get("name")
            if name == "pg-node3":
                c = MagicMock()
                c.name = str(name)
                c.connect.return_value = False
                c.auth_failed = False
                c.auth_error = ""
                c.warnings = ["connection dropped mid-collection"]
                return c
            return self._mock_node_client(name, is_primary=(name == "pg-node1"), streaming_peers=["pg-node2"])
        mock_client_cls.side_effect = client_side_effect

        res = pc.run({
            "cluster_host": "127.0.0.1",
            "patroni_ports": "8001",
            "node_ports": "5441,5442,5443",
            "cluster_name": "test_cluster_s7",
            "state_dir": self.temp_dir,
        })

        self.assertEqual(res["status"], pc.STATUS_UP)
        nodes_map = {n["name"]: n for n in res["Cluster_Nodes"]}
        self.assertEqual(nodes_map["pg-node1"]["status"], pc.STATUS_UP)
        self.assertEqual(nodes_map["pg-node2"]["status"], pc.STATUS_UP)
        self.assertEqual(nodes_map["pg-node3"]["status"], pc.STATUS_DOWN)


if __name__ == "__main__":
    unittest.main()
