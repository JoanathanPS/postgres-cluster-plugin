# Structure diff: standalone `postgres` vs `postgres_cluster`

This document describes the current output schema from `postgres/postgres.py` and `upstream_layout/postgres_cluster/postgres_cluster.py`. It is a source-level mapping; console display can vary by agent/template registration. The official standalone installation and metric reference is [Site24x7's PostgreSQL plugin README](https://raw.githubusercontent.com/site24x7/plugins/master/postgres/README.md).

## Summary metrics

The standalone plugin exposes its summary attributes without custom tabs. The cluster plugin retains the shared summary metrics from the active primary and adds `Cluster Health` and `Nodes Up`. `Server Version` remains textual. Some additional textual WAL/archive values may also appear depending on the current metric template.

Shared summary metric names: `Active Connections`, `Active Queries`, `Active Waiting Queries`, `Cache Hit Ratio`, `Database Count`, `Heap Blocks Hit`, `Heap Blocks Read`, `Index Rows Fetched`, `Index Rows Read`, `Index Scans`, `Locks Count`, `Max Connections`, `Table Count`, and `Uptime`.

## Cluster tabs and tables

| Cluster tab | Data |
| --- | --- |
| Cluster | Topology, primary count/timeline, failover metadata; `Cluster_Info` and `Cluster_Nodes` |
| Replication | Streaming links, lag, slots, logical/mesh status; `Replication_Links` and `Replication_Slots` |
| Node Performance | I/O, database activity, checkpoints; `Node_IO`, `Node_Checkpoints`, and `Stats_per_DB` |
| Transactions and Sessions | Activity and transaction/session counters; `Node_Activity`, `Node_Transactions`, and `Transactions_Per_Database` |
| WAL and Recovery | WAL positions/size, archive status, recovery conflicts; charts only |

There are ten child tables in total, within Site24x7's table/row/column limits. Exact columns and units are listed in the cluster README.

## Parity and differences

- Shared standalone query formulas are reused for the flat primary metrics and the two per-database tables, with version-specific checkpoint queries.
- Standalone flat values that were stringified are emitted as JSON numbers by the cluster plugin. Per-node tables provide selected metrics for each reachable node; the complete standalone metric set is not duplicated as flat metrics for every node.
- `Locks Count` may differ because the standalone collector's own transaction contributes locks to its query.
- On PostgreSQL 17+, the standalone collector omits `Buffers Backend` and `Buffers Backend Fsync`; the cluster collector now omits them too.
- The per-database transaction rows are not guaranteed to match row-for-row: the cluster filters null database names explicitly, while the standalone drops the first fetched row.
- Cluster-only metrics include topology, replication, failover history, WAL/archive telemetry, logical replication, and health state.

## Site24x7 limits

The cluster output is designed for a maximum of 10 tables, 15 columns per table, 25 rows per table, 5 string columns per table including the reserved `name` column, and 200 generic metrics. Tables over 25 rows are truncated; the collector's truncation notice is reported in `msg`.
