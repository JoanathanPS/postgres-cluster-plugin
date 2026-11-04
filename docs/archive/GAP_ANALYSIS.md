# Comparative Technical Analysis: Site24x7 PostgreSQL Cluster Monitoring

**Reference:** [PR #442 (site24x7/plugins)](https://github.com/site24x7/plugins/pull/442)  
**Status of PR #442:** Merged into `site24x7/plugins` (October 22, 2026)  
**Scope:** Architecture and Metric Comparison between PR #442 and this Multi-Node Cluster Implementation (`v2`)

---

## 1. Context and Objective

Pull Request #442 added a PostgreSQL cluster monitoring plugin to the official Site24x7 plugins repository. This document provides a factual, side-by-side technical evaluation of the architectural models, query strategies, and telemetry coverage between PR #442 and this plugin implementation.

The goal is to evaluate the design trade-offs of both approaches and document the metric enhancements adopted from PR #442 into this multi-node cluster monitoring solution.

---

## 2. GitHub PR #442 Review Metadata

- **PR Number:** 442 (`site24x7/plugins`)
- **Title:** PostgreSQL Cluster Monitoring Plugin
- **Merge Status:** Merged (October 22, 2026)
- **Review Summary (from `gh pr view 442 --comments`):**
  - Copilot automated code review noted 11 technical considerations:
    1. Synchronous standby classification (`sync` vs `quorum`).
    2. Calculation of WAL receive-to-replay lag.
    3. Backend direct-write metric reporting in `pg_stat_bgwriter`.
    4. Backward compatibility for checkpoint statistics on PostgreSQL versions prior to 17 (`pg_stat_checkpointer` vs `pg_stat_bgwriter`).
    5. Client backend connection filtering in `pg_stat_activity`.
    6. Aggregation of recovery conflicts across databases.
    7. Derivation of node roles and primary status from recovery state.
    8. Command-line output serialization formatting (valid RFC 8259 JSON vs Python dictionary literal).
    9. Placement of `import psycopg2` within exception-handling blocks.
    10. Distinction between standby source client ports and server listening ports.
    11. Enforcement of the 25-row tabular limit for Site24x7 child tables.
  - Maintainer review notes indicated feedback was reviewed and partially incorporated prior to merge.

---

## 3. Architectural Design Differences

| Design Dimension | PR #442 Implementation | This Plugin Implementation (`v2`) | Technical Rationale & Impact |
| :--- | :--- | :--- | :--- |
| **Configuration Model** | Separate sections per endpoint (`[pg_primary]` and `[pg_replica]`) with single `host` and `port` | Unified cluster configuration with a single `nodes` parameter (`host1:port1,host2:port2,...`) | PR #442 monitors individual instances independently. This plugin monitors the cluster topology as a cohesive unit under one Site24x7 monitor. |
| **Primary Discovery** | Static configuration or single-node check (`pg_is_in_recovery()`) | Dynamic parallel discovery across all configured nodes | Enables automatic failover tracking: if the primary changes, the plugin follows the new primary without configuration updates. |
| **Cluster Health Flags** | Not applicable (evaluates one endpoint per section) | Includes `Nodes Total`, `Nodes Up`, `Primary Count`, `No Primary Flag`, and `Split Brain Flag` | Provides automated alerts if multiple nodes claim to be primary (split-brain) or if zero primaries are reachable during a failover window. |
| **Concurrency & Probing** | Sequential connection to the specified endpoint | Concurrent thread pool (`ThreadPoolExecutor`) with a 2-second timeout per node | Ensures probing across all cluster nodes completes within 1 to 4 seconds, even when a node is unreachable. |
| **PostgreSQL Version Support** | Queries `pg_stat_checkpointer` directly | Dynamic version detection: queries `pg_stat_checkpointer` on PG 17+ and `pg_stat_bgwriter` on PG <17 | PostgreSQL 17 moved checkpoint metrics from `pg_stat_bgwriter` into `pg_stat_checkpointer`. Dynamic queries ensure compatibility across versions 9.2 through 17+. |
| **Windows Agent Output Handling** | Standard output pipes without redirection configuration | Configures `redirect_output = 1` under `[global_configurations]` | On Windows, anonymous pipes have a 4 KB buffer. When plugin JSON exceeds 4 KB, standard pipe blocking causes a 160 s timeout. File redirection bypasses pipe limits. |
| **Standalone CLI Output** | Uses `print(results)` (emits Python string literal representation with single quotes) | Uses `print(json.dumps(result))` (emits standard RFC 8259 JSON) | Serialized JSON ensures test runners, automated linters, and external scripts can parse output without syntax errors. |
| **Patroni REST Integration** | Not implemented | Supported via `patroni_port` mapping per node | Allows inspection of Patroni DCS state (e.g. `running`, `demoted`) alongside SQL health. |

---

## 4. Borrowed Metrics and Attribution

The following metric categories from PR #442 were evaluated as valuable additions to cluster observability and have been incorporated into this plugin:

1. **Replication Slots Segregation**:
   - `Physical Slots`: Count of active/inactive physical replication slots (`slot_type = 'physical'`).
   - `Logical Slots`: Count of logical replication slots (`slot_type = 'logical'`).
   - *Attribution:* Borrowed from PR #442's `_collect_replication_slots` query structure, integrated alongside our existing `Max Slot Lag Bytes` metric.

2. **Write-Ahead Log (WAL) and Archiving Telemetry**:
   - `Current WAL LSN`, `WAL Insert LSN`, and `WAL Flush LSN` in MB.
   - `WAL Files Count` and `WAL Total Size` (via `pg_ls_waldir()`).
   - `Archive Status Success`, `Archive Status Failed`, `Last Archived WAL File`, and `Archive Ready Files Count` (via `pg_stat_archiver` and `pg_ls_archive_statusdir()`).
   - *Attribution:* Adopted from PR #442's `_collect_wal_metrics`, wrapped with safe permission fallbacks in case the monitoring user lacks `pg_read_server_files`.

3. **Standby Recovery Conflicts Telemetry**:
   - `Recovery Conflicts Total`, `Conflicts Tablespace`, `Conflicts Lock`, `Conflicts Snapshot`, `Conflicts Buffer Pin`, and `Conflicts Deadlock` from `pg_stat_database_conflicts`.
   - `Oldest Running Transaction Age` from `pg_stat_activity`.
   - *Attribution:* Adopted from PR #442's `_collect_recovery_conflicts`.

4. **Connection Pool Utilization**:
   - `Available Connections` and `Connection Utilization Percent` derived from `pg_settings` (`max_connections`, `superuser_reserved_connections`) and `pg_stat_activity`.
   - *Attribution:* Adopted from PR #442's connection calculation.

---

## 5. Tab and Schema Structure in v2

With the incorporation of these metrics, the plugin organizes telemetry into 6 distinct Site24x7 dashboard tabs:

1. **Tab 1: Cluster (Order 1)**: Topology health, node availability, primary count, timeline, replay backlog, and replication slots. Includes child tables `Cluster_Nodes` and `Replication_Standbys`.
2. **Tab 2: DB and IO stats (Order 2)**: Database-level row activity, block reads, block hits, and child table `Stats_per_DB`.
3. **Tab 3: BG Writer (Order 3)**: Checkpoint frequency, sync/write duration, buffer allocation, and clean operations.
4. **Tab 4: Transactions and Sessions (Order 4)**: Commits, rollbacks, session lifecycle, and child table `Tranasctions_and_Session_per_Database`.
5. **Tab 5: Write Ahead Log (Order 5)**: WAL LSN positions, file count, total size, and WAL archiver performance.
6. **Tab 6: Recovery Conflicts (Order 6)**: Replication conflict breakdown by category, transaction age, and connection pool utilization.
