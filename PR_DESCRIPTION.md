# PR: Comprehensive PostgreSQL Cluster Monitoring Plugin for Site24x7 (v2 Redesign)

## Summary of Changes

This Pull Request introduces a production-ready, enterprise-grade PostgreSQL Cluster monitoring plugin for Site24x7. It supersedes the partial implementation in PR #442 by adopting a unified cluster-first topology model, delivering sub-second failover visibility, incorporating all review feedback from PR #442, redesigning into a clean 4-tab layout, and eliminating the Windows Agent 160 s registration deadlock.

The single source of truth for upstream repository submission is maintained under:
`upstream_layout/postgres_cluster/`

---

## 1. 4-Tab Dashboard Architecture

The dashboard is structured into exactly 4 specialized tabs, each answering a critical operational question:

1. **`Cluster`**: *What is the cluster topology, manager type, active primary, timeline, and overall cluster health?*
   - Surfaces `Cluster Type` (prominently at the top of the tab and as the primary landing page).
   - Features `Cluster Health` (0: Healthy, 1: Degraded, 2: Critical) and `Cluster Health Reason` (<100 characters).
   - Child Table: `Cluster_Nodes` (Per-node reachability, timeline, latency, connections, lag, upstream, and cluster type).
2. **`Replication`**: *Are standbys replicating properly, are WAL positions progressing, and are replication slots healthy?*
   - Standbys Expected/Streaming, Sync Standby Count, Max Replay Backlog/Delay, Slots Active/Inactive, Max Slot Lag Bytes, Logical Replication In Use.
   - Always-emitted WAL positions and Archiving status (`Archive Mode`, Success, Failed, Ready).
   - Child Tables: `Replication_Standbys`, `Replication_Slots`, `Standby_Conflicts`.
3. **`Node Performance`**: *How are cluster nodes performing in terms of I/O throughput, buffer allocation, cache hits, and checkpoints?*
   - Exact SQL and parameter parity with standalone `postgres.py`: insert/update/delete/fetch/return tuples, block reads/hits, heap reads/hits, cache hit ratio (0.0 to 1.0 ratio), index scans/reads/fetches, and background writer buffers.
   - Child Tables: `Node_IO`, `Node_Checkpoints`, `Stats_per_DB`.
4. **`Transactions and Sessions`**: *What is the concurrency, connection saturation, lock contention, and transaction throughput across nodes and databases?*
   - Active connections, max connections, connection utilization %, active queries, waiting queries, locks, commits, rollbacks, conflicts, open transactions, session lifecycles, and uptime.
   - Child Tables: `Node_Activity`, `Node_Transactions`, `Tranasctions_and_Session_per_Database`.

---

## 2. Hierarchical Cluster Health Evaluation Rules

Evaluated top-down to return the first matching condition:
- **`Critical` (Code 2)**:
  - `No Primary Flag == 1` (0 primary nodes found)
  - `Split Brain Flag == 1` (>1 primary nodes detected)
  - `Standbys Expected > 0` but `Standbys Streaming == 0` (all standbys disconnected)
- **`Degraded` (Code 1)**:
  - Any node down (`Nodes Up < Nodes Total`)
  - Standby disconnected (`Standbys Streaming < Standbys Expected`)
  - Replay delay over threshold (`Max Replay Delay > 30.0s`)
  - Replay backlog over threshold (`Max Replay Backlog > 104,857,600 bytes`)
  - Inactive replication slot (`Replication Slots Inactive > 0`)
  - Timeline mismatch (`Timeline Mismatch Flag == 1`)
- **`Healthy` (Code 0)**:
  - All nodes up, exactly 1 primary, all expected standbys streaming, matching timelines, and acceptable lag.

---

## 3. Strict Parity with Standalone `postgres.py` & PR #442

- **Identical SQL & Aliases**: Every query for IO, BG writer, Heap & Cache, and DB stats uses the exact query structure and aliases from official `postgres.py`.
- **Cache Hit Ratio**: Computed strictly as a 0.0 to 1.0 ratio (`heap_blks_hit / (heap_blks_hit + heap_blks_read)`).
- **Exact Typos Preserved**: The table name `Tranasctions_and_Session_per_Database` is retained exactly as in `postgres.py` for backward compatibility.
- **Site24x7 Schema Limits Observed**:
  - Max 10 child tables (exactly 9 defined).
  - Max 15 columns per child table.
  - Max 25 rows per child table (strict `[:25]` truncation).
  - Max 5 string columns per table.
  - Nested units dictionary for all tabular numeric columns.

---

## 4. Tested Clusters Matrix

| Cluster Manager / Architecture | Verification Status | Verification Methodology & Evidence |
| :--- | :--- | :--- |
| **Patroni HA** | **Tested Live** | Verified against live 3-node containerized cluster with DCS (etcd). Tested automatic failover, REST API probes, timeline increment (24 -> 25), and node recovery. |
| **Streaming Replication (Unmanaged)** | **Tested Live** | Verified against live 2-node PostgreSQL 16 cluster. Validated baseline detection, `pg_promote()` failover, split-brain alert detection (`Split Brain Flag == 1`, Health 2), and teardown. |
| **Standalone PostgreSQL (14 & 16)** | **Tested Live** | Verified against live containerized PostgreSQL 14 and 16 standalone instances. Verified single-node detection, version extraction, and healthy status code 0. |
| **repmgr** | **Fixture Validated** | Verified via test fixture detecting `repmgr` extension and `repmgr.nodes` topology catalog table. |
| **pg_auto_failover** | **Fixture Validated** | Verified via test fixture detecting `pgautofailover` extension and `pgautofailover_standby` replication slot. |
| **CloudNativePG (CNPG)** | **Fixture Validated** | Verified via test fixture detecting Kubernetes CNPG operator replication slot pattern `_cnpg_*`. |
| **Stolon** | **Fixture Validated** | Verified via test fixture detecting Stolon keeper slot pattern `stolon_*` and application name signatures. |
| **Citus Distributed** | **Fixture Validated** | Verified via test fixture detecting `citus` distributed coordinator extension. |
| **AWS Aurora PostgreSQL** | **Fixture Validated** | Verified via test fixture detecting `aurora_version()` engine function. |
| **AWS RDS PostgreSQL** | **Fixture Validated** | Verified via test fixture detecting Amazon RDS administrative role `rds_superuser`. |
| **Azure Database for PostgreSQL** | **Fixture Validated** | Verified via test fixture detecting Azure managed service role `azure_pg_admin`. |
| **GCP Cloud SQL PostgreSQL** | **Fixture Validated** | Verified via test fixture detecting Google Cloud SQL administrative role `cloudsqlsuperuser`. |
| **Mixed / HA Conflict** | **Fixture Validated** | Verified via test fixture detecting contradictory HA orchestrator signatures, safely categorized as `mixed/unknown`. |

---

## 5. Verification Suite Results

- **`check-layout.ps1`**: 15/15 passed.
- **`tester/test_cluster_plugin.py`**: 0 failures, 0 warnings.
- **`tester/test_multi_clusters.py`**: All multi-cluster tests passed (Plain streaming, `pg_promote` split brain, Standalone PG 14, Standalone PG 16).
- **`tester/e2e.ps1 -Mode quick`**: `RESULT: PASS` (all stages including live Playwright console check).
- **`tester/e2e.ps1 -Mode full`**: `RESULT: PASS` (all stages including dynamic failover, lag demo, agent logs, and live Playwright console check).
- **`tester/console_check.py`**: 8 PASS, 0 FAIL against fresh monitor in live Site24x7 web console.
