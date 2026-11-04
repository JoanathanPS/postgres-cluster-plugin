# Console Structure Diff: OG Standalone vs Dev PostgreSQL Cluster Plugin

This document provides a comparative analysis of the console structures between the official Site24x7 standalone PostgreSQL monitoring plugin (`postgres-Joana-PC.`) and the newly deployed cluster monitoring plugin (`postgres_cluster_final-Joana-PC.`).

---

## 1. Summary Page Comparison

In Site24x7, any top-level numeric metric not declared inside any tab's `tablist` is charted on the default **Summary** dashboard landing page. Top-level strings not tabbed render in textual attribute panels.

| Summary Element | OG Standalone Monitor (`postgres`) | Dev Cluster Monitor (`postgres_cluster_final`) | Parity Status |
| :--- | :--- | :--- | :--- |
| **Active Connections** | Charted on Summary | Charted on Summary | **EXACT MATCH** |
| **Active Queries** | Charted on Summary | Charted on Summary | **EXACT MATCH** |
| **Active Waiting Queries** | Charted on Summary | Charted on Summary | **EXACT MATCH** |
| **Cache Hit Ratio** | Charted on Summary | Charted on Summary | **EXACT MATCH** |
| **Database Count** | Charted on Summary | Charted on Summary | **EXACT MATCH** |
| **Heap Blocks Hit** | Charted on Summary | Charted on Summary | **EXACT MATCH** |
| **Heap Blocks Read** | Charted on Summary | Charted on Summary | **EXACT MATCH** |
| **Index Rows Fetched** | Charted on Summary | Charted on Summary | **EXACT MATCH** |
| **Index Rows Read** | Charted on Summary | Charted on Summary | **EXACT MATCH** |
| **Index Scans** | Charted on Summary | Charted on Summary | **EXACT MATCH** |
| **Locks Count** | Charted on Summary | Charted on Summary | **EXACT MATCH** |
| **Max Connections** | Charted on Summary | Charted on Summary | **EXACT MATCH** |
| **Table Count** | Charted on Summary | Charted on Summary | **EXACT MATCH** |
| **Uptime** | Charted on Summary | Charted on Summary | **EXACT MATCH** |
| **Cluster Health** | *Not applicable (Single node)* | Charted on Summary (Untabbed) | **Cluster Enhancement** |
| **Nodes Up** | *Not applicable (Single node)* | Charted on Summary (Untabbed) | **Cluster Enhancement** |
| **Total Untabbed Charts** | **14 charts** | **16 charts** (14 OG + 2 Cluster) | **FULL PARITY + CLUSTER OVERVIEW** |

---

## 2. Tabs Layout & Architecture

| Tab Order | OG Standalone Plugin | Dev Cluster Plugin (`postgres_cluster_final`) | Contents & Structural Purpose |
| :---: | :--- | :--- | :--- |
| **1** | *(No cluster tab)* | **Cluster** | Topology & Health: Charts `Nodes Total`, `Primary Count`, `Primary Timeline`, `No Primary Flag`, `Split Brain Flag`, `Timeline Mismatch Flag`, `Server PID` (*needs TL approval*). Tables: `Cluster_Info` (1 row metadata) and `Cluster_Nodes` (all cluster nodes). |
| **2** | *(No replication tab)* | **Replication** | Standby Health & WAL Slots: Charts `Standbys Expected`, `Standbys Streaming`, `Standby Disconnect Flag`, `Sync Standby Count`, `Cascading Standby Count`, `Max Replay Backlog`, `Max Replay Delay`, `Replication Slots Total/Active/Inactive`, `Max Slot Lag Bytes`, `Logical Replication In Use`. Tables: `Replication_Standbys` and `Replication_Slots`. |
| **3** | **DB and IO / BG Writer** | **Node Performance** | Primary & Node DML / Checkpoints: Charts `Total Rows Inserted/Updated/Deleted/Fetched/Returned`, `Total Block Reads/Hits`, `Buffers Alloc/Checkpoint/Clean/Backend/Backend Fsync`, `Checkpoint Sync/Write Time`, `Checkpoints Req/Timed`, `Maxwritten Clean`, `Dead Tuples`. Tables: `Node_IO`, `Node_Checkpoints`, `Stats_per_DB`. |
| **4** | **Sessions and Transactions** | **Transactions and Sessions** | Session & Tx States: Charts `Total Commits/Rollbacks/Conflicts`, `Total Sessions (Total/Abandoned/Fatal/Killed)`, `Transactions Idle In Transaction`, `Transactions Open`, `Connection Utilization Percent`, `Oldest Transaction ID Age`, `Oldest Running Transaction Age`. Tables: `Node_Activity`, `Node_Transactions`, `Tranasctions_and_Session_per_Database`. |
| **5** | *(None)* | **WAL and Recovery** | Write-Ahead Log & Archive: Charts `WAL Write/Insert/Flush Position`, `WAL Files Count`, `WAL Total Size`, `Archive Mode`, `Archive Status Success/Failed`, `Archive Ready Files Count`, `Last Archived WAL File`, `Recovery Conflicts Total`, and specific standby conflict counters. 0 tables. |

---

## 3. Child Tables Specification (Exactly 10 Tables)

All child tables strictly obey Site24x7 constraints ($\le 10$ tables, $\le 15$ columns, $\le 25$ rows, $\le 5$ string columns excluding `name`):

| # | Table Name | Tab | Total Columns | String Columns ($\le 5$) | Numeric Columns | Purpose |
| :---: | :--- | :--- | :---: | :---: | :---: | :--- |
| 1 | `Cluster_Info` | `Cluster` | 10 | 5 (`cluster_type`, `type_evidence`, `server_version`, `primary_node`, `health_reason`) | 4 (`nodes_total`, `nodes_up`, `primary_timeline`, `status`) + `name` | Cluster-wide metadata and orchestrator evidence (1 row) |
| 2 | `Cluster_Nodes` | `Cluster` | 11 | 3 (`role`, `upstream`, `patroni_state`) | 7 (`status`, `timeline`, `connections`, `replay_backlog_bytes`, `replay_delay_s`, `response_time_ms`, `is_primary`) + `name` | Per-node overview across all cluster nodes |
| 3 | `Replication_Standbys` | `Replication` | 10 | 4 (`client_addr`, `state`, `sync_state`, `role`) | 5 (`replay_lag_bytes`, `write_lag_bytes`, `flush_lag_bytes`, `replay_lag_s`, `is_sync`) + `name` | Active standbys streaming from primary |
| 4 | `Replication_Slots` | `Replication` | 5 | 2 (`plugin`, `slot_type`) | 2 (`active`, `wal_retained_bytes`) + `name` | Physical & logical replication slots on primary |
| 5 | `Node_IO` | `Node Performance` | 14 | 0 | 13 (`rows_inserted..`, `block_reads..`, `cache_hit_ratio`, `status`) + `name` | Per-node DML throughput and cache hits across all nodes |
| 6 | `Node_Checkpoints` | `Node Performance` | 12 | 0 | 11 (`checkpoints_..`, `checkpoint_write/sync_time`, `buffers_..`, `status`) + `name` | Per-node checkpoints and buffer telemetry across all nodes |
| 7 | `Stats_per_DB` | `Node Performance` | 10 | 0 | 9 (`active_connections`, `size_in_mb`, `rows_..`, `block_..`) + `name` | Database-level throughput discovered on primary |
| 8 | `Node_Activity` | `Transactions and Sessions` | 10 | 0 | 9 (`active_connections`, `max_connections`, `queries`, `transactions`, `locks`, `uptime`, `status`) + `name` | Per-node active queries, transactions, and locks across all nodes |
| 9 | `Node_Transactions` | `Transactions and Sessions` | 8 | 0 | 7 (`commits`, `rollbacks`, `conflicts`, `sessions_..`, `status`) + `name` | Per-node commits, rollbacks, and session states across all nodes |
| 10 | `Tranasctions_and_Session_per_Database` | `Transactions and Sessions` | 10 | 0 | 9 (`commits`, `rollbacks`, `conflicts`, `sessions_..`, `session_times`) + `name` | Database-level session lifecycle discovered on primary |

---

## 4. Key Structural Fixes Implemented

1. **Top-Level Flat Text Cleaned Up**:
   - `Cluster Type`, `Cluster Name`, `Cluster Type Evidence`, `Cluster Health Reason`, and `Server Version` were removed as top-level untabbed strings (which previously cluttered the bottom textual attribute view).
   - They are now cleanly structured inside the `Cluster_Info` table (1 single row).
2. **Alphanumeric Node Names**:
   - Replaced raw host-port sanitized identifiers (e.g., `D1270015441`) with strictly alphanumeric aliases (`pgnode1`, `pgnode2`, `pgnode3`).
3. **Table Limit Compliance**:
   - `Standby_Conflicts` table was retired, keeping total child tables at exactly 10. Standby query conflict metrics are preserved as aggregated sums on the `WAL and Recovery` tab.
4. **Consistent Metric Types Across Failures**:
   - Pre-populated all default metrics in `_collect_internal` ensuring float/int/str types remain 100% stable whether the cluster is healthy, degraded, or dead.
   - `Last Archived WAL File` defaults to `"none"` when empty or unreachable, never numeric `"0"`.
