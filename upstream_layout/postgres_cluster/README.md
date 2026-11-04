# Site24x7 PostgreSQL Cluster Monitoring Plugin

The Site24x7 PostgreSQL Cluster Monitoring plugin provides end-to-end cluster-level observability across all primary and standby nodes as a unified cohesive system. It dynamically tracks cluster topology, auto-detects active primaries, monitors failover progression and timeline increments, alerts on split-brain or no-primary conditions, tracks streaming replication lag and slots, audits WAL generation and archiving, surfaces per-node database activity and checkpoints, and tracks query performance across 5 specialized, easy-to-read dashboard tabs matching the official Site24x7 standalone PostgreSQL monitoring standard.

---

## OG Tab -> Dev Tab Architecture & Mapping

In Site24x7, numeric metrics that do not belong to any tab's `tablist` are automatically promoted to charts on the default **Summary** dashboard landing page. To ensure exact console parity with the official Site24x7 standalone agent plugin (`postgres.py`) while elevating cluster-wide observability, all 14 official Summary metrics are emitted untabbed alongside cluster-level summary counters, and 5 dedicated custom tabs are defined:

| OG Standalone Tab / Section | Dev Cluster Tab / Section | Description & Included Metrics | Child Tables |
| :--- | :--- | :--- | :--- |
| **Summary (Untabbed)** | **Summary (Untabbed)** | 14 OG charts + 2 cluster summary metrics + the OG textual `Server Version`: `Active Connections`, `Active Queries`, `Active Waiting Queries`, `Cache Hit Ratio`, `Database Count`, `Heap Blocks Hit`, `Heap Blocks Read`, `Index Rows Fetched`, `Index Rows Read`, `Index Scans`, `Locks Count`, `Max Connections`, `Table Count`, `Uptime`, `Cluster Health`, `Nodes Up`, `Server Version`. | *None (Charts only)* |
| *New Cluster Section* | **Cluster** (Order 1) | Cluster topology & health charts: `Nodes Total`, `Primary Count`, `Primary Timeline`, `No Primary Flag`, `Split Brain Flag`, `Timeline Mismatch Flag`, `Server PID` (*needs TL approval*). | `Cluster_Info` (1 row metadata: type, evidence, version, primary, health reason), `Cluster_Nodes` (Per-node role, timeline, latency, connections, backlog). |
| *Replication Section* | **Replication** (Order 2) | Standby replication & slot tracking: `Standbys Expected`, `Standbys Streaming`, `Standby Disconnect Flag`, `Sync Standby Count`, `Cascading Standby Count`, `Max Replay Backlog`, `Max Replay Delay`, `Replication Slots Total/Active/Inactive`, `Max Slot Lag Bytes`, `Logical Replication In Use`. | `Replication_Standbys` (Live streaming standbys & byte/sec lags), `Replication_Slots` (Replication slots & retained WAL). |
| **DB and IO / BG Writer** | **Node Performance** (Order 3) | Primary and per-node I/O, tuples, buffers, checkpoints: `Total Rows Inserted/Updated/Deleted/Fetched/Returned`, `Total Block Reads/Hits`, `Buffers Alloc/Checkpoint/Clean/Backend/Backend Fsync`, `Checkpoint Sync/Write Time`, `Checkpoints Req/Timed`, `Maxwritten Clean`, `Dead Tuples`. | `Node_IO` (Per-node DML & cache hits), `Node_Checkpoints` (Per-node checkpoints & buffers), `Stats_per_DB` (Discovered databases on primary). |
| **Sessions and Transactions** | **Transactions and Sessions** (Order 4) | Transaction states, lock contention, sessions: `Total Commits`, `Total Rollbacks`, `Total Conflicts`, `Total Sessions`, `Total Sessions Abandoned/Fatal/Killed`, `Transactions Idle In Transaction`, `Transactions Open`, `Connection Utilization Percent`, `Oldest Transaction ID Age`, `Oldest Running Transaction Age`. | `Node_Activity` (Per-node active queries & locks), `Node_Transactions` (Per-node commits & rollbacks), `Tranasctions_and_Session_per_Database` (Discovered databases session lifecycle). |
| *New WAL Section* | **WAL and Recovery** (Order 5) | Write-ahead logging, archive telemetry, standby conflict sums: `WAL Write Position`, `WAL Insert Position`, `WAL Flush Position`, `WAL Files Count`, `WAL Total Size`, `Archive Mode`, `Archive Status Success`, `Archive Status Failed`, `Archive Ready Files Count`, `Last Archived WAL File`, `Recovery Conflicts Total`, `Conflicts Tablespace`, `Conflicts Lock`, `Conflicts Snapshot`, `Conflicts Buffer Pin`, `Conflicts Deadlock`. | *None (Charts only)* |

---

## Key Capabilities

- **Unified Cluster Topology**: Monitors multiple PostgreSQL endpoints simultaneously under a single Site24x7 monitor instance.
- **Node Discovery from One Address**: you only configure the address of any one node (or two for safety). On every poll the plugin finds the rest of the cluster, so adding or removing nodes needs no config edit. See "Node Discovery" below.
- **Cluster Manager Auto-Detection**: Dynamically inspects engine catalogs, extensions, endpoints, and environment signatures to identify the underlying HA orchestrator or cloud platform (reporting `cluster_type` and `type_evidence` in the `Cluster_Info` table).
- **Dynamic Primary Discovery & Auto-Failover**: Evaluates all configured nodes concurrently in sub-second probes to determine the active primary and standbys. On failover, the plugin automatically follows the newly elected primary and tracks the new WAL timeline without configuration updates.
- **Hierarchical Cluster Health Evaluation**: Evaluates cluster state dynamically into `Cluster Health` (0: Healthy, 1: Degraded, 2: Critical) and reports an actionable `health_reason` in `Cluster_Info`.
- **Dedicated Replication Telemetry**:
  - `Replication_Standbys` & `Replication_Slots` child tables on the `Replication` tab.
  - Exact non-negative byte lag (`replay_lag_bytes`, `write_lag_bytes`, `flush_lag_bytes`) and time delay (`replay_lag_s`, `Max Replay Delay`).
  - Active, inactive, physical, and logical replication slot monitoring with retained WAL tracking (`Max Slot Lag Bytes`).
- **Per-Node Standalone Telemetry**: Standalone metrics from official `postgres.py` are collected across **all** reachable cluster nodes (primary AND standby) via dedicated child tables (`Node_IO`, `Node_Checkpoints`, `Node_Activity`, `Node_Transactions`).
- **Alphanumeric Node Aliasing**: Node names in tables are strictly alphanumeric identifiers (e.g. `pgnode1`, `pgnode2`, `pgnode3`), ensuring clean formatting in Site24x7 child tables.
- **Strict Site24x7 Tabular Limits Compliant**: Exactly 10 child tables (limit $\le 10$), $\le 15$ columns, $\le 25$ rows, and $\le 5$ string columns (excluding `name`).
- **No Fabricated Values**: a metric that cannot be read (query failed, node unreachable, no primary) is omitted and explained in `msg`; it is never filled with a default `0`. `Last Archived WAL File` is the text `"none"` when nothing has been archived. When no primary is reachable the flat OG metrics are absent for that poll and `Cluster Health` is `2`.
- **OG Parameter Parity**: every flat metric and both child tables of the standalone `postgres.py` are reproduced with the same SQL (verified by an automated parity test that runs `postgres.py` and this plugin against the same primary). Intentional differences: values are numeric instead of strings, the `Tranasctions_and_Session_per_Database` null-name row is dropped exactly as `postgres.py` does, and `Locks Count` is lower than `postgres.py` reports because `postgres.py` counts the locks held by its own open transaction.

---

## Cluster Health Rules

The plugin computes `Cluster Health` as an integer status code (`0` = Healthy, `1` = Degraded, `2` = Critical) alongside a human-readable `health_reason` string in `Cluster_Info` (< 100 characters). The rules evaluate top-down, returning the first matching rule:

### 1. Critical (`Cluster Health = 2`)
- **No Primary**: Zero reachable nodes report read-write primary status (`Primary Count == 0`).
  - *Reason*: `Critical: No active primary node detected`
- **Split Brain**: Multiple nodes simultaneously report read-write primary status (`Primary Count > 1`), except in Multi-Master / Active-Active architectures where multiple primaries are expected.
  - *Reason*: `Critical: Split brain detected (N primary nodes active)`
- **All Standbys Disconnected**: Standbys were expected, but zero standbys are streaming (`Standbys Expected > 0` and `Standbys Streaming == 0`), except in multi-master topologies.
  - *Reason*: `Critical: No streaming standbys connected (N expected)`

### 2. Degraded (`Cluster Health = 1`)
- **Node Down**: One or more configured cluster nodes are unreachable (`Nodes Up < Nodes Total`).
  - *Reason*: `Degraded: N of M node(s) offline`
- **Standby Disconnected**: Fewer standbys are streaming than expected (`Standbys Streaming < Standbys Expected`).
  - *Reason*: `Degraded: N of M standby(s) not streaming`
- **Replay Delay Over Threshold**: Standby replication replay delay exceeds 60.0 seconds (`Max Replay Delay > 60.0s`).
  - *Reason*: `Degraded: Replay delay X.Xs exceeds threshold (60s)`
- **Replay Backlog Over Threshold**: Standby replication byte backlog exceeds 100 MB (`Max Replay Backlog > 104,857,600 bytes`).
  - *Reason*: `Degraded: Replay backlog X.XMB exceeds threshold (100MB)`
- **Inactive Replication Slot**: One or more replication slots are inactive, risking disk fill (`Replication Slots Inactive > 0`).
  - *Reason*: `Degraded: N inactive replication slot(s) found`
- **Timeline Mismatch**: Any active node's timeline diverges from the primary's timeline (`Timeline Mismatch Flag == 1`).
  - *Reason*: `Degraded: Timeline mismatch detected across cluster nodes`

### 3. Healthy (`Cluster Health = 0`)
- **Standard Single-Primary HA**: All nodes reachable, exactly 1 primary, and all expected standbys streaming.
  - *Reason*: `Cluster healthy: N/N nodes active, 1 primary, M standbys streaming`
- **Multi-Master (Active-Active)**: All concurrent master nodes reachable and replicating bidirectionally.
  - *Reason*: `Multi-master cluster healthy: N/N active master nodes replicating`

---

## Child Tables Specification & Column Dictionary

The plugin defines exactly **10 child tables** (complying strictly with Site24x7 limits: max 10 tables, max 15 columns, max 25 rows, max 5 string columns per table, nested units dictionary):

| Child Table Name | Tab | Columns & Nested Units | String Columns (<=5) | Scope |
| :--- | :--- | :--- | :--- | :--- |
| `Cluster_Info` | `Cluster` | `name`, `cluster_type`, `type_evidence`, `server_version`, `primary_node`, `health_reason`, `nodes_total`, `nodes_up`, `primary_timeline`, `status` | 5 (`cluster_type`, `type_evidence`, `server_version`, `primary_node`, `health_reason`) | Exactly 1 row for cluster-wide metadata |
| `Cluster_Nodes` | `Cluster` | `name`, `role`, `status`, `timeline`, `connections`, `replay_backlog_bytes` (bytes), `replay_delay_s` (s), `response_time_ms` (ms), `upstream`, `patroni_state`, `is_primary` (flag) | 3 (`role`, `upstream`, `patroni_state`) | All configured cluster nodes |
| `Replication_Standbys` | `Replication` | `name`, `client_addr`, `state`, `sync_state`, `replay_lag_bytes` (bytes), `write_lag_bytes` (bytes), `flush_lag_bytes` (bytes), `replay_lag_s` (s), `is_sync` (flag), `status` (status) | 3 (`client_addr`, `state`, `sync_state`) | Active standbys streaming from primary |
| `Replication_Slots` | `Replication` | `name`, `plugin`, `slot_type`, `active` (flag), `wal_retained_bytes` (bytes), `status` (status) | 2 (`plugin`, `slot_type`) | All replication slots on primary |
| `Node_IO` | `Node Performance` | `name`, `rows_inserted` (rows), `rows_updated` (rows), `rows_deleted` (rows), `rows_fetched` (rows), `rows_returned` (rows), `block_reads` (blocks), `block_hits` (blocks), `heap_blocks_read` (blocks), `heap_blocks_hit` (blocks), `cache_hit_ratio` (ratio), `index_scans` (scans), `index_rows_read` (rows), `index_rows_fetched` (rows), `status` (status) | 0 (excluding name) | All reachable cluster nodes |
| `Node_Checkpoints` | `Node Performance` | `name`, `checkpoints_timed` (checkpoints), `checkpoints_req` (checkpoints), `checkpoint_write_time` (ms), `checkpoint_sync_time` (ms), `buffers_checkpoint` (buffers), `buffers_clean` (buffers), `maxwritten_clean` (buffers), `buffers_backend` (buffers), `buffers_backend_fsync` (calls), `buffers_alloc` (buffers), `status` (status) | 0 (excluding name) | All reachable cluster nodes |
| `Stats_per_DB` | `Node Performance` | `name`, `active_connections`, `size_in_mb`, `rows_inserted`, `rows_updated`, `rows_deleted`, `rows_fetched`, `rows_returned`, `block_reads`, `block_hits` | 0 (excluding name) | Discovered databases on primary |
| `Node_Activity` | `Transactions and Sessions` | `name`, `active_connections` (connections), `max_connections` (connections), `active_queries` (queries), `active_waiting_queries` (queries), `transactions_open` (transactions), `transactions_idle_in_transaction` (transactions), `locks_count` (locks), `oldest_xact_age_s` (s), `uptime` (s), `status` (status) | 0 (excluding name) | All reachable cluster nodes |
| `Node_Transactions` | `Transactions and Sessions` | `name`, `commits` (transactions), `rollbacks` (transactions), `conflicts` (conflicts), `sessions` (sessions), `sessions_abandoned` (sessions), `sessions_fatal` (sessions), `sessions_killed` (sessions), `status` (status) | 0 (excluding name) | All reachable cluster nodes |
| `Tranasctions_and_Session_per_Database` | `Transactions and Sessions` | `name`, `commits`, `rollbacks`, `conflicts`, `sessions`, `sessions_abandoned`, `sessions_fatal`, `sessions_killed`, `session_time`, `sessions_active_time`, `session_idle_in_transaction_time` | 0 (excluding name) | Discovered databases on primary |

---

## What Happens During a Failover

All configured nodes are probed on every poll, so standby details are visible at all times, not only after a promotion. When the primary is stopped and a standby is promoted:

- `Cluster_Info` shows the new `primary_node`, the new `primary_timeline`, and `health_reason` such as `Degraded: 1 of 3 node(s) offline`.
- `Cluster_Nodes` lists every node; the stopped node has role `offline` and `status` 0.
- `Node_IO`, `Node_Checkpoints`, `Node_Activity` and `Node_Transactions` keep one row per node; the stopped node has a row with `status` 0 and no numbers, so the console never keeps showing its last good values.
- The flat Summary metrics are collected from the node that is the primary at poll time.
- If no primary is reachable, the flat OG metrics are omitted for that poll and `Cluster Health` is `2`.

## Node Discovery

Give the plugin the address of one node and it finds the others on every poll (`discover=auto`, the default; `discover=off` monitors only the nodes you list).

| Cluster | How the other nodes are found |
| :--- | :--- |
| Patroni | `GET /cluster` on the Patroni REST port of any member (exact member list, hosts, ports) |
| repmgr | `repmgr.nodes` (in the `repmgr` database or the current one) |
| Citus | `pg_dist_node` |
| pg_auto_failover | `pgautofailover.node` when you point at the monitor; from a data node the replication topology is walked |
| Stolon, CloudNativePG, plain streaming, multi-master logical replication | The replication topology is walked: `pg_stat_wal_receiver` (upstream) and `pg_stat_replication` (downstream), from every node reached |

Configuration for a cluster you want to add nodes to later:

```ini
[postgres_cluster]
nodes=10.0.0.5:5432:8008
username=site24x7
password=...
db=postgres
```

`host:port:patroni_port` is the format of each address (use `none` as the Patroni port for non-Patroni clusters). Several addresses can be given, comma separated; if the first is down the next is used. A discovered node that is already configured (same address, same alias, or same Patroni member name) is not added twice.

## Tested Clusters

"Live" means the plugin ran inside the bed's Docker or Kubernetes network with a single seed address (`tester/test_discovery_live.py`). The test beds are in `testbeds/`.

| Cluster type | Result |
| :--- | :--- |
| Patroni (3 nodes, etcd, HAProxy, PostgreSQL 17.2) | Live: all 3 nodes and roles from one member; healthy, node stopped, primary stopped and promoted, node rejoining; Site24x7 console verified |
| Plain streaming replication (2 nodes) | Live: all nodes from either the standby or the primary |
| repmgr (1 primary + 2 standbys, PostgreSQL 16) | Live: type `repmgr`, 3 nodes |
| Stolon (etcd, 3 keepers, PostgreSQL 15) | Live: type `Stolon`, 3 nodes, roles after Stolon's own election |
| pg_auto_failover (monitor + 2 nodes, PostgreSQL 11 demo image) | Live from a data node: type `pg_auto_failover`, 2 nodes |
| Citus (coordinator + 2 workers) | Live: type `Citus Distributed`, 3 nodes, no false split brain |
| Multi-master (native logical replication, 2 nodes, PostgreSQL 16) | Live: type `Multi-Master (Active-Active)`, 2 primaries, no false split brain |
| CloudNativePG (kind, operator 1.24.1, 3 instances, PostgreSQL 16) | Live, plugin run as a pod: type `CloudNative-PG`, all 3 instances found from the read-only service. Node names come from the service and pod names |
| AWS RDS/Aurora, Azure, Google Cloud SQL | Detection logic only. Not tested on real services; their node lists live in the cloud API, not in PostgreSQL |

## Known Limitations

- Discovery from the replication topology only sees a standby's IP, so the primary's port is assumed for it. Use Patroni or repmgr (exact lists) or list such nodes explicitly if they use another port.
- Discovered addresses must be reachable from the agent. Names that only resolve inside a container network show as offline nodes.
- repmgr: the monitoring user needs `USAGE` on schema `repmgr` and `SELECT` on its tables to read the catalog; without it the replication topology is walked instead.
- A node that is removed from the cluster stops being listed, but Site24x7 keeps the old row in the child tables.
- Citus: workers are separate primaries, so several primaries are not reported as split brain.
- Multi-master topologies with several primaries look like split brain unless the type is detected as multi-master.
- On managed services such as RDS Multi-AZ, standbys are usually not reachable by clients, so they appear offline.
- Database-scoped metrics (`Table Count`, heap and index statistics, `Dead Tuples`) cover only the database named in `db`, exactly as `postgres.py` does.
- `Buffers Backend` and `Buffers Backend Fsync` do not exist on PostgreSQL 17 (moved to `pg_stat_io`), so they are omitted there.
- `Server PID` is the PID of the plugin's own connection, kept only for parity with the previous cluster plugin.
- The console freezes the tabs and metric list at first registration. To change them, install under a new plugin name.

## Recommended Thresholds

Plugin monitors get no limits by default. Create one profile (Admin > Configuration Profiles > Threshold and Availability > Plugin Integrations):

| Metric | Condition | Severity |
| :--- | :--- | :--- |
| `Cluster Health` | `>= 1` | Trouble |
| `Cluster Health` | `= 2` | Critical |
| `No Primary Flag` | `= 1` | Critical |
| `Split Brain Flag` | `= 1` | Critical |
| `Replication Slots Inactive` | `> 0` | Trouble |
| `Max Replay Backlog` | `> 104857600` | Trouble |

---

## Installation & Configuration

### Automated Installation (From Cloned Repository)

1. **Clone the repository**:
   ```bash
   git clone -b upstream-layout https://github.com/JoanathanPS/postgres-cluster-plugin.git
   cd postgres-cluster-plugin/upstream_layout/postgres_cluster
   ```

2. **Run Installer**:
   - **Linux**:
     ```bash
     sudo bash installer/Site24x7PostgresClusterPluginInstaller.sh
     ```
   - **Windows (PowerShell as Administrator)**:
     ```powershell
     powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\Site24x7PostgresClusterPluginInstaller.ps1 -PluginFolderName "postgres_cluster_v3" -Nodes "pgnode1=127.0.0.1:5441:8001,pgnode2=127.0.0.1:5442:8002,pgnode3=127.0.0.1:5443:8003" -Username "site24x7" -Password "site24x7" -Database "appdb" -NonInteractive -SkipAdminCheck
     ```

### Configuration (`postgres_cluster.cfg`)

```ini
[global_configurations]
use_agent_python=0
redirect_output=1

[postgres_cluster]
nodes=pgnode1=127.0.0.1:5441:8001,pgnode2=127.0.0.1:5442:8002,pgnode3=127.0.0.1:5443:8003
username=site24x7
password=site24x7
db=appdb
patroni_port=8008
cluster_type=auto
```

> **Note on Windows `redirect_output`**: Setting `redirect_output = 1` in `[global_configurations]` is required on Windows agents. It directs the agent to capture plugin JSON through temporary file redirection instead of anonymous pipes, eliminating pipe buffer deadlock when child table JSON exceeds 4 KB.
