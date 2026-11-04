# Structure diff: standalone `postgres` plugin vs `postgres_cluster`

Observed in the Site24x7 console (monitor `postgres_cluster_v3-Joana-PC.`, PostgreSQL 17.2 Patroni cluster of 3 nodes) on 4 Nov 2026. The standalone side is taken from the `tabs` and `units` definitions in `postgres/postgres.py`.

## Summary page

| | Standalone `postgres` | `postgres_cluster` |
| :--- | :--- | :--- |
| Charts | 14: Active Connections, Active Queries, Active Waiting Queries, Cache Hit Ratio, Database Count, Heap Blocks Hit, Heap Blocks Read, Index Rows Fetched, Index Rows Read, Index Scans, Locks Count, Max Connections, Table Count, Uptime | The same 14, plus `Cluster Health` and `Nodes Up` (16 charts, verified in the console) |
| Textual attributes | Server Version | Server Version, Archive Mode, Last Archived WAL File |

## Tabs

| Standalone tab | Cluster plugin tab | Charts seen in console | Tables seen in console |
| :--- | :--- | :--- | :--- |
| (none) | **Cluster** | 7: No Primary Flag, Nodes Total, Primary Count, Primary Timeline, Server PID, Split Brain Flag, Timeline Mismatch Flag | `Cluster_Info` (1 row: cluster type, evidence, version, primary node, health reason), `Cluster_Nodes` (3 rows) |
| (none) | **Replication** | 12: standbys expected/streaming, disconnect flag, sync and cascading counts, max replay backlog/delay, slots total/active/inactive, max slot lag, logical replication flag | `Replication_Standbys`, `Replication_Slots` |
| BG Writer + DB and IO stats | **Node Performance** | 16: rows inserted/updated/deleted/fetched/returned, block reads/hits, checkpoint timing and counts, buffers (alloc, checkpoint, clean), maxwritten clean, dead tuples | `Node_IO`, `Node_Checkpoints` (3 rows each), `Stats_per_DB` ("No Data Available" with a Discover button, same as the standalone monitor) |
| Transactions and Sessions | **Transactions and Sessions** | 12: commits, rollbacks, conflicts, sessions (total, abandoned, fatal, killed), idle in transaction, open, connection utilization, oldest transaction ID age, oldest running transaction age | `Node_Transactions`, `Node_Activity` (3 rows each), `Tranasctions_and_Session_per_Database` ("No Data Available" with Discover, same as standalone) |
| (none) | **WAL and Recovery** | 14: WAL positions, WAL file count and size, archive success/failed/ready, recovery conflict counters | none |

## What changed relative to the standalone plugin, and why

- Every standalone parameter exists with the same SQL. An automated test (`tester/test_cluster_plugin.py`, "OG parity") runs `postgres.py` and the cluster plugin against the same primary and compares them.
- Standalone metrics are also reported per node (`Node_IO`, `Node_Checkpoints`, `Node_Activity`, `Node_Transactions`), so each node in the cluster has the standalone parameters. The flat Summary values come from the node that is the primary at poll time.
- The `Tranasctions_and_Session_per_Database` null-name row is dropped, exactly as `postgres.py` does.
- Numeric metrics are numbers instead of strings.
- `Locks Count` is lower than the standalone plugin reports for the same SQL, because `postgres.py` counts the locks held by its own open transaction.
- `Buffers Backend` and `Buffers Backend Fsync` do not exist on PostgreSQL 17 (moved to `pg_stat_io`) and are omitted there; the standalone plugin omits them on 17 too.
- A metric that cannot be read is omitted, never replaced by 0.

## Limits used

10 tables (max 10), at most 15 columns, 25 rows and 5 string columns per table, 83 flat metrics (max 200).
