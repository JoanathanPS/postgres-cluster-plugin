# PR: PostgreSQL Cluster Monitoring Plugin for Site24x7

Monitor a PostgreSQL cluster from one Site24x7 plugin monitor. The collector discovers members where supported, identifies roles and failovers, and reports cluster health, replication, WAL, database, and per-node metrics.

The upstream-layout package is in `upstream_layout/postgres_cluster/`. Its README contains installation steps, configuration, metrics, tested cluster types, alert setup, and limitations.

## What it reports

- Standalone PostgreSQL summary metrics, collected from the active primary, plus cluster health and node availability.
- Five tabs: Cluster, Replication, Node Performance, Transactions and Sessions, and WAL and Recovery.
- Cluster-level discovery counts distinguish configured seed nodes, additional discovered members, members omitted by the 25-node display cap, and nodes polled.
- Ten child tables: `Cluster_Info`, `Cluster_Nodes`, `Replication_Links`, `Replication_Slots`, `Node_IO`, `Node_Checkpoints`, `Stats_per_DB`, `Node_Activity`, `Node_Transactions`, and `Transactions_Per_Database`.
- Per-node rows for reachable nodes in the node tables; cluster-wide topology, replication and health metrics.
- Health state `0` healthy, `1` degraded, `2` critical, with an explanation in `Cluster_Info`.

## Standalone PostgreSQL parity

The collector reuses the standalone plugin's SQL for shared metrics, with version-specific checkpoint handling. Numeric values are emitted as JSON numbers. Known differences include `Locks Count` (the standalone counts locks held by its own monitoring transaction), the representation of values, and PostgreSQL 17+ backend buffer counters, which are omitted when unavailable. The per-database transaction row handling also differs. Replay delay and backlog health thresholds are configurable. See the cluster README for the full parity notes and defaults.

## Validation coverage

The repository contains live testbeds and a live discovery runner for Patroni, plain streaming replication, repmgr, Stolon, pg_auto_failover, Citus, pgpool-II, native logical multi-master, and CloudNativePG. Coverage is not uniform: consult the README's matrix for versions and scenarios actually exercised. Linux agent installation and some failover/replication modes remain unverified.

Plugin metrics do not receive threshold values automatically. The README includes starting values for a Site24x7 Plugin Integrations threshold profile; adjust them to the cluster's recovery objectives.
