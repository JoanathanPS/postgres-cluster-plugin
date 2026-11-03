# Site24x7 PostgreSQL Cluster Monitoring Plugin

The Site24x7 PostgreSQL Cluster Monitoring plugin provides end-to-end cluster-level observability across all primary and standby nodes as a unified cohesive system. It dynamically tracks cluster topology, auto-detects active primaries, monitors failover progression and timeline increments, alerts on split-brain or no-primary conditions, tracks streaming replication lag and slots, audits WAL generation and archiving, surfaces per-node database activity and checkpoints, and tracks standby query recovery conflicts across 4 specialized, easy-to-read dashboard tabs.

---

## Key Capabilities

- **Unified Cluster Topology**: Monitors multiple PostgreSQL endpoints simultaneously under a single Site24x7 monitor instance (eliminating the need to deploy and manage separate monitors per node).
- **Cluster Manager Auto-Detection**: Dynamically inspects engine catalogs, extensions, endpoints, and environment signatures to identify the underlying HA orchestrator or cloud platform (reporting `Cluster Type` and a concise `Cluster Type Evidence` string < 100 characters).
- **Dynamic Primary Discovery & Auto-Failover**: Evaluates all configured nodes concurrently in sub-second probes to determine the active primary and standbys. On failover, the plugin automatically follows the newly elected primary and tracks the new WAL timeline without configuration updates.
- **Hierarchical Cluster Health Evaluation**: Evaluates cluster state dynamically into `Cluster Health` (0: Healthy, 1: Degraded, 2: Critical) and reports an actionable `Cluster Health Reason` (<100 characters).
- **Dedicated Replication Telemetry**:
  - `Replication_Standbys` & `Replication_Slots` child tables on the `Replication` tab.
  - Exact byte lag (`replay_lag_bytes`, `write_lag_bytes`, `flush_lag_bytes`) and time delay (`replay_lag_s`, `Max Replay Delay`).
  - Active, inactive, physical, and logical replication slot monitoring with retained WAL tracking (`Max Slot Lag Bytes`).
- **Per-Node Standalone Telemetry**: Standalone metrics from official `postgres.py` are collected across **all** reachable cluster nodes (primary AND standby) via 5 dedicated child tables:
  - `Node_IO` (insert/update/delete/fetch/return tuples, block reads/hits, heap reads/hits, cache hit ratio, index scans/reads/fetches).
  - `Node_Checkpoints` (checkpoints timed/requested, write/sync time, buffers written).
  - `Node_Activity` (active queries, waiting queries, idle transactions, connections, locks, uptime).
  - `Node_Transactions` (commits, rollbacks, conflicts, sessions abandoned/fatal/killed).
  - `Standby_Conflicts` (conflicts on locks, snapshots, buffer pins, deadlocks, tablespaces).
- **4 Intuitive Dashboard Tabs**: Logically partitioned into `Cluster`, `Replication`, `Node Performance`, and `Transactions and Sessions`.
- **Always-Emitted Archive & WAL Telemetry**: `Archive Mode`, `Archive Status Success`, `Archive Status Failed`, `Archive Ready Files Count`, and `Last Archived WAL File` are always emitted with valid default values (never omitted when archiving is disabled).

---

## Cluster Health Rules

The plugin computes `Cluster Health` as an integer status code (`0` = Healthy, `1` = Degraded, `2` = Critical) alongside a human-readable `Cluster Health Reason` string (< 100 characters). The rules evaluate top-down, returning the first matching rule:

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

## 4-Tab Dashboard Architecture

The dashboard is structured into exactly 4 specialized tabs, each answering a critical operational question:

```
+--------------------------------------------------------------------------------------------------------+
|                                  PostgreSQL Cluster Plugin Dashboard                                   |
+-----------------------------------+------------------------------------+-------------------------------+
|  1. Cluster                       |  2. Replication                    |  3. Node Performance          |  4. Transactions & Sessions
|  "What is cluster topology,       |  "Are standbys caught up, and      |  "How are nodes performing    |  "What is the transactional
|   manager type, and health?"      |   are WAL/slots stable?"           |   in I/O and checkpoints?"    |   load & connection state?"
+-----------------------------------+------------------------------------+-------------------------------+
```

### Tab 1: "Cluster"
- **Question Answered**: *What is the cluster topology, manager type, active primary, timeline, and overall cluster health?*
- **Flat Metrics (Primary Baseline)**:
  - `Cluster Type`: Detected orchestrator (`Patroni`, `repmgr`, `streaming replication`, `standalone`, etc.).
  - `Cluster Health`: Health status code (0: Healthy, 1: Degraded, 2: Critical).
  - `Cluster Health Reason`: Actionable cause string (< 100 characters).
  - `Cluster Name`: Discovered cluster scope or configured name.
  - `Cluster Type Evidence`: Diagnostic evidence snippet (< 100 characters).
  - `Nodes Total`: Count of all configured endpoints.
  - `Nodes Up`: Count of currently reachable endpoints.
  - `Primary Count`: Count of active primary nodes (normally 1).
  - `No Primary Flag`: 1 if zero primaries active; 0 otherwise.
  - `Split Brain Flag`: 1 if multiple primaries active; 0 otherwise.
  - `Primary Timeline`: Active WAL timeline ID of the primary node.
  - `Timeline Mismatch Flag`: 1 if any standby timeline differs from the primary; 0 otherwise.
- **Child Table**: `Cluster_Nodes` (Per-node overview across all nodes).

### Tab 2: "Replication"
- **Question Answered**: *Are standbys replicating properly, are WAL positions progressing, and are replication slots healthy?*
- **Flat Metrics**:
  - `Standbys Expected`, `Standbys Streaming`, `Standby Disconnect Flag`.
  - `Sync Standby Count`, `Cascading Standby Count`.
  - `Max Replay Backlog` (bytes), `Max Replay Delay` (seconds).
  - `Replication Slots Total`, `Replication Slots Active`, `Replication Slots Inactive`, `Max Slot Lag Bytes`.
  - `Logical Replication In Use` (1/0).
  - `WAL Write Position` (MB), `WAL Insert Position` (MB), `WAL Flush Position` (MB).
  - `WAL Files Count`, `WAL Total Size` (MB).
  - `Archive Mode`, `Archive Status Success`, `Archive Status Failed`, `Archive Ready Files Count`, `Last Archived WAL File`.
  - `Recovery Conflicts Total`, `Conflicts Tablespace`, `Conflicts Lock`, `Conflicts Snapshot`, `Conflicts Buffer Pin`, `Conflicts Deadlock`.
  - `Oldest Running Transaction Age` (seconds).
- **Child Tables**:
  - `Replication_Standbys`: Connected streaming standbys with exact byte and second lags.
  - `Replication_Slots`: Physical and logical replication slots with active state and retained WAL bytes.
  - `Standby_Conflicts`: Per-node query conflict breakdown on standby nodes.

### Tab 3: "Node Performance"
- **Question Answered**: *How are cluster nodes performing in terms of I/O throughput, buffer allocation, cache hits, and checkpoints?*
- **Flat Metrics (Primary Baseline)**:
  - `Total Rows Inserted`, `Total Rows Updated`, `Total Rows Deleted`, `Total Rows Fetched`, `Total Rows Returned`.
  - `Total Block Reads`, `Total Block Hits`.
  - `Heap Blocks Read`, `Heap Blocks Hit`, `Cache Hit Ratio` (0.0 to 1.0 ratio).
  - `Index Scans`, `Index Rows Read`, `Index Rows Fetched`.
  - `Checkpoints Timed`, `Checkpoints Req`, `Checkpoint Write Time` (ms), `Checkpoint Sync Time` (ms).
  - `Buffers Checkpoint`, `Buffers Clean`, `Maxwritten Clean`, `Buffers Backend`, `Buffers Backend Fsync`, `Buffers Alloc`.
  - `Dead Tuples`.
- **Child Tables**:
  - `Node_IO`: Per-node DML throughput, block reads/hits, heap stats, cache hit ratio, and index usage across every cluster node.
  - `Node_Checkpoints`: Per-node checkpoint write/sync times and background writer buffer statistics across every cluster node.
  - `Stats_per_DB`: Database-level throughput, size, block reads, and hits on the primary.

### Tab 4: "Transactions and Sessions"
- **Question Answered**: *What is the concurrency, connection saturation, lock contention, and transaction throughput across nodes and databases?*
- **Flat Metrics (Primary Baseline)**:
  - `Active Connections`, `Max Connections`, `Connection Utilization Percent` (%).
  - `Active Queries`, `Active Waiting Queries`.
  - `Locks Count`, `Oldest Transaction ID Age`.
  - `Total Commits`, `Total Rollbacks`, `Total Conflicts`.
  - `Transactions Open`, `Transactions Idle In Transaction`.
  - `Total Sessions`, `Total Sessions Abandoned`, `Total Sessions Fatal`, `Total Sessions Killed`.
  - `Uptime` (seconds), `Table Count`, `Database Count`, `Server Version`, `Server PID` (*needs TL approval*).
- **Child Tables**:
  - `Node_Activity`: Per-node connections, active queries, waiting queries, idle transactions, locks, and uptime across every cluster node.
  - `Node_Transactions`: Per-node transaction commits, rollbacks, conflicts, and session lifecycle counts across every cluster node.
  - `Tranasctions_and_Session_per_Database`: Database-level session lifecycle, transaction commits/rollbacks, and active times on the primary.

---

## Child Tables Specification & Column Dictionary

The plugin defines exactly **9 child tables** (complying strictly with Site24x7 limits: max 10 tables, max 15 columns, max 25 rows, max 5 string columns per table, nested units dictionary):

| Child Table Name | Tab | Columns & Nested Units | String Columns (<=5) | Scope |
| :--- | :--- | :--- | :--- | :--- |
| `Cluster_Nodes` | `Cluster` | `name`, `role`, `cluster_type`, `patroni_state`, `upstream`, `is_cascading`, `up` (flag), `is_primary` (flag), `timeline` (timeline), `response_time_ms` (ms), `connections` (connections), `replay_backlog_bytes` (bytes), `replay_delay_s` (s), `status` (status) | 5 (`name`, `role`, `cluster_type`, `patroni_state`, `upstream`) | All configured cluster nodes |
| `Replication_Standbys` | `Replication` | `name`, `client_addr`, `state`, `sync_state`, `role`, `replay_lag_bytes` (bytes), `write_lag_bytes` (bytes), `flush_lag_bytes` (bytes), `replay_lag_s` (s), `is_sync` (flag), `status` (status) | 5 (`name`, `client_addr`, `state`, `sync_state`, `role`) | Active standbys streaming from primary |
| `Replication_Slots` | `Replication` | `name`, `plugin`, `slot_type`, `active` (flag), `wal_retained_bytes` (bytes), `status` (status) | 3 (`name`, `plugin`, `slot_type`) | All replication slots on primary |
| `Standby_Conflicts` | `Replication` | `name`, `confl_tablespace` (conflicts), `confl_lock` (conflicts), `confl_snapshot` (conflicts), `confl_bufferpin` (conflicts), `confl_deadlock` (conflicts), `total_conflicts` (conflicts), `status` (status) | 1 (`name`) | Standby nodes only |
| `Node_IO` | `Node Performance` | `name`, `rows_inserted` (rows), `rows_updated` (rows), `rows_deleted` (rows), `rows_fetched` (rows), `rows_returned` (rows), `block_reads` (blocks), `block_hits` (blocks), `heap_blocks_read` (blocks), `heap_blocks_hit` (blocks), `cache_hit_ratio` (ratio), `index_scans` (scans), `index_rows_read` (rows), `index_rows_fetched` (rows), `status` (status) | 1 (`name`) | All reachable cluster nodes |
| `Node_Checkpoints` | `Node Performance` | `name`, `checkpoints_timed` (checkpoints), `checkpoints_req` (checkpoints), `checkpoint_write_time` (ms), `checkpoint_sync_time` (ms), `buffers_checkpoint` (buffers), `buffers_clean` (buffers), `maxwritten_clean` (buffers), `buffers_backend` (buffers), `buffers_backend_fsync` (calls), `buffers_alloc` (buffers), `status` (status) | 1 (`name`) | All reachable cluster nodes |
| `Node_Activity` | `Transactions and Sessions` | `name`, `active_connections` (connections), `max_connections` (connections), `active_queries` (queries), `active_waiting_queries` (queries), `transactions_open` (transactions), `transactions_idle_in_transaction` (transactions), `locks_count` (locks), `oldest_xact_age_s` (s), `uptime` (s), `status` (status) | 1 (`name`) | All reachable cluster nodes |
| `Node_Transactions` | `Transactions and Sessions` | `name`, `commits` (transactions), `rollbacks` (transactions), `conflicts` (conflicts), `sessions` (sessions), `sessions_abandoned` (sessions), `sessions_fatal` (sessions), `sessions_killed` (sessions), `status` (status) | 1 (`name`) | All reachable cluster nodes |
| `Stats_per_DB` | `Node Performance` | `name`, `active_connections`, `size_in_mb`, `rows_inserted`, `rows_updated`, `rows_deleted`, `rows_fetched`, `rows_returned`, `block_reads`, `block_hits` | 1 (`name`) | Discovered databases on primary |
| `Tranasctions_and_Session_per_Database` | `Transactions and Sessions` | `name`, `commits`, `rollbacks`, `conflicts`, `sessions`, `sessions_abandoned`, `sessions_fatal`, `sessions_killed`, `session_time`, `sessions_active_time`, `session_idle_in_transaction_time` | 1 (`name`) | Discovered databases on primary |

---

## Tested Clusters Matrix

In accordance with rigorous engineering standards, no unsubstantiated claims are made. Every supported cluster manager and topology is classified by its verified status:

| Cluster Manager / Architecture | Verification Status | Verification Methodology & Evidence | Evidence Signature (<100 chars) |
| :--- | :--- | :--- | :--- |
| **Patroni HA** | **Tested Live** | Verified against live 3-node containerized cluster with DCS (etcd). Tested automatic failover, REST API probes, timeline increment (24 -> 25), and node recovery. | `Patroni REST API response (scope: patroni-cluster, v4.0.4)` |
| **Streaming Replication (Unmanaged)** | **Tested Live** | Verified against live 2-node PostgreSQL 16 streaming cluster. Validated baseline detection, `pg_promote()` failover, split-brain alert detection (`Split Brain Flag == 1`, Health 2), and teardown. | `PostgreSQL physical streaming replication (1 standbys)` |
| **Standalone PostgreSQL (14 & 16)** | **Tested Live** | Verified against live containerized PostgreSQL 14 and 16 standalone instances. Verified single-node detection, version extraction, and healthy status code 0. | `Single PostgreSQL instance without active streaming standbys` |
| **repmgr** | **Fixture Validated** | Verified via test fixture detecting `repmgr` extension and `repmgr.nodes` topology catalog table. | `repmgr extension / repmgr.nodes catalog found` |
| **pg_auto_failover** | **Fixture Validated** | Verified via test fixture detecting `pgautofailover` extension and `pgautofailover_standby` replication slot. | `pgautofailover extension / standby slot found` |
| **CloudNativePG (CNPG)** | **Fixture Validated** | Verified via test fixture detecting Kubernetes CNPG operator replication slot pattern `_cnpg_*`. | `CloudNative-PG replication slot pattern _cnpg_* found` |
| **Stolon** | **Fixture Validated** | Verified via test fixture detecting Stolon keeper slot pattern `stolon_*` and application name signatures. | `Stolon replication slot / app pattern found` |
| **Citus Distributed** | **Fixture Validated** | Verified via test fixture detecting `citus` distributed coordinator extension. | `citus distributed extension installed` |
| **AWS Aurora PostgreSQL** | **Fixture Validated** | Verified via test fixture detecting `aurora_version()` engine function. | `aurora_version() function detected` |
| **AWS RDS PostgreSQL** | **Fixture Validated** | Verified via test fixture detecting Amazon RDS administrative role `rds_superuser`. | `rds_superuser role detected` |
| **Azure Database for PostgreSQL** | **Fixture Validated** | Verified via test fixture detecting Azure managed service role `azure_pg_admin`. | `azure_pg_admin role detected` |
| **GCP Cloud SQL PostgreSQL** | **Fixture Validated** | Verified via test fixture detecting Google Cloud SQL administrative role `cloudsqlsuperuser`. | `cloudsqlsuperuser role detected` |
| **Mixed / HA Conflict** | **Fixture Validated** | Verified via test fixture detecting contradictory HA orchestrator signatures, safely categorized as `mixed/unknown`. | `Conflicting evidence: Patroni and repmgr detected` |

---

## Known Limitations

1. **Non-Superuser Permissions**: Non-superuser monitoring users (`site24x7`) require `pg_monitor` grant to inspect `pg_stat_replication`, `pg_stat_database`, and `pg_stat_activity`. Without `pg_monitor`, query text is obscured and lag metrics return 0.
2. **Cascading Replication Standbys**: Cascading standbys downstream of an intermediate standby cannot be directly queried for primary replication LSNs unless included in the `nodes` configuration string.
3. **Historical WAL Files**: PostgreSQL engines that keep large WAL retention directories (`wal_keep_size`) will show higher `WAL Files Count` and `WAL Total Size` without impacting real-time throughput.
4. **Site24x7 Custom Tab Promotion**: Site24x7 promotes the primary landing page based on tab order and first metric. String metrics (`Cluster Type`) render in textual attribute panels and table columns, while numeric metrics populate time-series charts.

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
     powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\Site24x7PostgresClusterPluginInstaller.ps1
     ```

### Configuration (`postgres_cluster.cfg`)

```ini
[global_configurations]
use_agent_python = 0
redirect_output = 1

[postgres_cluster]
nodes = "127.0.0.1:5441:8001,127.0.0.1:5442:8002,127.0.0.1:5443:8003"
username = "site24x7"
password = "your_password"
db = "postgres"
patroni_port = "8008"
cluster_type = "auto"
```

> **Note on Windows `redirect_output`**: Setting `redirect_output = 1` in `[global_configurations]` is required on Windows agents. It directs the agent to capture plugin JSON through temporary file redirection instead of anonymous pipes, eliminating pipe buffer deadlock when child table JSON exceeds 4 KB.
