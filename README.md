# Site24x7 PostgreSQL Cluster Monitoring Plugin

The Site24x7 PostgreSQL Cluster Monitoring plugin provides end-to-end cluster-level observability across all primary and standby nodes as a cohesive system. It tracks cluster topology, dynamic primary discovery, failover progression, split-brain and no-primary conditions, WAL timeline divergence, streaming replication lag, replication slots, WAL archiving, background writer and checkpoint performance, connection utilization, and recovery conflicts.

---

## Key Capabilities

- **Unified Cluster Topology**: Monitors multiple PostgreSQL endpoints simultaneously under a single Site24x7 monitor instance.
- **Dynamic Primary Discovery & Auto-Failover**: Evaluates all configured nodes in parallel (sub-second timeouts) to identify the active primary and monitor Standbys. In the event of failover, the plugin dynamically follows the newly promoted primary without requiring configuration changes.
- **Critical Cluster Health Flags**:
  - `No Primary Flag`: Triggered when zero reachable nodes are operating as a primary (cluster outage or in-flight election).
  - `Split Brain Flag`: Triggered when multiple nodes report primary status simultaneously.
- **Replication Backlog & Standby Insights**: Detailed tracking of byte and time lag (`replay_lag_bytes`, `write_lag_bytes`, `flush_lag_bytes`), sync states (`sync`, `async`, `quorum`), and individual standby connectivity.
- **Replication Slots Telemetry**: Monitors total, active, and inactive physical and logical slots with retained WAL lag bytes.
- **Child Tables**: Generates dedicated Site24x7 child tables:
  - `Cluster_Nodes`: Real-time reachability, role, timeline, and latency per node.
  - `Replication_Standbys`: Live replication streaming status directly from the primary.
- **6 Organized Dashboard Tabs**: Grouped logically into Cluster, DB and IO stats, BG Writer, Transactions and Sessions, Write Ahead Log, and Recovery Conflicts.

---

## What This Adds Over the Standalone PostgreSQL Plugin

Running a real key diff between the standalone Site24x7 PostgreSQL plugin (`postgres/postgres.py` queried against a single primary endpoint) and this cluster plugin (`postgres_cluster.py`) demonstrates **34 new top-level metric keys**, **2 dedicated child tables**, and **3 new dashboard tabs**.

### 1. New Dashboard Tabs
- **`Cluster`** (`order: 1`): Unified topology view containing `Cluster_Nodes` and `Replication_Standbys` child tables, node reachability, primary flags, WAL timelines, and replication slots.
- **`Write Ahead Log`** (`order: 5`): High-resolution WAL tracking including exact LSN positions (MB), on-disk WAL directory file counts and size, and archiver success/failure rates.
- **`Recovery Conflicts`** (`order: 6`): Standby query cancellation breakdown across locks, snapshots, buffer pins, deadlocks, and tablespaces, along with connection pool headroom.

### 2. New Child Tables
- **`Cluster_Nodes`**: Real-time status for every cluster node (columns: `name`, `role`, `patroni_state`, `up`, `is_primary`, `timeline`, `response_time_ms`, `replay_backlog_bytes`, `replay_delay_s`, `connections`, `status`).
- **`Replication_Standbys`**: Streaming replication connections queried from the primary (columns: `name`, `client_addr`, `state`, `sync_state`, `is_sync`, `replay_lag_bytes`, `write_lag_bytes`, `flush_lag_bytes`).

### 3. New Metrics Diff Table

| Metric Key | Type | What It Tells an Operator | Source Query / Origin |
| :--- | :--- | :--- | :--- |
| `Nodes Total` | `int` | Total count of configured cluster nodes. | Configuration parser (`nodes` list length) |
| `Nodes Up` | `int` | Number of cluster nodes currently responding to probes. | Concurrent probe (`SELECT 1;`) |
| `Primary Count` | `int` | Number of reachable nodes operating in read-write primary mode. | `SELECT pg_is_in_recovery();` (count where false) |
| `No Primary Flag` | `int` (1/0) | Alert flag: 1 if zero primaries are reachable (outage or failover). | Derived (`1 if Primary Count == 0 else 0`) |
| `Split Brain Flag` | `int` (1/0) | Critical alert flag: 1 if multiple nodes report primary status. | Derived (`1 if Primary Count > 1 else 0`) |
| `Primary Timeline` | `int` | Active WAL timeline ID; increments on failover. | `SELECT ('x' \|\| substring(pg_walfile_name(pg_current_wal_lsn()) from 1 for 8))::bit(32)::int;` |
| `Max Replay Backlog` | `int` (bytes) | Worst-case replication replay backlog across standbys. | `SELECT COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn), 0)::bigint FROM pg_stat_replication;` |
| `Replication Slots Total` | `int` | Total replication slots defined on primary. | `SELECT count(*)::int FROM pg_replication_slots;` |
| `Replication Slots Active` | `int` | Count of replication slots actively streaming data. | `SELECT count(*) FILTER (WHERE active = true)::int FROM pg_replication_slots;` |
| `Replication Slots Inactive` | `int` | Count of inactive slots; alerts on risk of unbounded WAL retention. | `SELECT count(*) FILTER (WHERE active = false)::int FROM pg_replication_slots;` |
| `Physical Slots` | `int` | Number of physical streaming replication slots. | `SELECT count(*) FILTER (WHERE slot_type = 'physical')::int FROM pg_replication_slots;` |
| `Logical Slots` | `int` | Number of logical decoding / CDC replication slots. | `SELECT count(*) FILTER (WHERE slot_type = 'logical')::int FROM pg_replication_slots;` |
| `Max Slot Lag Bytes` | `int` (bytes) | Maximum WAL retained by any single consumer slot. | `SELECT COALESCE(max(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)), 0)::bigint FROM pg_replication_slots;` |
| `WAL Write Position` | `float` (MB) | Current byte offset write position on the primary WAL. | `SELECT ROUND(pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0') / 1024.0 / 1024.0, 2);` |
| `WAL Insert Position` | `float` (MB) | WAL write position buffered in memory. | `SELECT ROUND(pg_wal_lsn_diff(pg_current_wal_insert_lsn(), '0/0') / 1024.0 / 1024.0, 2);` |
| `WAL Flush Position` | `float` (MB) | WAL write position durably committed to storage. | `SELECT ROUND(pg_wal_lsn_diff(pg_current_wal_flush_lsn(), '0/0') / 1024.0 / 1024.0, 2);` |
| `WAL Files Count` | `int` | Total count of WAL segments present in the `pg_wal` directory. | `SELECT count(*) FROM pg_ls_waldir();` |
| `WAL Total Size` | `float` (MB) | Total disk consumption of all WAL files on disk. | `SELECT COALESCE(ROUND(SUM(size) / 1024.0 / 1024.0, 2), 0) FROM pg_ls_waldir();` |
| `Archive Status Success` | `int` | Cumulative number of WAL files successfully archived. | `SELECT archived_count FROM pg_stat_archiver;` |
| `Archive Status Failed` | `int` | Cumulative number of failed WAL archival attempts. | `SELECT failed_count FROM pg_stat_archiver;` |
| `Last Archived WAL File` | `str` | Name of the last segment successfully pushed to archive. | `SELECT last_archived_wal FROM pg_stat_archiver;` |
| `Archive Ready Files Count` | `int` | Backlog of WAL files pending archival (`.ready`). | `SELECT count(*) FROM pg_ls_archive_statusdir() WHERE name LIKE '%.ready';` |
| `Conflicts Tablespace` | `int` | Queries cancelled on standbys due to dropped tablespaces. | `SELECT SUM(confl_tablespace) FROM pg_stat_database_conflicts;` |
| `Conflicts Lock` | `int` | Standby queries cancelled due to table lock timeouts against WAL replay. | `SELECT SUM(confl_lock) FROM pg_stat_database_conflicts;` |
| `Conflicts Snapshot` | `int` | Standby queries cancelled due to vacuumed cleanup of dead tuples. | `SELECT SUM(confl_snapshot) FROM pg_stat_database_conflicts;` |
| `Conflicts Buffer Pin` | `int` | Standby queries cancelled due to contention on pinned shared buffers. | `SELECT SUM(confl_bufferpin) FROM pg_stat_database_conflicts;` |
| `Conflicts Deadlock` | `int` | Standby queries cancelled due to deadlocks during replay. | `SELECT SUM(confl_deadlock) FROM pg_stat_database_conflicts;` |
| `Recovery Conflicts Total` | `int` | Sum of all query cancellations occurring on standby nodes. | `SELECT SUM(confl_tablespace + confl_lock + confl_snapshot + confl_bufferpin + confl_deadlock) FROM pg_stat_database_conflicts;` |
| `Oldest Running Transaction Age`| `int` (s) | Duration in seconds of the oldest active transaction. | `SELECT COALESCE(MAX(EXTRACT(EPOCH FROM now() - xact_start))::BIGINT, 0) FROM pg_stat_activity WHERE state <> 'idle';` |
| `Available Connections` | `int` | Free connection slots reserved for regular client applications. | Derived: `max_connections - superuser_reserved_connections - active_connections` |
| `Connection Utilization Percent`| `float` (%) | Percentage of configured max client connection slots in active use. | Derived: `ROUND((active_connections / max_connections) * 100.0, 2)` |
| `Cache Hit Ratio` | `float` (%) | Buffer cache efficiency; percentage of page reads served from RAM. | Derived: `ROUND((blks_hit / (blks_hit + blks_read)) * 100.0, 2)` |
| `Dead Tuples` | `int` (tuples) | Total accumulated dead tuples awaiting autovacuum cleanup; bloat risk. | `SELECT COALESCE(SUM(n_dead_tup), 0)::bigint FROM pg_stat_user_tables;` |
| `Oldest Transaction ID Age` | `int` (xids) | Oldest transaction age; tracks headroom before 2-billion TxID wraparound shutdown. | `SELECT COALESCE(MAX(age(datfrozenxid)), 0)::bigint FROM pg_database WHERE datallowconn;` |
| `Cluster_Nodes` | `list[dict]` | Tabular telemetry across all nodes (reachability, role, timeline, latency). | Multi-node parallel probe |
| `Replication_Standbys` | `list[dict]` | Tabular streaming replication metrics per connected replica. | `SELECT * FROM pg_stat_replication;` on primary |
| `status` | `int` (1/0) | Plugin overall operational health status indicator. | Dynamic health check evaluator |

---

## Installation

> **Repository Access**: The plugin and installers are maintained at:  
> `https://github.com/JoanathanPS/postgres-cluster-plugin` (branch: `upstream-layout`, path: `upstream_layout/postgres_cluster/`)  
> *(Final upstream location to be decided upon official merge).*  
> Because this repository is **private**, raw `wget` or `curl` URL downloads will fail with authentication errors. Users must clone the repository and run the installer directly from their local copy.

### Automated Installation (From Local Repository Clone)

Both the Linux and Windows installers are designed to work directly from the local repository copy without requiring external file downloads:
- They automatically locate `postgres_cluster.py` in the local directory structure.
- They prompt for cluster connection parameters (or accept command-line arguments).
- They generate `postgres_cluster.cfg` with `redirect_output = 1` and section `[postgres_cluster]`.
- They deploy files into the Site24x7 agent plugins directory and run verification probes before finishing.

#### Step 1: Clone the repository
```bash
git clone -b upstream-layout https://github.com/JoanathanPS/postgres-cluster-plugin.git
cd postgres-cluster-plugin/upstream_layout/postgres_cluster
```

#### Step 2: Run the installer

- **Linux**:
  ```bash
  sudo bash installer/Site24x7PostgresClusterPluginInstaller.sh
  ```

- **Windows (PowerShell as Administrator)**:
  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\Site24x7PostgresClusterPluginInstaller.ps1
  ```

---

## Prerequisites

1. **Site24x7 Agent**: Latest version of the Site24x7 Agent installed on the monitoring server ([Linux Agent](https://www.site24x7.com/app/client#/admin/inventory/add-monitor) or [Windows WinAgent](https://www.site24x7.com/app/client#/admin/inventory/add-monitor)).
2. **Python Runtime**: Python 3.6 or higher.
3. **Database Driver**: `psycopg2` or `psycopg2-binary`:
   ```bash
   pip3 install psycopg2-binary
   ```
4. **Monitoring User Privileges**:
   A dedicated monitoring user (e.g. `site24x7`) must be provisioned on all cluster nodes with the standard `pg_monitor` or `pg_read_all_stats` role.
   Use the included script in `prerequisites/`:
   ```bash
   psql -h <primary_host> -p <port> -U postgres -f prerequisites/create_user.sql
   ```
   Or execute:
   ```sql
   CREATE USER site24x7 WITH PASSWORD 'your_password';
   GRANT pg_read_all_stats TO site24x7;
   GRANT pg_read_all_settings TO site24x7;
   ALTER ROLE site24x7 SET default_transaction_read_only = on;
   ```

---

## Manual Plugin Installation

### Step 1: Create the Plugin Folder

#### Linux
```bash
sudo mkdir -p /opt/site24x7/monagent/plugins/postgres_cluster
cd /opt/site24x7/monagent/plugins/postgres_cluster
```

#### Windows
```powershell
New-Item -ItemType Directory -Path "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster" -Force
Set-Location "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster"
```

### Step 2: Copy Plugin Files
Copy `postgres_cluster.py` and `postgres_cluster.cfg` from `upstream_layout/postgres_cluster/` in your local cloned repository into the plugin directory.

*(Note: Because this repository is private, copy the files from your local git clone rather than using raw URLs).*

### Step 3: Configure `postgres_cluster.cfg`
Edit `postgres_cluster.cfg` with your cluster connection endpoints:
```ini
[global_configurations]
use_agent_python = 0
redirect_output = 1

[postgres_cluster]
nodes = "192.168.1.10:5432,192.168.1.11:5432,192.168.1.12:5432"
username = "site24x7"
password = "your_monitoring_password"
db = "postgres"
patroni_port = "8008"
```

> **Note on Windows `redirect_output`**: `redirect_output = 1` is critical on Windows agents. It instructs the Site24x7 Windows Agent to capture plugin JSON through temporary file redirection rather than anonymous pipes, preventing pipe buffer deadlocks when JSON output exceeds 4 KB.
>
> **Platform Testing Note**: This plugin has been thoroughly validated on Windows Server / WinAgent and standalone Python runtimes. The Linux installation scripts follow standard Site24x7 conventions.

### Step 4: Verify Plugin Output
Execute standalone verification to ensure valid RFC 8259 JSON output:
```bash
python3 postgres_cluster.py --nodes "192.168.1.10:5432,192.168.1.11:5432,192.168.1.12:5432" --username "site24x7" --password "your_password"
```

---

## Metrics Reference

### 1. Cluster Health & Topology Metrics

| Metric Name | Description |
| :--- | :--- |
| **Nodes Total** | Total number of PostgreSQL cluster nodes defined in the configuration. |
| **Nodes Up** | Number of configured nodes successfully reached and responding to health probes. |
| **Primary Count** | Number of reachable nodes identified as the primary (`pg_is_in_recovery() = false`). |
| **No Primary Flag** | Binary alert flag (1 if zero primaries are reachable, 0 if healthy). |
| **Split Brain Flag** | Binary alert flag (1 if multiple nodes claim primary status, 0 if healthy). |
| **Primary Timeline** | Current WAL timeline ID reported by the detected active primary node. |
| **Max Replay Backlog** | Maximum replication replay lag across all connected streaming standbys (in bytes). |

### 2. Replication Slots Metrics

| Metric Name | Description |
| :--- | :--- |
| **Replication Slots Total** | Total count of replication slots defined on the primary. |
| **Replication Slots Active** | Number of replication slots with an active streaming consumer. |
| **Replication Slots Inactive**| Number of replication slots with no active consumer (risk of WAL buildup). |
| **Physical Slots** | Count of physical replication slots (used by streaming standby replicas). |
| **Logical Slots** | Count of logical replication slots (used by CDC / logical replication tools). |
| **Max Slot Lag Bytes** | Maximum retained WAL lag (in bytes) held by any replication slot consumer. |

### 3. Write-Ahead Log (WAL) & Archiving Metrics

| Metric Name | Description |
| :--- | :--- |
| **WAL Write Position** | Current byte offset write position on the primary WAL (in MB). |
| **WAL Insert Position**| Byte offset position up to which WAL records have been buffered in memory (in MB). |
| **WAL Flush Position** | Byte offset position up to which WAL records have been durably flushed to disk (in MB). |
| **WAL Files Count** | Count of active 24-hex WAL segment files in `pg_wal` (excluding `.history` files). |
| **WAL Total Size** | Total disk space consumed by active WAL segment files in `pg_wal` (MB). |
| **Archive Status Success** | *(Reported when archive_mode is on/always)* Cumulative count of successfully archived WAL segments. |
| **Archive Status Failed** | *(Reported when archive_mode is on/always)* Cumulative count of failed WAL archiving attempts. |
| **Archive Ready Files Count**| *(Reported when archive_mode is on/always)* Number of WAL segments pending archiving in `archive_status`. |
| **Last Archived WAL File** | *(Reported when archive_mode is on/always)* Filename of the most recently archived WAL segment. |

### 4. Background Writer & Checkpoints Metrics

| Metric Name | Description |
| :--- | :--- |
| **Checkpoints Timed** | Number of scheduled checkpoints triggered by `checkpoint_timeout`. |
| **Checkpoints Req** | Number of unscheduled checkpoints requested by load or `max_wal_size`. |
| **Checkpoint Write Time** | Time spent writing dirty shared buffers to storage during checkpoints (ms). |
| **Checkpoint Sync Time** | Time spent syncing written buffers to disk using `fsync` (ms). |
| **Buffers Checkpoint** | Shared buffers written to storage during checkpoints. |
| **Buffers Clean** | Buffers written to storage by the background writer process. |
| **Maxwritten Clean** | Rounds where background writer stopped because write limits were reached. |
| **Buffers Alloc** | Total shared memory buffer allocations. |

### 5. Connection & Session Pool Metrics

| Metric Name | Description |
| :--- | :--- |
| **Active Connections** | Total active client backend connections (`backend_type = 'client backend'`). |
| **Available Connections** | Free connection slots available for non-superuser connections. |
| **Connection Utilization Percent** | Percentage of configured `max_connections` currently consumed. |
| **Total Sessions** | Cumulative session count opened across the cluster instance. |
| **Total Sessions Abandoned**| Sessions disconnected without clean termination. |
| **Total Sessions Fatal** | Sessions terminated due to fatal internal errors. |
| **Total Sessions Killed** | Sessions explicitly terminated by administrator action. |

### 6. Recovery Conflicts Metrics

| Metric Name | Description |
| :--- | :--- |
| **Recovery Conflicts Total** | Total standby queries cancelled due to recovery conflicts with replayed WAL. |
| **Conflicts Tablespace** | Standby queries cancelled due to dropped tablespaces. |
| **Conflicts Lock** | Standby queries cancelled due to locks required by WAL replay. |
| **Conflicts Snapshot** | Standby queries cancelled due to expired snapshots. |
| **Conflicts Buffer Pin** | Standby queries cancelled due to pinned buffer contention. |
| **Conflicts Deadlock** | Standby queries cancelled due to replay deadlock conditions. |
| **Oldest Running Transaction Age** | Elapsed duration of the oldest active transaction (seconds). |

---

## Child Tables Reference

### Child Table: `Cluster_Nodes`
Maintains real-time inventory and health across every configured node in the cluster:
- **`name`**: Node identifier / alias.
- **`host`**: Hostname or IP address.
- **`port`**: PostgreSQL port.
- **`role`**: Detected role (`primary`, `standby`, or `offline`).
- **`timeline`**: Reported WAL timeline ID.
- **`state`**: Probe reachability state (`up` or `down`).
- **`response_time_ms`**: Health check round-trip probe latency in milliseconds.
- **`patroni_state`**: DCS state from Patroni REST API (e.g. `running`, `demoted`, or `N/A`).

### Child Table: `Replication_Standbys`
Real-time streaming replication telemetry queried from `pg_stat_replication` on the active primary:
- **`name`**: Standby application name or client address.
- **`client_addr`**: IP address of the connected standby.
- **`state`**: Replication streaming state (e.g. `streaming`, `catchup`).
- **`sync_state`**: Synchronous replication status (`sync`, `async`, `potential`, `quorum`).
- **`replay_lag_bytes`**: Replay lag behind primary WAL write position (bytes).
- **`write_lag_bytes`**: Write lag (bytes).
- **`flush_lag_bytes`**: Flush lag (bytes).

---

## Site24x7 Dashboard Tabs

The plugin automatically organizes all metrics into 6 dashboard tabs:

1. **Cluster** (`order: 1`):
   Contains `Cluster_Nodes`, `Replication_Standbys`, `Nodes Total`, `Nodes Up`, `Primary Count`, `No Primary Flag`, `Split Brain Flag`, `Primary Timeline`, `Max Replay Backlog`, `Replication Slots Total`, `Replication Slots Active`, `Replication Slots Inactive`, `Physical Slots`, `Logical Slots`, `Max Slot Lag Bytes`.
2. **DB and IO stats** (`order: 2`):
   Database block reads, hits, cache hit ratio, row-level DML metrics, and the `Stats_per_DB` child table.
3. **BG Writer** (`order: 3`):
   Checkpoint timing, buffer writes, clean operations, and memory allocation.
4. **Transactions and Sessions** (`order: 4`):
   Commits, rollbacks, session lifecycles, and the `Tranasctions_and_Session_per_Database` child table.
5. **Write Ahead Log** (`order: 5`):
   WAL Write/Insert/Flush positions (MB), on-disk WAL segment file count and total size, and archiving telemetry (when archiving is enabled).
6. **Recovery Conflicts** (`order: 6`):
   Standby recovery conflicts breakdown, lock/pin/snapshot conflicts, oldest transaction duration, and connection pool utilization.

---

## v1 vs v2 on the Console

- **Where to find both monitors**: In the Site24x7 web console, navigate to **Plugins** $\rightarrow$ **Plugin Integrations** (or filter by Application).
  - **v1 monitors**: Named per configured node section (e.g. `postgres_cluster_v1-pg_primary`, `postgres_cluster_v1-pg_replica`).
  - **v2 monitor**: Displayed as a unified cluster monitor (e.g. `postgres_cluster_dev` or `postgres_cluster`).
- **Core architectural difference**: **v1** creates one monitor per node, while **v2** creates one monitor for the whole cluster.

*Note: The initial v1 plugin implementation was contributed by the previous intern via site24x7/plugins PR #442; v2 builds upon this work to offer a consolidated, cluster-wide topology under a single monitor pane.*
