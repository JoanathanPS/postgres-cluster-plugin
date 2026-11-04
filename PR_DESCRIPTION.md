# PR: PostgreSQL Cluster Monitoring Plugin for Site24x7

One Site24x7 plugin monitor for a whole PostgreSQL cluster. It finds the primary and the standbys, reports cluster health, replication and per-node standalone metrics, and keeps working through a failover. The plugin supersedes the partial implementation in PR #442.

The plugin lives in `upstream_layout/postgres_cluster/` (same folder layout as the upstream `postgres` plugin: `README.md`, `.cfg`, `installer/`, `prerequisites/`, `wc_automation/`).

## What it reports

- **Summary page:** the 14 charts of the standalone `postgres` plugin, plus `Cluster Health` and `Nodes Up`. `Server Version` is the textual attribute.
- **5 tabs:** Cluster, Replication, Node Performance, Transactions and Sessions, WAL and Recovery.
- **10 child tables:** `Cluster_Info`, `Cluster_Nodes`, `Replication_Standbys`, `Replication_Slots`, `Node_IO`, `Node_Checkpoints`, `Node_Activity`, `Node_Transactions`, plus the standalone plugin's `Stats_per_DB` and `Tranasctions_and_Session_per_Database`.
- **Cluster Health** 0 / 1 / 2 with a readable reason in `Cluster_Info`.
- **Per node:** every standalone parameter is also reported for every node, standbys included.

Tab layout and metric mapping: see `upstream_layout/postgres_cluster/README.md` and `STRUCTURE_DIFF.md`.

## Parity with the standalone `postgres` plugin

- The same SQL is used for every flat metric and both child tables.
- An automated test (`tester/test_cluster_plugin.py`, "OG parity") runs `postgres.py` and this plugin against the same primary and compares them.
- Known difference: `Locks Count` is lower, because `postgres.py` counts the locks of its own open transaction.
- Unreadable metrics are omitted and explained in `msg`; nothing is filled with a fake 0.

## What was tested, and how

| Area | Status |
| :--- | :--- |
| Patroni, 3 nodes, PostgreSQL 17.2 (healthy, standby down, primary down and promoted, node rejoin) | Tested live |
| Site24x7 console on a Windows agent (all 5 tabs, tables, offline node shown as offline) | Tested live |
| Same numbers as standalone `postgres.py` | Tested live (automated) |
| Bad password, wrong database, unreachable host, empty node list, duplicate names | Tested live (command line) |
| Replication lag under load | Tested live (e2e) |
| Other cluster managers (repmgr, pg_auto_failover, Stolon, CloudNativePG, Citus, multi-master) | Detection logic only, tested with made-up data; see the README for current status |
| PostgreSQL versions below 17, Linux agent, sync/cascading standbys, archiving enabled, alerts | Not tested |

## Alerts

Plugin monitors have no thresholds by default. The README lists recommended thresholds (for example `Cluster Health >= 1` Trouble, `= 2` Critical).

## Tests

- `check-layout.ps1`: 15/15.
- `tester/test_cluster_plugin.py`: 0 failures.
- `tester/e2e.ps1 -Mode full -SkipConsole`: PASS on 4 Nov 2026.
