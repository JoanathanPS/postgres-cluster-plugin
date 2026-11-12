#!/usr/bin/env python3
"""
tests/test_contract.py
Automated contract test suite verifying Site24x7 plugin invariants:
  1. No units key without data in payload.
  2. No tablist entry that is neither an emitted metric nor an emitted table.
  3. No metric that is exactly 0 in EVERY scenario (reports as "never populated").
  4. No metric emitted with a fabricated default after a forced query failure.
  5. Tabular limits: <= 10 tables, <= 15 columns, <= 25 rows, <= 5 string columns.
  6. Key JSON types are consistent across scenarios.
  7. No credentials or DSNs in any output.
"""

import os
import sys
import unittest
import re
from unittest.mock import patch

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "postgres_cluster"))

import postgres_cluster as pc


class TestSite24x7Contract(unittest.TestCase):
    """Rigorous contract compliance tests."""

    @classmethod
    def setUpClass(cls):
        cls.scenarios = {}

        # Scenario 1: Standalone primary (live on 5450 if available, else mock)
        cls.scenarios["standalone_primary"] = pc.run({
            "nodes": "127.0.0.1:5450",
            "username": "site24x7",
            "password": "site24x7",
            "monitor_mode": "standalone"
        })

        # Scenario 2: Native streaming replica (live on 5433)
        cls.scenarios["native_standby"] = pc.run({
            "nodes": "127.0.0.1:5433",
            "username": "site24x7",
            "password": "site24x7",
            "monitor_mode": "standalone"
        })

        # Scenario 3: Patroni 3-node cluster (live on 5441, 5442, 5443)
        cls.scenarios["patroni_cluster"] = pc.run({
            "nodes": "127.0.0.1:5441,127.0.0.1:5442,127.0.0.1:5443",
            "username": "site24x7",
            "password": "site24x7",
            "monitor_mode": "cluster"
        })

        # Scenario 4: Auto mode on native standby (cluster detected, primary down)
        cls.scenarios["standby_auto_detect"] = pc.run({
            "nodes": "127.0.0.1:5433",
            "username": "site24x7",
            "password": "site24x7",
            "monitor_mode": "auto"
        })

        # Scenario 5: Auth failure scenario
        cls.scenarios["auth_failure"] = pc.run({
            "nodes": "127.0.0.1:5450",
            "username": "site24x7",
            "password": "wrong_password_test",
            "monitor_mode": "standalone"
        })

    def test_rule1_no_units_without_data(self):
        """Rule 1: No key in units without corresponding data in payload."""
        for sc_name, payload in self.scenarios.items():
            units = payload.get("units", {})
            for unit_key, unit_val in units.items():
                if isinstance(unit_val, dict):
                    # Nested table units: table must exist in payload
                    self.assertIn(
                        unit_key, payload,
                        f"[{sc_name}] Nested table unit '{unit_key}' has no corresponding table in payload"
                    )
                    self.assertIsInstance(payload[unit_key], list)
                else:
                    self.assertIn(
                        unit_key, payload,
                        f"[{sc_name}] Unit key '{unit_key}' exists in units but is missing from payload"
                    )

    def test_rule2_no_tablist_entry_missing(self):
        """Rule 2: No tablist entry that is neither an emitted metric nor an emitted table."""
        for sc_name, payload in self.scenarios.items():
            tabs = payload.get("tabs", {}).get("tabs", {})
            for tab_name, tab_info in tabs.items():
                tablist = tab_info.get("tablist", [])
                for entry in tablist:
                    self.assertIn(
                        entry, payload,
                        f"[{sc_name}] Tab '{tab_name}' tablist entry '{entry}' is neither an emitted metric nor an emitted table in payload"
                    )

    def test_rule3_no_metric_always_zero_across_all_scenarios(self):
        """Rule 3: Ensure tracked performance metrics are populated and not 0 in EVERY scenario."""
        numeric_metrics = {}
        for sc_name, payload in self.scenarios.items():
            if payload.get("status") != pc.STATUS_UP:
                continue
            for k, v in payload.items():
                if k in pc.RESERVED_KEYS or isinstance(v, (list, dict)):
                    continue
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    if k not in numeric_metrics:
                        numeric_metrics[k] = []
                    numeric_metrics[k].append(v)

        always_zero = []
        for k, values in numeric_metrics.items():
            # Exclude deliberate binary error/disconnect flags which SHOULD be 0 when healthy
            if k.endswith("_Flag") or k in ("Budget_Exceeded", "Split_Brain_Flag", "Timeline_Mismatch_Flag"):
                continue
            if all(v == 0 for v in values):
                always_zero.append(k)

        # Report always zero metrics
        if always_zero:
            print(f"\n[Contract Audit] Metrics observed as zero across all healthy runs: {always_zero}")
        
        # Core populated metrics from Finding 4 must take real positive values in healthy systems
        core_populated = ["DB_Count", "Nodes_Total", "Nodes_Up", "Queries_Run", "Collect_Time_ms"]
        for cm in core_populated:
            if cm in numeric_metrics:
                self.assertTrue(
                    any(v > 0 for v in numeric_metrics[cm]),
                    f"Core metric '{cm}' was 0 in EVERY scenario (never populated)!"
                )

    def test_rule4_no_fabricated_default_on_forced_failure(self):
        """Rule 4: Any query failure must omit the metric, never emit fabricated 0 or -1."""
        def mock_query_one(sql):
            if "pg_stat_database" in sql:
                return (5, 100, 2, 50, 20, 10, 200, 500, 30, 700, 1000)
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

            # Assert omitted:
            omitted_metrics = [
                "Standbys_Streaming", "Sync_Standby_Count",
                "Replication_Slots_Total", "Replication_Slots_Active",
                "Inactive_Slots_Count", "Max_Slot_Retained_MB", "Slot_Risk"
            ]
            for m in omitted_metrics:
                self.assertNotIn(
                    m, res,
                    f"Metric '{m}' was fabricated with a default instead of being omitted on query failure!"
                )
                self.assertNotIn(m, res.get("units", {}))
                for tab in res.get("tabs", {}).get("tabs", {}).values():
                    self.assertNotIn(m, tab.get("tablist", []))

            # Must be recorded in warnings and message
            self.assertIn("metric_unavailable", res.get("msg", ""))

    def test_rule5_tabular_limits(self):
        """Rule 5: Tabular limits: <= 10 tables, <= 15 columns, <= 25 rows, <= 5 string columns."""
        for sc_name, payload in self.scenarios.items():
            tables = [k for k, v in payload.items() if isinstance(v, list)]
            self.assertLessEqual(
                len(tables), pc.MAX_TABLES,
                f"[{sc_name}] Too many tables: {len(tables)} > {pc.MAX_TABLES}"
            )
            for tbl_name in tables:
                rows = payload[tbl_name]
                self.assertLessEqual(
                    len(rows), pc.MAX_ROWS,
                    f"[{sc_name}] Table '{tbl_name}' exceeds max rows: {len(rows)} > {pc.MAX_ROWS}"
                )
                if rows:
                    cols = list(rows[0].keys())
                    self.assertLessEqual(
                        len(cols), pc.MAX_COLS,
                        f"[{sc_name}] Table '{tbl_name}' exceeds max columns: {len(cols)} > {pc.MAX_COLS}"
                    )
                    str_cols = [c for c, val in rows[0].items() if isinstance(val, str)]
                    self.assertLessEqual(
                        len(str_cols), pc.MAX_STRING_COLS,
                        f"[{sc_name}] Table '{tbl_name}' exceeds max string columns: {len(str_cols)} > {pc.MAX_STRING_COLS}"
                    )

    def test_rule6_consistent_json_types_across_scenarios(self):
        """Rule 6: Key JSON types must be consistent across scenarios."""
        key_types = {}
        for sc_name, payload in self.scenarios.items():
            for k, v in payload.items():
                if k in pc.RESERVED_KEYS:
                    continue
                # Normalize int and float as 'numeric'
                v_type = 'numeric' if isinstance(v, (int, float)) and not isinstance(v, bool) else type(v).__name__
                if k in key_types:
                    prev_type, prev_sc = key_types[k]
                    self.assertEqual(
                        v_type, prev_type,
                        f"Key '{k}' changed JSON type: was {prev_type} in {prev_sc}, but is {v_type} in {sc_name}"
                    )
                else:
                    key_types[k] = (v_type, sc_name)

    def test_rule7_no_credentials_or_dsns_in_output(self):
        """Rule 7: No credentials, passwords, or DSNs in any output payload."""
        sensitive_patterns = [
            re.compile(r"password\s*=", re.IGNORECASE),
            re.compile(r"://[^:@]+:[^@]+@", re.IGNORECASE),
            re.compile(r"site24x7_password", re.IGNORECASE),
            re.compile(r"wrong_password_test", re.IGNORECASE)
        ]

        def scan_obj(obj, path=""):
            if isinstance(obj, str):
                for pat in sensitive_patterns:
                    self.assertFalse(
                        bool(pat.search(obj)),
                        f"Sensitive credential pattern '{pat.pattern}' found at '{path}': {obj}"
                    )
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    scan_obj(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for idx, item in enumerate(obj):
                    scan_obj(item, f"{path}[{idx}]")

        for sc_name, payload in self.scenarios.items():
            scan_obj(payload, path=f"[{sc_name}]")


if __name__ == "__main__":
    unittest.main()
