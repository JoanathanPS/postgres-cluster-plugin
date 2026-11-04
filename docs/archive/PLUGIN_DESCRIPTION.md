# PostgreSQL Cluster Monitoring Plugin for Site24x7: Complete Architecture & Metrics Reference

---

## 1. Executive Summary & Core Objective

In production PostgreSQL deployments using High Availability (HA) frameworks such as **Patroni**, **repmgr**, or native **streaming replication**, a database does not exist as an isolated server; it operates as an active, stateful cluster comprising a **Primary** (Read/Write) and one or more **Standbys/Replicas** (Read-Only).

### The Problem with Previous Implementations
1. **The Standalone Plugin (`site24x7/plugins/postgres`)**:
   - Only connects to a single host/port.
   - If the primary fails over to a replica, the plugin either reports a dead server or reports standby metrics where write queries fail.
   - Zero visibility into cluster topology, replication lag in bytes, WAL timelines, or split-brain conditions.
2. **The Previous Intern's v1 Implementation (`postgres_cluster_v1`)**:
   - Created **one separate monitor per node** (e.g. `postgres_cluster_v1-pg_primary`, `postgres_cluster_v1-pg_replica`), consuming multiple monitor licenses and scattering cluster health across disjointed screens.
   - Suffered from a blocking bug (`print(dict)` instead of `print(json.dumps())`), causing the agent to fail registration.
   - Did not dynamically track failover without manual agent reconfiguration.

### The Solution: Our v2 PostgreSQL Cluster Plugin
- **One Unified Monitor**: The entire cluster is represented under **one single Site24x7 plugin monitor**.
- **Dynamic Primary Discovery & Auto-Failover**: Probes all configured nodes concurrently every 5 minutes. The plugin automatically identifies who is currently the primary and queries deep instance telemetry from that node, while simultaneously monitoring standbys. If a failover occurs, the plugin seamlessly switches its deep queries to the newly promoted primary without requiring any config changes or restarting the agent.
- **Failover & Outage Safety Flags**: Directly alerts if zero nodes are primary (`No Primary Flag = 1`) or if multiple nodes claim primary status (`Split Brain Flag = 1`).
- **Competitor Advantage**: Adds DBA-critical telemetry inspired by Datadog & pganalyze: **Cache Hit Ratio (%)**, **Dead Tuples accumulation**, and **Oldest Transaction ID Age (xid freeze risk)**.

---

## 2. Architectural Comparison

```
+-----------------------------------+-----------------------------------+-----------------------------------+
| Capability                        | Standalone `postgres`             | Previous v1 (`postgres_cluster_v1`)| Our Plugin (`postgres_cluster`)   |
+-----------------------------------+-----------------------------------+-----------------------------------+
| Target Architecture               | Single standalone instance        | Multi-node (separate monitors)    | Unified Cluster Topology          |
| Monitor Footprint in Console      | 1 monitor per endpoint            | N monitors (1 per node)           | 1 Single Unified Monitor          |
| Failover Handling                 | Fails when primary IP changes     | Requires manual config update     | Fully Automatic & Dynamic         |
| Node Probing                      | Serial / synchronous              | Serial (slow if node down)        | Concurrent (Thread Pool, sub-sec) |
| Split-Brain & No-Primary Alerts   | None                              | None                              | Built-in (Flags 1/0)              |
| Replication Lag Measurement       | None                              | Partial time lag                  | Byte lag + Time lag + Slot lag    |
| Patroni REST API Integration      | None                              | None                              | Supported (dual-mode discovery)   |
| Dashboard Tabs                    | 3 tabs                            | 3 tabs (DB and IO, BG, Tx)        | 6 Tabs logically organized        |
| Child Tables                      | 2 (DB stats & Sessions)           | 2 (DB stats & Sessions)           | 4 (Adds Nodes & Standbys tables)  |
| Advanced DBA & Freeze Metrics     | None                              | None                              | Cache Hit %, Dead Tuples, TxID Age|
+-----------------------------------+-----------------------------------+-----------------------------------+
```

---

## 3. The 6 Dashboard Tabs & All Monitored Metrics

The plugin groups metrics into **6 organized dashboard tabs** in the Site24x7 web console:

```
[Tab 1: Cluster]
  ├── Cluster_Nodes (Table)
  ├── Replication_Standbys (Table)
  └── Cluster Health & Slot Metrics
[Tab 2: DB and IO stats]
  ├── Stats_per_DB (Table)
  └── Cache Hit Ratio, Dead Tuples, Block I/O, DML Rows
[Tab 3: BG Writer]
  └── Checkpoint Timing, Buffers Clean, Backend Fsync, Allocations
[Tab 4: Transactions and Sessions]
  ├── Tranasctions_and_Session_per_Database (Table)
  └── Oldest TxID Age, Commits, Rollbacks, Session Lifecycles
[Tab 5: Write Ahead Log]
  └── LSN Positions (MB), WAL File Counts, WAL Disk Size, Archiving
[Tab 6: Recovery Conflicts]
  └── Standby Query Cancellations (Lock/Snapshot/Buffer Pin/Deadlock) & Connection Pool
```

---

### Tab 1: Cluster (`order: 1`)
*Focus: Overall high-availability health, node reachability, role assignment, and replication backlogs.*

| Metric Name | Type / Unit | Description & Operational Value |
| :--- | :--- | :--- |
| **Nodes Total** | `int` (nodes) | Total number of configured cluster nodes. |
| **Nodes Up** | `int` (nodes) | Count of nodes currently answering network and database probes. |
| **Primary Count** | `int` (nodes) | Count of reachable nodes operating in read-write primary mode (`pg_is_in_recovery() = false`). |
| **No Primary Flag** | `int` (flag: 0/1) | **Alert Flag**: Sets to `1` if zero reachable nodes are primary (indicates cluster outage or in-flight election). |
| **Split Brain Flag** | `int` (flag: 0/1) | **Critical Alert Flag**: Sets to `1` if multiple nodes report primary status simultaneously (split-brain). |
| **Primary Timeline** | `int` (timeline) | Active WAL timeline ID. Increments upon every failover or standby promotion (e.g. 17 $\rightarrow$ 18). |
| **Max Replay Backlog** | `int` (bytes) | Worst-case replication replay backlog across all connected standbys. |
| **Replication Slots Total** | `int` (slots) | Total count of replication slots defined on the primary. |
| **Replication Slots Active** | `int` (slots) | Count of replication slots actively streaming data to standbys. |
| **Replication Slots Inactive** | `int` (slots) | Count of inactive/disconnected replication slots (alerts before WAL accumulates unbounded on disk). |
| **Physical Slots** | `int` (slots) | Number of physical streaming replication slots. |
| **Logical Slots** | `int` (slots) | Number of logical decoding slots (used by CDC / external consumers). |
| **Max Slot Lag Bytes** | `int` (bytes) | Maximum WAL retained by any single consumer slot. |

#### Child Table: `Cluster_Nodes`
Maintains real-time inventory and probe latency for every configured node:
- **`name`**: Endpoint identifier (e.g. `127.0.0.1:5441:8001` or `pg-node1`).
- **`role`**: Detected role (`primary`, `standby`, or `offline`).
- **`patroni_state`**: DCS state from Patroni REST API (`running`, `streaming`, `demoted`, or `N/A`).
- **`up`**: Reachability flag (`1` = reachable, `0` = unreachable).
- **`is_primary`**: Read-write flag (`1` = primary, `0` = replica).
- **`timeline`**: Reported WAL timeline ID.
- **`response_time_ms`**: Probe round-trip latency in milliseconds.
- **`replay_backlog_bytes`**: Node-specific replication backlog.
- **`replay_delay_s`**: Node-specific replication time lag in seconds.
- **`connections`**: Active client connections on that specific node.
- **`status`**: Health indicator (`1` = OK, `0` = Dead).

#### Child Table: `Replication_Standbys`
Real-time streaming telemetry queried from `pg_stat_replication` on the active primary:
- **`name`**: Standby application name or client address.
- **`client_addr`**: IP address of the connected standby.
- **`state`**: WAL streaming state (`streaming`, `catchup`, `backup`).
- **`sync_state`**: Synchronous replication state (`sync`, `async`, `potential`, `quorum`).
- **`is_sync`**: Synchronous flag (`1` = sync, `0` = async).
- **`replay_lag_bytes`**: Replay lag behind primary WAL write position.
- **`write_lag_bytes`**: Write lag behind primary WAL write position.
- **`flush_lag_bytes`**: Flush lag behind primary WAL write position.

---

### Tab 2: DB and IO stats (`order: 2`)
*Focus: Buffer pool caching efficiency, disk I/O, DML throughput, and dead tuple accumulation.*

| Metric Name | Type / Unit | Description & Operational Value |
| :--- | :--- | :--- |
| **Cache Hit Ratio** | `float` (%) | **Competitor Advantage Metric**: Percentage of disk reads served from RAM (`shared_buffers`) vs physical disk. Values $<99\%$ suggest buffer pool starvation. |
| **Dead Tuples** | `int` (tuples) | **Competitor Advantage Metric**: Total dead rows awaiting vacuum cleanup across all databases. Identifies table bloat early. |
| **Total Block Reads** | `int` (blocks) | Cumulative blocks read from physical storage into memory. |
| **Total Block Hits** | `int` (blocks) | Cumulative blocks read directly from shared memory buffer cache. |
| **Total Rows Fetched** | `int` (rows) | Cumulative table rows retrieved by client queries. |
| **Total Rows Inserted** | `int` (rows) | Cumulative rows inserted via `INSERT` commands. |
| **Total Rows Updated** | `int` (rows) | Cumulative rows updated via `UPDATE` commands. |
| **Total Rows Deleted** | `int` (rows) | Cumulative rows deleted via `DELETE` commands. |
| **Total Rows Returned** | `int` (rows) | Total rows emitted across all database queries. |

#### Child Table: `Stats_per_DB`
Per-database breakdown of block I/O, storage size in MB, active connections, and row DML activity.

---

### Tab 3: BG Writer (`order: 3`)
*Focus: Background writer, checkpoint scheduling, and dirty buffer flushing efficiency.*

| Metric Name | Type / Unit | Description & Operational Value |
| :--- | :--- | :--- |
| **Checkpoints Timed** | `int` | Scheduled checkpoints triggered by `checkpoint_timeout`. |
| **Checkpoints Req** | `int` | Unscheduled checkpoints triggered by WAL volume exceeding limits. High values suggest `max_wal_size` should be increased. |
| **Checkpoint Write Time** | `int` (ms) | Milliseconds spent writing dirty buffers to disk during checkpoints. |
| **Checkpoint Sync Time** | `int` (ms) | Milliseconds spent synchronizing (fsync) checkpoint files to persistent storage. |
| **Buffers Checkpoint** | `int` (buffers) | Dirty shared buffers flushed during checkpoints. |
| **Buffers Clean** | `int` (buffers) | Dirty buffers flushed proactively by the background writer process. |
| **Maxwritten Clean** | `int` | Count of times the background writer stopped because `bgwriter_lru_maxpages` was reached. |
| **Buffers Backend** | `int` (buffers) | Buffers written directly by backend client connections (indicates backends had to stall to flush dirty memory). |
| **Buffers Backend Fsync** | `int` (calls) | Times backend workers were forced to run their own fsync calls. |
| **Buffers Alloc** | `int` (buffers) | Total buffer allocations in shared memory. |

---

### Tab 4: Transactions and Sessions (`order: 4`)
*Focus: Transaction throughput, transaction ID age, open sessions, and transaction states.*

| Metric Name | Type / Unit | Description & Operational Value |
| :--- | :--- | :--- |
| **Oldest Transaction ID Age** | `int` (xids) | **Competitor Advantage Metric**: Number of transactions since the oldest unvacuumed transaction ID. Critical for preventing catastrophic 2-billion transaction **TxID wraparound outages**. |
| **Total Commits** | `int` (transactions) | Cumulative count of successfully committed transactions. |
| **Total Rollbacks** | `int` (transactions) | Cumulative count of aborted/rolled-back transactions. |
| **Total Conflicts** | `int` (conflicts) | Total transactions cancelled due to recovery conflicts. |
| **Transactions Open** | `int` (transactions) | Number of transactions currently in flight. |
| **Transactions Idle In Transaction** | `int` (transactions) | Connections holding an uncommitted transaction open while idle (blocks autovacuum and table locks). |
| **Total Sessions** | `int` (sessions) | Cumulative client sessions established. |
| **Total Sessions Abandoned** | `int` (sessions) | Sessions terminated because client disconnected unexpectedly. |
| **Total Sessions Fatal** | `int` (sessions) | Sessions terminated due to fatal server-side errors. |
| **Total Sessions Killed** | `int` (sessions) | Sessions explicitly terminated by administrator (`pg_terminate_backend`). |

#### Child Table: `Tranasctions_and_Session_per_Database`
Per-database breakdown of commits, rollbacks, session durations, active execution time, and idle-in-transaction time.

---

### Tab 5: Write Ahead Log (`order: 5`)
*Focus: WAL write offsets, on-disk segment storage, and continuous archiving health.*

| Metric Name | Type / Unit | Description & Operational Value |
| :--- | :--- | :--- |
| **WAL Write Position** | `float` (MB) | Current byte offset write position on the primary WAL. |
| **WAL Insert Position** | `float` (MB) | WAL write position buffered in memory prior to disk write. |
| **WAL Flush Position** | `float` (MB) | WAL position durably committed to physical disk storage. |
| **WAL Files Count** | `int` (files) | Number of 16MB WAL segment files present in `pg_wal`. |
| **WAL Total Size** | `float` (MB) | Total disk consumption of the `pg_wal` directory. |
| **Archive Status Success** | `int` (files) | Cumulative count of WAL segment files successfully archived. |
| **Archive Status Failed** | `int` (files) | Cumulative count of failed WAL archiving attempts. |
| **Archive Ready Files Count**| `int` (files) | WAL segment files queued and waiting to be archived. |

---

### Tab 6: Recovery Conflicts (`order: 6`)
*Focus: Standby query cancellations during continuous replay and connection capacity.*

| Metric Name | Type / Unit | Description & Operational Value |
| :--- | :--- | :--- |
| **Recovery Conflicts Total** | `int` (conflicts) | Total queries on standbys cancelled due to conflict with incoming replayed WAL. |
| **Conflicts Lock** | `int` (conflicts) | Standby queries cancelled because replay required exclusive table locks. |
| **Conflicts Snapshot** | `int` (conflicts) | Standby queries cancelled because replay cleaned rows still visible to active snapshot. |
| **Conflicts Buffer Pin** | `int` (conflicts) | Standby queries cancelled due to long-held shared buffer pins. |
| **Conflicts Deadlock** | `int` (conflicts) | Standby queries cancelled to resolve replay deadlocks. |
| **Conflicts Tablespace** | `int` (conflicts) | Standby queries cancelled because replayed WAL dropped a tablespace. |
| **Oldest Running Transaction Age** | `int` (seconds) | Elapsed execution duration of the oldest running transaction across the cluster. |
| **Available Connections** | `int` (connections) | Remaining free connection slots before reaching `max_connections`. |
| **Connection Utilization Percent** | `float` (%) | Percentage of configured connection pool currently in use. |

---

## 4. Configuration & Deployment

### Configuration File (`postgres_cluster.cfg`)
```ini
[global_configurations]
use_agent_python = 0
redirect_output = 1

[postgres_cluster]
nodes = "127.0.0.1:5441:8001,127.0.0.1:5442:8002,127.0.0.1:5443:8003"
username = "site24x7"
password = "your_monitoring_password"
db = "postgres"
patroni_port = "8008"
```

- **`nodes`**: Comma-separated list of nodes in `host:port` or `host:port:patroni_port` format.
- **`use_agent_python = 0`**: Runs using system Python where `psycopg2-binary` is installed.
- **`redirect_output = 1`**: Instructs the Site24x7 agent service to capture both `stdout` and `stderr` to `PluginLog.log` for instant debugging.

### Verification Command
- **Linux:**
  ```bash
  python3 postgres_cluster.py --nodes "127.0.0.1:5441:8001,127.0.0.1:5442:8002,127.0.0.1:5443:8003" --username site24x7 --password your_password --db postgres
  ```
- **Windows:**
  ```powershell
  py postgres_cluster.py --nodes "127.0.0.1:5441:8001,127.0.0.1:5442:8002,127.0.0.1:5443:8003" --username site24x7 --password your_password --db postgres
  ```

---

## 5. Security & Least Privilege

The plugin operates with a dedicated read-only role and requires **no superuser privileges**:

```sql
CREATE USER site24x7 WITH PASSWORD 'your_password';
GRANT pg_monitor TO site24x7;
ALTER ROLE site24x7 SET default_transaction_read_only = on;
ALTER ROLE site24x7 CONNECTION LIMIT 10;
```
- `pg_monitor` grants read-only access to `pg_stat_replication`, `pg_stat_archiver`, `pg_stat_database`, and WAL directory functions.
- `default_transaction_read_only = on` ensures the monitoring user cannot execute `INSERT`, `UPDATE`, or `DELETE`.
- `CONNECTION LIMIT 10` prevents the monitoring collector from starving application connection pools.
