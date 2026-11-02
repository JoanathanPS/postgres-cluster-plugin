# Site24x7 PostgreSQL Cluster Monitoring Plugin

The Site24x7 PostgreSQL Cluster Monitoring plugin provides end-to-end cluster-level observability across all primary and standby nodes as a unified cohesive system. It dynamically tracks cluster topology, auto-detects active primaries, monitors failover progression and timeline increments, alerts on split-brain or no-primary conditions, tracks streaming replication lag and slots, audits WAL generation and archiving, surfaces per-node database activity and checkpoints, and tracks standby query recovery conflicts across 7 specialized dashboard tabs.

---

## Key Capabilities

- **Unified Cluster Topology**: Monitors multiple PostgreSQL endpoints simultaneously under a single Site24x7 monitor instance (eliminating the need to deploy and manage separate monitors per node).
- **Cluster Manager Auto-Detection**: Dynamically inspects engine catalogs, extensions, endpoints, and environment signatures to identify the underlying HA orchestrator or cloud platform (reporting `Cluster Type` and a concise `Cluster Type Evidence` string < 100 characters).
- **Dynamic Primary Discovery & Auto-Failover**: Evaluates all configured nodes concurrently in sub-second probes to determine the active primary and standbys. On failover, the plugin automatically follows the newly elected primary and tracks the new WAL timeline without configuration updates.
- **Critical Cluster Health Flags**:
  - `No Primary Flag`: Alerts immediately if zero reachable nodes are operating in read-write primary mode (cluster outage or in-flight election).
  - `Split Brain Flag`: Critical alert if multiple nodes simultaneously report primary status.
  - `Standby Disconnect Flag`: Alerts if fewer standbys are actively streaming than expected.
- **Dedicated Replication Telemetry**:
  - `Replication_Standbys` & `Replication_Slots` child tables on the `Replication` tab.
  - Exact byte lag (`replay_lag_bytes`, `write_lag_bytes`, `flush_lag_bytes`) and time delay (`replay_delay_s`, `Max Replay Delay`).
  - Active, inactive, physical, and logical replication slot monitoring with retained WAL tracking (`Max Slot Lag Bytes`).
- **Per-Node Standalone Telemetry**: Standalone metrics from official `postgres.py` are collected across **all** reachable cluster nodes (primary AND standby) via 4 dedicated child tables:
  - `Node_Activity` (active queries, waiting queries, idle transactions, connections).
  - `Node_Throughput` (commits, rollbacks, disk blocks read/hit, tuples DML).
  - `Node_Checkpoints` (checkpoints timed/requested, write/sync time, buffers written).
  - `Standby_Conflicts` (conflicts on locks, snapshots, buffer pins, deadlocks, tablespaces).
- **7 Organized Dashboard Tabs**: Grouped cleanly into Cluster, Replication, DB and IO stats, BG Writer, Transactions and Sessions, Write Ahead Log, and Recovery Conflicts.
- **Always-Emitted Archive & WAL Telemetry**: `Archive Mode`, `Archive Status Success`, `Archive Status Failed`, `Archive Ready Files Count`, and `Last Archived WAL File` are always emitted with valid default values (never omitted when archiving is disabled).

---

## Tested Clusters Matrix

In accordance with engineering standards, no unsubstantiated "100% compatibility" claims are made. Every supported cluster manager and topology is classified by its verified status:

| Cluster Manager / Architecture | Verification Status | Verification Methodology & Evidence | Evidence Signature (<100 chars) |
| :--- | :--- | :--- | :--- |
| **Patroni HA** | **Tested Live** | Verified against live 3-node containerized cluster with DCS (etcd). Tested automatic failover, REST API probes, timeline increment (19 -> 20), and node recovery. | `Patroni REST API response (scope: patroni-cluster, v4.0.4)` |
| **Streaming Replication (Unmanaged)** | **Tested Live** | Verified against live 2-node PostgreSQL 16 cluster. Validated baseline detection, `pg_promote()` manual failover, split-brain alert detection, and single promoted primary stabilization. | `PostgreSQL physical streaming replication (1 standbys)` |
| **repmgr** | **Fixture Validated** | Verified via test fixture detecting `repmgr` extension and `repmgr.nodes` topology catalog table. | `repmgr extension / repmgr.nodes catalog found` |
| **pg_auto_failover** | **Fixture Validated** | Verified via test fixture detecting `pgautofailover` extension and `pgautofailover_standby` replication slot. | `pgautofailover extension / standby slot found` |
| **CloudNativePG (CNPG)** | **Fixture Validated** | Verified via test fixture detecting Kubernetes CNPG operator replication slot pattern `_cnpg_*`. | `CloudNative-PG replication slot pattern _cnpg_* found` |
| **Stolon** | **Fixture Validated** | Verified via test fixture detecting Stolon keeper slot pattern `stolon_*` and application name signatures. | `Stolon replication slot / app pattern found` |
| **Citus Distributed** | **Fixture Validated** | Verified via test fixture detecting `citus` distributed coordinator extension. | `citus distributed extension installed` |
| **AWS Aurora PostgreSQL** | **Fixture Validated** | Verified via test fixture detecting `aurora_version()` engine function. | `aurora_version() function detected` |
| **AWS RDS PostgreSQL** | **Fixture Validated** | Verified via test fixture detecting Amazon RDS administrative role `rds_superuser`. | `rds_superuser role detected` |
| **Azure Database for PostgreSQL**| **Fixture Validated** | Verified via test fixture detecting Azure managed service role `azure_pg_admin`. | `azure_pg_admin role detected` |
| **GCP Cloud SQL PostgreSQL** | **Fixture Validated** | Verified via test fixture detecting Google Cloud SQL administrative role `cloudsqlsuperuser`. | `cloudsqlsuperuser role detected` |
| **Mixed / HA Conflict** | **Fixture Validated** | Verified via test fixture detecting contradictory HA orchestrator signatures, safely categorized as `mixed/unknown`. | `Conflicting evidence: Patroni and repmgr detected` |
| **Standalone PostgreSQL** | **Fixture Validated** | Verified via test fixture detecting standalone instance with zero active streaming standbys. | `Single PostgreSQL instance without active streaming standbys` |

---

## Dashboard Tabs & Child Tables Reference

The plugin organizes telemetry across **7 dedicated dashboard tabs** and **9 child tables** (strictly adhering to Site24x7 plugin limits of <= 10 child tables, <= 15 columns, and <= 25 rows per table):

### Dashboard Tabs

1. **`Cluster`** (`order: 1`):
   - **Metrics**: `Nodes Total`, `Nodes Up`, `Primary Count`, `No Primary Flag`, `Split Brain Flag`, `Primary Timeline`, `Cluster Type`, `Cluster Type Evidence`, `Cluster Summary`, `Cluster Name`, `Server Version`, `Server PID`, `Uptime`.
   - **Child Table**: `Cluster_Nodes`.
2. **`Replication`** (`order: 2`):
   - **Metrics**: `Standbys Expected`, `Standbys Streaming`, `Standby Disconnect Flag`, `Sync Standby Count`, `Cascading Standby Count`, `Max Replay Backlog`, `Max Replay Delay`, `Replication Slots Total`, `Replication Slots Active`, `Replication Slots Inactive`, `Physical Slots`, `Logical Slots`, `Max Slot Lag Bytes`.
   - **Child Tables**: `Replication_Standbys`, `Replication_Slots`.
3. **`DB and IO stats`** (`order: 3`):
   - **Metrics**: `Database Count`, `Table Count`, `Total Block Reads`, `Total Block Hits`, `Heap Blocks Read`, `Heap Blocks Hit`, `Cache Hit Ratio`, `Dead Tuples`, `Total Rows Inserted`, `Total Rows Updated`, `Total Rows Deleted`, `Total Rows Fetched`, `Total Rows Returned`, `Index Scans`, `Index Rows Read`, `Index Rows Fetched`.
   - **Child Tables**: `Stats_per_DB`, `Node_Throughput`.
4. **`BG Writer`** (`order: 4`):
   - **Metrics**: `Checkpoints Timed`, `Checkpoints Req`, `Checkpoint Write Time`, `Checkpoint Sync Time`, `Buffers Checkpoint`, `Buffers Clean`, `Maxwritten Clean`, `Buffers Alloc`.
   - **Child Table**: `Node_Checkpoints`.
5. **`Transactions and Sessions`** (`order: 5`):
   - **Metrics**: `Total Commits`, `Total Rollbacks`, `Total Sessions`, `Total Sessions Abandoned`, `Total Sessions Fatal`, `Total Sessions Killed`, `Transactions Open`, `Transactions Idle In Transaction`.
   - **Child Tables**: `Tranasctions_and_Session_per_Database`, `Node_Activity`.
6. **`Write Ahead Log`** (`order: 6`):
   - **Metrics**: `WAL Write Position`, `WAL Insert Position`, `WAL Flush Position`, `WAL Files Count`, `WAL Total Size`, `Archive Mode`, `Archive Status Success`, `Archive Status Failed`, `Archive Ready Files Count`, `Last Archived WAL File`.
7. **`Recovery Conflicts`** (`order: 7`):
   - **Metrics**: `Active Connections`, `Max Connections`, `Available Connections`, `Connection Utilization Percent`, `Superuser Reserved Connections`, `Active Queries`, `Active Waiting Queries`, `Locks Count`, `Conflicts Tablespace`, `Conflicts Lock`, `Conflicts Snapshot`, `Conflicts Buffer Pin`, `Conflicts Deadlock`, `Recovery Conflicts Total`, `Oldest Running Transaction Age`, `Oldest Transaction ID Age`.
   - **Child Table**: `Standby_Conflicts`.

---

### Child Tables Specification

| Child Table Name | Tab | Key Columns & Metrics | Scope |
| :--- | :--- | :--- | :--- |
| `Cluster_Nodes` | `Cluster` | `name`, `role`, `patroni_state`, `up`, `is_primary`, `timeline`, `response_time_ms`, `replay_backlog_bytes`, `replay_delay_s`, `connections`, `status` | All configured cluster nodes |
| `Replication_Standbys` | `Replication` | `name`, `client_addr`, `state`, `sync_state`, `is_sync`, `replay_lag_bytes`, `write_lag_bytes`, `flush_lag_bytes` | Streaming standbys connected to primary |
| `Replication_Slots` | `Replication` | `slot_name`, `plugin`, `slot_type`, `database`, `active`, `retained_lag_bytes` | Replication slots defined on primary |
| `Node_Activity` | `Transactions and Sessions` | `node`, `role`, `active_queries`, `waiting_queries`, `idle_in_tx`, `connections` | Per-node activity across all nodes |
| `Node_Throughput` | `DB and IO stats` | `node`, `role`, `commits`, `rollbacks`, `blks_read`, `blks_hit`, `tup_inserted`, `tup_updated`, `tup_deleted` | Per-node database DML & IO across all nodes |
| `Node_Checkpoints` | `BG Writer` | `node`, `role`, `checkpoints_timed`, `checkpoints_req`, `write_time_ms`, `sync_time_ms`, `buffers_checkpoint`, `buffers_clean`, `buffers_backend` | Per-node checkpointer / bgwriter across all nodes |
| `Standby_Conflicts` | `Recovery Conflicts` | `node`, `confl_lock`, `confl_snapshot`, `confl_bufferpin`, `confl_deadlock`, `confl_tablespace`, `confl_total` | Per-node recovery conflict audit |
| `Stats_per_DB` | `DB and IO stats` | Database-level disk, cache, and row throughput | Primary database instances |
| `Tranasctions_and_Session_per_Database` | `Transactions and Sessions` | Database-level session and transaction lifecycle | Primary database instances |

---

## Full Telemetry Coverage Map (98 Items)

This table establishes complete coverage parity between legacy metrics from **PR #442** (`postgres_cluster` v1) and official **standalone PostgreSQL plugin** (`postgres.py`) against **v2** equivalents and dashboard tabs. 100% parity is asserted by automated unit tests:

| Old Item / Metric | Source | Type | v2 Equivalent | Dashboard Tab |
| :--- | :--- | :--- | :--- | :--- |
| Active Connections | standalone_postgres | metric | Active Connections | Recovery Conflicts |
| Active Queries | standalone_postgres | metric | Active Queries | Recovery Conflicts |
| Active Waiting Queries | standalone_postgres | metric | Active Waiting Queries | Recovery Conflicts |
| Buffers Alloc | standalone_postgres | metric | Buffers Alloc | BG Writer |
| Buffers Checkpoint | standalone_postgres | metric | Buffers Checkpoint | BG Writer |
| Buffers Clean | standalone_postgres | metric | Buffers Clean | BG Writer |
| Cache Hit Ratio | standalone_postgres | metric | Cache Hit Ratio | DB and IO stats |
| Checkpoint Sync Time | standalone_postgres | metric | Checkpoint Sync Time | BG Writer |
| Checkpoint Write Time | standalone_postgres | metric | Checkpoint Write Time | BG Writer |
| Checkpoints Req | standalone_postgres | metric | Checkpoints Req | BG Writer |
| Checkpoints Timed | standalone_postgres | metric | Checkpoints Timed | BG Writer |
| Database Count | standalone_postgres | metric | Database Count | DB and IO stats |
| Heap Blocks Hit | standalone_postgres | metric | Heap Blocks Hit | DB and IO stats |
| Heap Blocks Read | standalone_postgres | metric | Heap Blocks Read | DB and IO stats |
| Index Rows Fetched | standalone_postgres | metric | Index Rows Fetched | DB and IO stats |
| Index Rows Read | standalone_postgres | metric | Index Rows Read | DB and IO stats |
| Index Scans | standalone_postgres | metric | Index Scans | DB and IO stats |
| Locks Count | standalone_postgres | metric | Locks Count | Recovery Conflicts |
| Max Connections | standalone_postgres | metric | Max Connections | Recovery Conflicts |
| Maxwritten Clean | standalone_postgres | metric | Maxwritten Clean | BG Writer |
| Server Version | standalone_postgres | metric | Server Version | Cluster |
| Stats_per_DB | standalone_postgres | table | Stats_per_DB | DB and IO stats |
| Table Count | standalone_postgres | metric | Table Count | DB and IO stats |
| Total Block Hits | standalone_postgres | metric | Total Block Hits | DB and IO stats |
| Total Block Reads | standalone_postgres | metric | Total Block Reads | DB and IO stats |
| Total Commits | standalone_postgres | metric | Total Commits | Transactions and Sessions |
| Total Conflicts | standalone_postgres | metric | Total Conflicts | Transactions and Sessions |
| Total Rollbacks | standalone_postgres | metric | Total Rollbacks | Transactions and Sessions |
| Total Rows Deleted | standalone_postgres | metric | Total Rows Deleted | DB and IO stats |
| Total Rows Fetched | standalone_postgres | metric | Total Rows Fetched | DB and IO stats |
| Total Rows Inserted | standalone_postgres | metric | Total Rows Inserted | DB and IO stats |
| Total Rows Returned | standalone_postgres | metric | Total Rows Returned | DB and IO stats |
| Total Rows Updated | standalone_postgres | metric | Total Rows Updated | DB and IO stats |
| Total Sessions | standalone_postgres | metric | Total Sessions | Transactions and Sessions |
| Total Sessions Abandoned | standalone_postgres | metric | Total Sessions Abandoned | Transactions and Sessions |
| Total Sessions Fatal | standalone_postgres | metric | Total Sessions Fatal | Transactions and Sessions |
| Total Sessions Killed | standalone_postgres | metric | Total Sessions Killed | Transactions and Sessions |
| Tranasctions_and_Session_per_Database | standalone_postgres | table | Tranasctions_and_Session_per_Database | Transactions and Sessions |
| Transactions Idle In Transaction | standalone_postgres | metric | Transactions Idle In Transaction | Transactions and Sessions |
| Transactions Open | standalone_postgres | metric | Transactions Open | Transactions and Sessions |
| Uptime | standalone_postgres | metric | Uptime | Cluster |
| Active Connections | pr442 | metric | Active Connections | Recovery Conflicts |
| Active Replication Slots | pr442 | metric | Replication Slots Active | Replication |
| Archive Ready Files Count | pr442 | metric | Archive Ready Files Count | Write Ahead Log |
| Archive Status Failed | pr442 | metric | Archive Status Failed | Write Ahead Log |
| Archive Status Success | pr442 | metric | Archive Status Success | Write Ahead Log |
| Available Connections | pr442 | metric | Available Connections | Recovery Conflicts |
| Buffers Allocated | pr442 | metric | Buffers Alloc | BG Writer |
| Buffers Backend Direct Writes | pr442 | column | buffers_backend | BG Writer |
| Buffers Checkpoint | pr442 | metric | Buffers Checkpoint | BG Writer |
| Buffers Clean | pr442 | metric | Buffers Clean | BG Writer |
| Checkpoint Sync | pr442 | metric | Checkpoint Sync Time | BG Writer |
| Checkpoint Write | pr442 | metric | Checkpoint Write Time | BG Writer |
| Checkpoints Requested | pr442 | metric | Checkpoints Req | BG Writer |
| Checkpoints Timed | pr442 | metric | Checkpoints Timed | BG Writer |
| Cluster Name | pr442 | metric | Cluster Name | Cluster |
| Cluster Nodes | pr442 | table | Cluster_Nodes | Cluster |
| Cluster Status | pr442 | metric | status | Cluster |
| Conflicts Buffer Pin | pr442 | metric | Conflicts Buffer Pin | Recovery Conflicts |
| Conflicts Deadlock | pr442 | metric | Conflicts Deadlock | Recovery Conflicts |
| Conflicts Lock | pr442 | metric | Conflicts Lock | Recovery Conflicts |
| Conflicts Snapshot | pr442 | metric | Conflicts Snapshot | Recovery Conflicts |
| Conflicts Tablespace | pr442 | metric | Conflicts Tablespace | Recovery Conflicts |
| Connection Utilization Percent | pr442 | metric | Connection Utilization Percent | Recovery Conflicts |
| Current WAL LSN | pr442 | metric | WAL Write Position | Write Ahead Log |
| Flush Lag | pr442 | column | flush_lag_bytes | Replication |
| Inactive Replication Slots | pr442 | metric | Replication Slots Inactive | Replication |
| Is In Recovery | pr442 | column | is_primary | Cluster |
| Last Archived WAL File | pr442 | metric | Last Archived WAL File | Write Ahead Log |
| Last Received LSN | pr442 | metric | WAL Flush Position | Replication |
| Last Replayed LSN | pr442 | metric | Max Replay Backlog | Replication |
| Logical Slots | pr442 | metric | Logical Slots | Replication |
| Max Connections | pr442 | metric | Max Connections | Recovery Conflicts |
| Maxwritten Clean | pr442 | metric | Maxwritten Clean | BG Writer |
| Node Role | pr442 | column | role | Cluster |
| Oldest Running Transaction Age | pr442 | metric | Oldest Running Transaction Age | Recovery Conflicts |
| Physical Slots | pr442 | metric | Physical Slots | Replication |
| PostgreSQL Version | pr442 | metric | Server Version | Cluster |
| Receive Apply Lag | pr442 | metric | Max Replay Backlog | Replication |
| Recovery Conflicts Total | pr442 | metric | Recovery Conflicts Total | Recovery Conflicts |
| Replay Lag | pr442 | metric | Max Replay Backlog | Replication |
| Replay Lag Time | pr442 | metric | Max Replay Delay | Replication |
| Replica Count | pr442 | metric | Standbys Streaming | Replication |
| Replication Lag | pr442 | metric | Max Replay Backlog | Replication |
| Replication Slot Count | pr442 | metric | Replication Slots Total | Replication |
| Replication State | pr442 | column | state | Replication |
| Server PID | pr442 | metric | Server PID | Cluster |
| Server Uptime | pr442 | metric | Uptime | Cluster |
| Slot Lag | pr442 | metric | Max Slot Lag Bytes | Replication |
| Superuser Reserved Connections | pr442 | metric | Superuser Reserved Connections | Recovery Conflicts |
| Sync State | pr442 | column | sync_state | Replication |
| Timeline ID | pr442 | metric | Primary Timeline | Cluster |
| WAL Files Count | pr442 | metric | WAL Files Count | Write Ahead Log |
| WAL Flush LSN | pr442 | metric | WAL Flush Position | Write Ahead Log |
| WAL Insert LSN | pr442 | metric | WAL Insert Position | Write Ahead Log |
| WAL Receiver Status | pr442 | metric | Standbys Streaming | Replication |
| WAL Total Size | pr442 | metric | WAL Total Size | Write Ahead Log |
| Write Lag | pr442 | column | write_lag_bytes | Replication |

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
nodes = "192.168.1.10:5432,192.168.1.11:5432,192.168.1.12:5432"
username = "site24x7"
password = "your_password"
db = "postgres"
patroni_port = "8008"
```

> **Note on Windows `redirect_output`**: Setting `redirect_output = 1` in `[global_configurations]` is required on Windows agents. It directs the agent to capture plugin JSON through temporary file redirection instead of anonymous pipes, eliminating pipe buffer deadlock when child table JSON exceeds 4 KB.

---

## Verification & Testing Suite

The repository includes a comprehensive test suite to validate every claim and operational requirement:

- **Upstream Layout Integrity**:
  ```powershell
  .\check-layout.ps1
  ```
- **Automated Plugin & Concurrency Test Suite**:
  ```powershell
  python tester/test_cluster_plugin.py
  ```
- **End-to-End Orchestrated Pipeline**:
  ```powershell
  .\tester\e2e.ps1 -Mode quick -SkipConsole
  ```
