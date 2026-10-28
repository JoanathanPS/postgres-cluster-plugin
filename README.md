# Site24x7 PostgreSQL Cluster Monitoring Plugin

The Site24x7 PostgreSQL Cluster Monitoring plugin provides comprehensive cluster-level observability across all primary and standby nodes in a PostgreSQL cluster. It tracks cluster topology, dynamic primary discovery, failover progression, split-brain and no-primary conditions, WAL timeline divergence, streaming replication lag, replication slots, WAL archiving, background writer and checkpoint performance, connection utilization, and recovery conflicts — all unified within a single Site24x7 monitor instance.

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
  - `Cluster_Nodes`: Real-time reachability, role, timeline, latency, and Patroni state per node.
  - `Replication_Standbys`: Live replication streaming status directly from the primary.
- **6 Organized Dashboard Tabs**: Grouped logically into `Cluster`, `DB and IO stats`, `BG Writer`, `Transactions and Sessions`, `Write Ahead Log`, and `Recovery Conflicts`.

---

## Prerequisites

1. **Site24x7 Server Agent**:
   - Install the latest [Site24x7 Linux Agent](https://www.site24x7.com/app/client#/admin/inventory/add-monitor) or [Site24x7 Windows Agent (WinAgent)](https://www.site24x7.com/app/client#/admin/inventory/add-monitor).
2. **Python Runtime**:
   - Python 3.6 or higher.
3. **Database Driver**:
   - `psycopg2` or `psycopg2-binary`:
     ```bash
     pip install psycopg2-binary
     ```
4. **Database Monitoring Role & Permissions**:
   Create a dedicated monitoring user on all cluster nodes with the standard PostgreSQL monitoring roles:
   ```sql
   CREATE USER site24x7 WITH PASSWORD 'your_monitoring_password';
   GRANT pg_read_all_stats TO site24x7;
   GRANT pg_read_all_settings TO site24x7;
   ALTER ROLE site24x7 SET default_transaction_read_only = on;
   ```

---

## Plugin Installation

### Step 1: Create the Plugin Folder

#### Linux
```bash
sudo mkdir -p /opt/site24x7/monagent/plugins/postgres_cluster
cd /opt/site24x7/monagent/plugins/postgres_cluster
```

#### Windows
Open PowerShell as Administrator:
```powershell
New-Item -ItemType Directory -Path "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster" -Force
Set-Location "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster"
```

---

### Step 2: Download or Copy Plugin Files

Place the following files into the `postgres_cluster` plugin directory:
- `postgres_cluster.py`
- `postgres_cluster.cfg`

---

### Step 3: Configure `postgres_cluster.cfg`

Edit `postgres_cluster.cfg` with your cluster connection endpoints and credentials:

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

#### Configuration Options Reference

| Parameter | Section | Description | Default / Example |
| :--- | :--- | :--- | :--- |
| `redirect_output` | `[global_configurations]` | Instructs the Site24x7 Windows Agent to capture plugin JSON via temporary files rather than anonymous pipes. **Crucial on Windows** to prevent pipe buffer hangs with large metrics payloads. | `1` |
| `use_agent_python` | `[global_configurations]` | Whether to use Site24x7 bundled Python (`1`) or system Python (`0`). | `0` |
| `nodes` | `[postgres_cluster]` | Comma-separated list of `host:port` pairs for all nodes in the cluster. | `"127.0.0.1:5441,127.0.0.1:5442,127.0.0.1:5443"` |
| `username` | `[postgres_cluster]` | Database user name with `pg_monitor` or `pg_read_all_stats` privileges. | `"site24x7"` |
| `password` | `[postgres_cluster]` | Password for the database monitoring user. | `"your_monitoring_password"` |
| `db` | `[postgres_cluster]` | Maintenance database name to connect to for server stats. | `"postgres"` |
| `patroni_port` | `[postgres_cluster]` | *(Optional)* HTTP port for the Patroni REST API to gather DCS cluster states. | `"8008"` |

---

### Step 4: Verify the Plugin Standalone

Execute the script directly to verify that valid JSON is produced:

```bash
# Using parameters from postgres_cluster.cfg:
python postgres_cluster.py

# Or passing arguments via command line:
python postgres_cluster.py --nodes "192.168.1.10:5432,192.168.1.11:5432,192.168.1.12:5432" --username "site24x7" --password "your_password"
```

The output should be a valid JSON dictionary containing `version`, `cluster_health`, `Cluster_Nodes`, `Replication_Standbys`, and cluster metrics.

The Site24x7 Agent will automatically discover and execute the plugin within 5 minutes. You can view the monitor under:  
**Site24x7 Web Console  Plugins  Plugin Integrations**

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
| **Replication Slots Inactive** | Number of replication slots with no active consumer (risk of WAL buildup). |
| **Physical Slots** | Count of physical replication slots (used by streaming standby replicas). |
| **Logical Slots** | Count of logical replication slots (used by CDC / logical replication tools). |
| **Max Slot Lag Bytes** | Maximum retained WAL lag (in bytes) held by any replication slot consumer. |

### 3. Write-Ahead Log (WAL) & Archiving Metrics

| Metric Name | Description |
| :--- | :--- |
| **Current WAL LSN** | Current Log Sequence Number write position on the primary. |
| **WAL Insert LSN** | LSN position up to which WAL records have been buffered in memory. |
| **WAL Flush LSN** | LSN position up to which WAL records have been durably flushed to disk. |
| **WAL Files Count** | Total count of WAL segment files present in `pg_wal`. |
| **WAL Total Size** | Total disk space consumed by WAL files in `pg_wal` (MB). |
| **Archive Status Success** | Cumulative count of successfully archived WAL segments. |
| **Archive Status Failed** | Cumulative count of failed WAL archiving attempts. |
| **Archive Ready Files Count** | Number of WAL segments pending archiving in `archive_status`. |
| **Last Archived WAL File** | Filename of the most recently archived WAL segment. |

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
| **Total Sessions Abandoned** | Sessions disconnected without clean termination. |
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

The plugin organizes all monitored metrics into 6 dashboard tabs:

1. **Cluster** (`order: 1`):
   Contains `Cluster_Nodes`, `Replication_Standbys`, `Nodes Total`, `Nodes Up`, `Primary Count`, `No Primary Flag`, `Split Brain Flag`, `Primary Timeline`, `Max Replay Backlog`, `Replication Slots Total`, `Replication Slots Active`, `Replication Slots Inactive`, `Physical Slots`, `Logical Slots`, `Max Slot Lag Bytes`.
2. **DB and IO stats** (`order: 2`):
   Database block reads, hits, cache hit ratio, row-level DML metrics, and the `Stats_per_DB` child table.
3. **BG Writer** (`order: 3`):
   Checkpoint timing, buffer writes, clean operations, and memory allocation.
4. **Transactions and Sessions** (`order: 4`):
   Commits, rollbacks, session lifecycles, and the `Transactions_and_Session_per_Database` child table.
5. **Write Ahead Log** (`order: 5`):
   Current LSN markers, WAL directory file count, total WAL disk usage, and archiver success/failure rates.
6. **Recovery Conflicts** (`order: 6`):
   Standby recovery conflicts breakdown, lock/pin/snapshot conflicts, oldest transaction duration, and connection pool utilization.
