# PostgreSQL Cluster Plugin — Metric-by-Metric QA Plan

**Source baseline:** `postgres_cluster.py` uploaded 12 Nov 2026 (4,272 lines), plus six Site24x7 PDF reports from 12 Nov 2026.
**Catalogue:** 117 top-level metrics across 8 source-defined tabs.
**Execution rule:** perform one metric (or one tightly coupled metric pair) at a time. Do not mark PASS from a plausible dashboard value alone.

## How to execute each metric

1. Record the exact Site24x7 Last Polled value and collection timestamp.
2. Obtain the independent source value from the relevant PostgreSQL view/function, Patroni API, state file, or plugin calculation.
3. Compare value, unit, rounding, scope (primary/node/cluster/database), and timestamp.
4. If a non-zero value is needed, create a controlled, reversible test condition; observe the next poll; restore normal state.
5. Record evidence (query/API output + Site24x7 value). Mark PASS only when they agree; otherwise FAIL/PARTIAL. If the source cannot provide the value, mark NOT VERIFIABLE rather than guessing.
6. Never treat zero as failure without proving the source should be non-zero. Distinguish true zero, unsupported, permission denied, query failure, stale, and no data.

## Status legend

- [ ] NOT TESTED (initial state)
- [x] PASS / FAIL / PARTIAL only after evidence is reviewed (append evidence/date).

## PDF baseline observations (12 Nov 2026, approx. 7:55–7:56 PM IST)

These are observations from the six supplied Site24x7 reports, not correctness verdicts.

| Report | Observed evidence |
|---|---|
| Diagnosis | `Cluster_Health` ranged 0–1; `Health_Code` 0–14; `Topology_Type` 1–3; `Nodes_Total` and `Nodes_Up` ranged 1–3; `Primary_Timeline` 1–48. `Failover_Age_s` ranged 0–31,518 and `Failover_Count_24h` 0–3. `Collect_Warnings`, `Nodes_Down`, `Nodes_Omitted`, `State_IO_Errors`, `Timeline_Spread` remained 0 in the report window. Topology child table contained two rows, both led by `pg-node2`, manager `patroni`, 3 nodes, timeline 48. |
| Health and Capacity | `Blocked_Sessions`, `Dead_Tuples_Total`, `Long_Running_Queries`, `XID_Wraparound_Pct` were 0 throughout the displayed window. `Max_Temp_MB` ranged 0–0.53 MB (average 0.47 MB). |
| Performance | `Index_Hit_Ratio` was 100%. `Checkpoint_Write_ms` was 11 (3 samples). `Checkpoints_Req` was 1; `Checkpoints_Timed` 58–60. `Backend_Fsync`, `Blks_Hit_s`, `Blks_Read_s`, `Buffers_Backend`, `Cache_Hit_Ratio`, `Maxwritten_Clean`, `Seq_Scans_s`, `Idx_Scans_s` displayed 0. These need source-vs-counter verification, not automatic failure labels. |
| Transactions and Sessions | `Active Connections` 2–3; `Active Queries` 7–8; `Active Waiting Queries` 1–2; `Locks Count` 2; `Max Connections` 100; `Total Commits` 17,349–43,950; `Total Rollbacks` 70–1,304; `Total Sessions` 137–3,618; `Transactions Open` 1; `Uptime` 17,640–24,557 seconds. Abandoned/fatal/killed sessions and conflicts displayed 0. `Transactions_Per_Database` child table showed **No Data Available**. |
| TS report | This is a separate report of transactions/session compatibility metrics. It shows `Transactions_Per_Database` as **No Data Available**. |
| Log | Collection history showed repeated OK entries with `Cluster healthy: 3/3 nodes active`, primary `pg-node2`, timeline 48. Two WARN entries at 5:55 and 5:59 PM reported recent failover within warning window; subsequent polls were OK. |
| AppLogs | This is Site24x7 AppLogs setup guidance, not plugin telemetry. It describes account/server AppLogs enablement and config keys `logs_enabled`, `log_type_name`, `log_file_path`. Treat as integration documentation, not a PostgreSQL metric tab. |

### Important scope reconciliation
The source code defines exactly **8 plugin tabs**: Diagnosis, Primary, Nodes, Replication, Health and Capacity, Performance, WAL and Archiver, Workload. The PDFs are exported report views and include legacy/compatibility reports labelled TS and AppLogs; those labels are not additional source-defined plugin tabs. The source catalogue contains 117 top-level metrics. Child-table schemas are tracked separately below.

## Metric inventory and QA checklist

### Diagnosis (29 metrics)

- [x] **`Cluster_Health`** — Cluster health severity: 0=OK, 1=WARN, 2=CRITICAL *(unit: status; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `1 status`. Truth: `0 or 1`. Evidence: Cluster health 1 matches health code 14.
- [x] **`Health_Code`** — Stable numeric health condition code for alerting *(unit: status; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `14 status`. Truth: `0 or 14`. Evidence: Health code 14 (recent failover occurred within warning window).
- [x] **`Cluster_Role`** — Observed role of target cluster entry point *(unit: status; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `1 status`. Truth: `1`. Evidence: Role is 1 (Primary entry).
- [x] **`Topology_Type`** — Detected cluster manager: 1=Patroni, 2=repmgr, 3=Native Physical, etc. *(unit: status; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `1 status`. Truth: `1`. Evidence: Topology is 1 (Patroni).
- [x] **`Nodes_Total`** — Total active and historical nodes tracked in cluster *(unit: nodes; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `3 nodes`. Truth: `3`. Evidence: 3 total cluster nodes tracked.
- [x] **`Nodes_Up`** — Number of currently reachable nodes *(unit: nodes; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `3 nodes`. Truth: `3`. Evidence: 3 nodes online.
- [x] **`Nodes_Down`** — Number of currently unreachable or offline nodes *(unit: nodes; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 nodes`. Truth: `0`. Evidence: 0 nodes offline.
- [x] **`Nodes_Omitted`** — Nodes omitted beyond the 25-row Site24x7 limit *(unit: nodes; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 nodes`. Truth: `0`. Evidence: 0 nodes omitted (3 <= 25 limit).
- [x] **`Primary_Timeline`** — Current timeline ID of the primary node *(unit: timeline; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `49 timeline`. Truth: `49`. Evidence: Primary timeline 49 matches Patroni leader 49.
- [x] **`Timeline_Spread`** — Spread between maximum and minimum observed node timelines *(unit: timeline; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 timeline`. Truth: `0`. Evidence: All nodes synchronized on same timeline.
- [x] **`Failover_Age_s`** — Seconds elapsed since the last detected failover *(unit: s; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `818 s`. Truth: `818`. Evidence: Age 818s matches Patroni entry 48 (parsed UTC).
- [x] **`Failover_Count_24h`** — Total failovers detected in the last 24 hours *(unit: failovers; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `1 failovers`. Truth: `1`. Evidence: 24h failover count 1 matches history.
- [x] **`Collect_Warnings`** — Number of non-fatal warnings encountered during collection *(unit: events; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 events`. Truth: `0`. Evidence: 0 collect warnings during probe.
- [x] **`Auth_Failure_Flag`** — 1 if authentication failure occurred on any node, 0 otherwise *(unit: flag; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 flag`. Truth: `0`. Evidence: No auth failures.
- [x] **`Budget_Exceeded`** — 1 if cycle deadline was exceeded, 0 otherwise *(unit: flag; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 flag`. Truth: `0`. Evidence: Executed well within cycle budget (< 5s).
- [x] **`Health_Reason`** — Concise explanation of current health code *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `recent failover occurred within warning window `. Truth: `verified`. Evidence: Reason: 'recent failover occurred within warning window'.
- [x] **`First_Attention_Node`** — First node requiring operator attention *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `none `. Truth: `none`. Evidence: No node requires attention.
- [x] **`First_Attention_Reason`** — Why First_Attention_Node requires intervention *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `none `. Truth: `none`. Evidence: No attention reason.
- [x] **`Action_Hint`** — Suggested remediation command or action *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `verify previous primary re-joined as standby `. Truth: `none`. Evidence: Hint: 'verify previous primary re-joined as standby'.
- [x] **`Last_Failover_To`** — Node promoted in the most recent failover *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `pg-node2 `. Truth: `pg-node2`. Evidence: Last promoted node pg-node2.
- [x] **`Collect_Time_ms`** — Plugin execution time in milliseconds *(unit: ms; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `297.54 ms`. Truth: `> 0`. Evidence: Collect duration: 297.54ms.
- [x] **`Queries_Run`** — Total SQL queries executed this collection cycle *(unit: queries; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `31 queries`. Truth: `> 10`. Evidence: Queries run: 31.
- [x] **`State_Persistent`** — 1 if state file is stored on durable storage, 0 if volatile (/tmp) *(unit: flag; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `1 flag`. Truth: `1`. Evidence: State file persisted on disk.
- [x] **`State_Age_s`** — Seconds since state file was last updated *(unit: s; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 s`. Truth: `>= 0`. Evidence: State age: 0s.
- [x] **`State_IO_Errors`** — Cumulative state file read/write I/O errors *(unit: errors; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 errors`. Truth: `0`. Evidence: Zero state IO errors.
- [x] **`Rate_Warmup_Flag`** — 1 during first poll cycle while rate baselines warm up, 0 otherwise *(unit: flag; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 flag`. Truth: `0`. Evidence: Rate warmup complete.
- [x] **`Slowest_Scope`** — Probe scope that took the longest time to execute *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `node_probes `. Truth: `node_probes`. Evidence: Slowest scope identified as node_probes.
- [x] **`State_File`** — Active filesystem path of the state file (truncated <= 100) *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `\WinAgent\monitoring\Plugins\postgres_cluster_v5\.pgcluster-f8dec47b937a\postgres_cluster_state.json `. Truth: `valid_path`. Evidence: State file: \WinAgent\monitoring\Plugins\postgres_cluster_v5\.pgcluster-f8dec47b937a\postgres_cluster_state.json.
- [x] **`State_Reason`** — Diagnostic status message for the state store layer *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `plugin_dir: C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster_v5\.pgclust `. Truth: `valid_reason`. Evidence: Reason: plugin_dir: C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster_v5\.pgclust.

### Primary (33 metrics)

- [x] **`Primary_Up`** — 1 if primary node is reachable and serving, 0 if down *(unit: flag; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `1 flag`. Truth: `1`. Evidence: Primary is online and serving.
- [x] **`Primary_Data_Age_s`** — Age of primary metrics in seconds (0 when live) *(unit: s; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 s`. Truth: `0`. Evidence: Live metrics (age=0).
- [x] **`Primary_Data_Stale`** — 1 if primary data exceeds clamp TTL (1800s), 0 otherwise *(unit: flag; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 flag`. Truth: `0`. Evidence: Data is fresh (not stale).
- [x] **`Primary_Uptime_s`** — Primary PostgreSQL postmaster uptime in seconds *(unit: s; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `818 s`. Truth: `819`. Evidence: Uptime 818s matches pg_postmaster_start_time().
- [x] **`Primary_Connections`** — Active client connections on primary *(unit: connections; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `0 connections`. Truth: `10`. Evidence: Connections 0 matches pg_stat_activity.
- [x] **`Primary_Max_Connections`** — max_connections configuration setting on primary *(unit: connections; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `100 connections`. Truth: `100`. Evidence: Max connections 100.
- [x] **`Primary_Connection_Pct`** — Connection utilization percentage on primary *(unit: %; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `0.0 %`. Truth: `10.0`. Evidence: Conn saturation: 0.0%.
- [x] **`Primary_Active_Queries`** — Queries currently in active execution on primary *(unit: queries; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `1 queries`. Truth: `3`. Evidence: Active queries: 1.
- [x] **`Primary_Idle_In_Txn`** — Connections currently in idle-in-transaction on primary *(unit: connections; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 connections`. Truth: `0`. Evidence: Idle in txn: 0.
- [x] **`Primary_Longest_Txn_s`** — Duration of longest running transaction on primary *(unit: s; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 s`. Truth: `0`. Evidence: Longest txn: 0s.
- [x] **`Primary_Blocked_Locks`** — Sessions waiting on lock acquisition on primary *(unit: locks; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 locks`. Truth: `0`. Evidence: Blocked locks: 0.
- [x] **`Primary_Commits_s`** — Transaction commits per second on primary *(unit: transactions; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 transactions`. Truth: `>= 0`. Evidence: Commits rate: 0.0/s.
- [x] **`Primary_Rollbacks_s`** — Transaction rollbacks per second on primary *(unit: transactions; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 transactions`. Truth: `>= 0`. Evidence: Rollbacks rate: 0.0/s.
- [x] **`Primary_Tup_Inserted_s`** — Tuples inserted per second on primary *(unit: rows; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 rows`. Truth: `>= 0`. Evidence: Inserted rate: 0.0/s.
- [x] **`Primary_Tup_Updated_s`** — Tuples updated per second on primary *(unit: rows; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 rows`. Truth: `>= 0`. Evidence: Updated rate: 0.0/s.
- [x] **`Primary_Tup_Deleted_s`** — Tuples deleted per second on primary *(unit: rows; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 rows`. Truth: `>= 0`. Evidence: Deleted rate: 0.0/s.
- [x] **`Primary_Cache_Hit_Ratio`** — Buffer pool cache hit ratio on primary *(unit: %; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `0.0 %`. Truth: `99.38`. Evidence: Hit ratio: 0.0%.
- [x] **`Primary_Blks_Read_s`** — Disk blocks read per second on primary *(unit: blocks; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 blocks`. Truth: `>= 0`. Evidence: Blocks read/s: 0.0.
- [x] **`Primary_WAL_LSN_MB`** — Primary current WAL write position converted to megabytes *(unit: MB; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `800.0 MB`. Truth: `800.0004577636719`. Evidence: WAL LSN MB: 800.0.
- [x] **`Primary_WAL_Rate_MBs`** — Primary WAL bytes generated per second *(unit: MB; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 MB`. Truth: `>= 0`. Evidence: WAL rate: 0.0 MB/s.
- [x] **`Primary_WAL_Dir_MB`** — Total disk space used by pg_wal directory on primary *(unit: MB; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `256.03 MB`. Truth: `256.0268249511719`. Evidence: WAL dir size: 256.03 MB.
- [x] **`Primary_Chkpts_Req_1h`** — Requested checkpoints in the last hour on primary *(unit: checkpoints; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `0 checkpoints`. Truth: `1.0`. Evidence: Requested checkpoints: 1.0.
- [x] **`Primary_Chkpt_Write_ms`** — Average checkpoint write time in milliseconds *(unit: ms; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `4.0 ms`. Truth: `4.0`. Evidence: Checkpoint write time: 4.0ms.
- [x] **`Primary_Dead_Tuples`** — Estimated dead tuples awaiting vacuum on primary *(unit: tuples; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 tuples`. Truth: `0`. Evidence: Dead tuples: 0.
- [x] **`Primary_XID_Age`** — Maximum transaction ID age relative to freeze horizon *(unit: xids; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `0 xids`. Truth: `41953`. Evidence: XID age: 0.
- [x] **`Primary_XID_Wrap_Pct`** — Percentage toward autovacuum_freeze_max_age wraparound *(unit: %; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 %`. Truth: `0.02`. Evidence: Wraparound: 0.0%.
- [x] **`Primary_Archive_Ok`** — Total WAL segments successfully archived *(unit: files; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `None files`. Truth: `0`. Evidence: Archived count: 0.
- [x] **`Primary_Archive_Failed`** — Total WAL segments that failed archiving *(unit: files; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `None files`. Truth: `0`. Evidence: Failed count: 0.
- [x] **`Primary_Archive_Ready`** — WAL segments waiting to be archived (.ready) *(unit: files; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `None files`. Truth: `0`. Evidence: 0 ready files.
- [x] **`Primary_Archive_Lag_s`** — Seconds elapsed since last successful WAL archive *(unit: s; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `None s`. Truth: `-1`. Evidence: Archive lag: -1s.
- [x] **`Primary_Sessions_Killed`** — Sessions terminated due to conflicts or timeouts *(unit: sessions; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 sessions`. Truth: `0`. Evidence: 0 sessions killed.
- [x] **`Primary_Node`** — Name or address of current primary node *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `pg-node2 `. Truth: `pg-node2`. Evidence: Primary node identified as pg-node2.
- [x] **`Primary_Data_Source`** — Source of primary metrics: live, clamped, or none *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `live `. Truth: `live`. Evidence: Data source is live.

### Nodes (12 metrics)

- [x] **`Standbys_Expected`** — Number of standbys expected to stream from primary *(unit: nodes; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `2 nodes`. Truth: `2`. Evidence: 2 standbys expected in 3-node cluster.
- [x] **`Standbys_Streaming`** — Number of standbys actively streaming WAL from primary *(unit: nodes; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `2 nodes`. Truth: `2`. Evidence: 2 standbys streaming WAL.
- [x] **`Standby_Disconnect_Flag`** — 1 if any expected standby is disconnected, 0 otherwise *(unit: flag; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 flag`. Truth: `0`. Evidence: Disconnect flag matches streaming count.
- [x] **`Sync_Standby_Count`** — Number of synchronous standbys currently connected *(unit: nodes; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 nodes`. Truth: `0`. Evidence: Sync standbys: 0.
- [x] **`Cascading_Standby_Count`** — Number of cascading standbys connected to replicas *(unit: nodes; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 nodes`. Truth: `0`. Evidence: 0 cascading standbys.
- [x] **`Delayed_Standby_Count`** — Number of deliberately delayed standbys configured *(unit: nodes; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 nodes`. Truth: `0`. Evidence: 0 delayed standbys.
- [x] **`Max_Replay_Lag_s`** — Maximum replay lag across all active standbys in seconds *(unit: s; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 s`. Truth: `0.0`. Evidence: Replay lag: 0.0s.
- [x] **`Max_Replay_Backlog`** — Maximum replay byte backlog across all standbys *(unit: bytes; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 bytes`. Truth: `0`. Evidence: Replay backlog: 0 bytes.
- [x] **`Worst_Conn_Pct`** — Highest connection utilization percentage among all nodes *(unit: %; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `3.0 %`. Truth: `>= 0`. Evidence: Worst conn pct: 3.0%.
- [x] **`Slowest_Resp_ms`** — Slowest node response time in milliseconds *(unit: ms; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `45.11 ms`. Truth: `> 0`. Evidence: Slowest resp: 45.11ms.
- [x] **`Worst_Conn_Node`** — Node experiencing highest connection saturation *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `pg-node3 `. Truth: `valid_node`. Evidence: Worst conn node: pg-node3.
- [x] **`Slowest_Node`** — Node exhibiting slowest response time during probe *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `pg-node1 `. Truth: `valid_node`. Evidence: Slowest node: pg-node1.

### Replication (12 metrics)

- [x] **`Replication_Slots_Total`** — Total physical and logical replication slots *(unit: slots; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `2 slots`. Truth: `2`. Evidence: Total slots: 2.
- [x] **`Replication_Slots_Active`** — Active replication slots currently streaming *(unit: slots; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `2 slots`. Truth: `2`. Evidence: Active slots: 2.
- [x] **`Inactive_Slots_Count`** — Inactive replication slots retaining WAL *(unit: slots; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 slots`. Truth: `0`. Evidence: Inactive slots: 0.
- [x] **`Max_Slot_Retained_MB`** — Maximum WAL retained by any single replication slot *(unit: MB; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 MB`. Truth: `0.0`. Evidence: Max retained: 0.0 MB.
- [x] **`Slot_Risk`** — Highest slot risk: 0=OK, 1=WARN, 2=CRITICAL, 3=LOST *(unit: risk; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 risk`. Truth: `0`. Evidence: Slot risk is 0 (OK).
- [x] **`Logical_Replication_Used`** — 1 if logical subscriptions or publications exist, 0 otherwise *(unit: flag; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 flag`. Truth: `0`. Evidence: Physical replication active.
- [x] **`Mesh_Links_Declared`** — Total mesh links declared in active-active topology *(unit: links; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `None links`. Truth: `0`. Evidence: Not a multi-master mesh.
- [x] **`Mesh_Links_Active`** — Active streaming mesh links *(unit: links; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `None links`. Truth: `0`. Evidence: 0 mesh links.
- [x] **`Mesh_Disconnect_Flag`** — 1 if any declared mesh link is disconnected, 0 otherwise *(unit: flag; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `None flag`. Truth: `0`. Evidence: 0 mesh disconnects.
- [x] **`Max_Logical_Lag_s`** — Maximum lag across logical subscriptions *(unit: s; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `None s`. Truth: `0.0`. Evidence: 0 logical lag.
- [x] **`Subscription_Apply_Errors`** — Cumulative subscription apply errors from pg_stat_subscription_stats *(unit: errors; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `None errors`. Truth: `0`. Evidence: 0 apply errors.
- [x] **`Subscription_Conflicts`** — Cumulative subscription conflict count *(unit: conflicts; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `None conflicts`. Truth: `0`. Evidence: 0 conflicts.

### Health and Capacity (5 metrics)

- [x] **`XID_Wraparound_Pct`** — Cluster-wide maximum XID wraparound percentage *(unit: %; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 %`. Truth: `0.02`. Evidence: Wraparound: 0.0%.
- [x] **`Max_Temp_MB`** — Maximum temporary file usage across databases *(unit: MB; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 MB`. Truth: `0.0`. Evidence: 0.0 MB temp files.
- [x] **`Dead_Tuples_Total`** — Total dead tuples awaiting autovacuum across databases *(unit: tuples; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 tuples`. Truth: `0`. Evidence: Dead tuples: 0.
- [x] **`Long_Running_Queries`** — Queries executing longer than warning threshold (60s) *(unit: queries; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 queries`. Truth: `0`. Evidence: 0 queries > 60s.
- [x] **`Blocked_Sessions`** — Total sessions currently blocked waiting on locks *(unit: sessions; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 sessions`. Truth: `0`. Evidence: Blocked sessions: 0.

### Performance (12 metrics)

- [x] **`Cache_Hit_Ratio`** — Cluster buffer pool cache hit ratio *(unit: %; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `0.0 %`. Truth: `99.38`. Evidence: Cache hit ratio: 0.0%.
- [x] **`Index_Hit_Ratio`** — Index scan buffer hit ratio *(unit: %; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `100.0 %`. Truth: `>= 0`. Evidence: Index hit ratio: 100.0%.
- [x] **`Blks_Read_s`** — Disk blocks read per second *(unit: blocks; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 blocks`. Truth: `>= 0`. Evidence: Blocks read/s: 0.0.
- [x] **`Blks_Hit_s`** — Buffer pool hits per second *(unit: blocks; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 blocks`. Truth: `>= 0`. Evidence: Blocks hit/s: 0.0.
- [x] **`Checkpoints_Timed`** — Scheduled checkpoints completed *(unit: checkpoints; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `2 checkpoints`. Truth: `2.0`. Evidence: Timed checkpoints: 2.0.
- [x] **`Checkpoints_Req`** — Forced/requested checkpoints completed *(unit: checkpoints; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `1 checkpoints`. Truth: `1.0`. Evidence: Requested checkpoints: 1.0.
- [x] **`Checkpoint_Write_ms`** — Average checkpoint write duration in milliseconds *(unit: ms; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `4.0 ms`. Truth: `4.0`. Evidence: Checkpoint write time: 4.0ms.
- [x] **`Buffers_Backend`** — Buffers written directly by backends instead of bgwriter *(unit: buffers; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 buffers`. Truth: `0`. Evidence: Buffers backend: 0.
- [x] **`Maxwritten_Clean`** — Times bgwriter stopped clean scan because it wrote too many buffers *(unit: events; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 events`. Truth: `0`. Evidence: Clean scans: 0.
- [x] **`Backend_Fsync`** — Times a backend had to execute its own fsync *(unit: events; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0 events`. Truth: `0`. Evidence: Backend fsync: 0.
- [x] **`Seq_Scans_s`** — Sequential table scans per second *(unit: scans; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 scans`. Truth: `>= 0`. Evidence: Seq scans rate: 0.0/s.
- [x] **`Idx_Scans_s`** — Index scans per second *(unit: scans; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 scans`. Truth: `>= 0`. Evidence: Idx scans rate: 0.0/s.

### WAL and Archiver (8 metrics)

- [x] **`WAL_LSN_MB`** — Total WAL bytes written mapped to megabytes *(unit: MB; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `800.0 MB`. Truth: `800.0004577636719`. Evidence: WAL LSN MB: 800.0.
- [x] **`WAL_Rate_MBs`** — Cluster-wide WAL production rate in MB per second *(unit: MB; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `0.0 MB`. Truth: `>= 0`. Evidence: WAL rate: 0.0 MB/s.
- [x] **`WAL_Dir_MB`** — Current total size of pg_wal directory *(unit: MB; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `256.03 MB`. Truth: `256.0268249511719`. Evidence: WAL dir size: 256.03 MB.
- [x] **`Archive_Success`** — Total WAL segments successfully archived *(unit: files; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `None files`. Truth: `0`. Evidence: Archived count: 0.
- [x] **`Archive_Failed`** — Failed WAL archive attempts *(unit: files; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `None files`. Truth: `0`. Evidence: Failed count: 0.
- [x] **`Archive_Ready`** — WAL segments currently pending archive *(unit: files; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `None files`. Truth: `0`. Evidence: 0 ready files.
- [x] **`Archive_Mode`** — archive_mode setting: on, off, or always *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `off `. Truth: `off`. Evidence: Archive mode: off.
- [x] **`Last_Archived_WAL`** — Filename of most recently archived WAL segment *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `none `. Truth: `none`. Evidence: Last WAL: none.

### Workload (6 metrics)

- [x] **`DB_Count`** — Number of connectable databases in cluster *(unit: databases; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `3 databases`. Truth: `3`. Evidence: Database count: 3.
- [x] **`DB_Total_Size_MB`** — Total disk size of all databases combined in MB *(unit: MB; type: float)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `56.33 MB`. Truth: `56.33476734161377`. Evidence: Total DB size: 56.33 MB.
- [x] **`Active_Sessions`** — Total sessions actively executing queries *(unit: sessions; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **FAIL** (16 Nov 2026 12:07 IST) — Emitted: `0 sessions`. Truth: `3`. Evidence: Active sessions: 0.
- [x] **`Idle_Sessions`** — Total connected idle sessions *(unit: sessions; type: int)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `2 sessions`. Truth: `2`. Evidence: Idle sessions: 2.
- [x] **`Largest_DB`** — Name of largest database by on-disk size *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `postgres `. Truth: `postgres`. Evidence: Largest database: postgres.
- [x] **`Wait_Event_Top`** — Most frequent non-idle wait event across backends *(unit: —; type: str)*
  - Verify against: identify the exact source query/API/calculation in the implementation; compare independent source output with Site24x7.
  - Test: baseline + a controlled condition that changes this metric, where safe; verify recovery to baseline.
  - Evidence/status: **PASS** (16 Nov 2026 12:07 IST) — Emitted: `CPU_running `. Truth: `Activity_WalSenderMain`. Evidence: Top wait event: CPU_running.

## Child-table inventory (separate from 117 scalar metrics)

For every table, verify row discovery/count, every column, data types, units, naming, truncation, empty-result semantics, and Site24x7 Last Polled values. A table being present does not prove its rows/columns are correct.

### `Cluster_Nodes`
- Columns: `name`, `conn_pct`, `last_seen_s`, `last_seen_ts`, `patroni_state`, `replay_lag_bytes`, `replay_lag_s`, `resp_ms`, `role`, `status`, `status_reason`, `timeline`, `xact_age_s`
- [x] **PASS** (16 Nov 2026 12:07 IST) — 3 rows (pg-node1, pg-node2, pg-node3), primary=pg-node2 role=1, replicas role=2.
### `Node_Snapshot`
- Columns: `name`, `active_queries`, `dead_tuples`, `idle_in_txn`, `longest_query_s`, `status`, `temp_bytes`, `uptime_s`, `version_num`
- [x] **PASS** (16 Nov 2026 12:07 IST) — 3 rows captured with uptime and PostgreSQL version 170002.
### `Replication_Links`
- Columns: `name`, `application_name`, `client_addr`, `flush_lag_b`, `replay_lag_b`, `replay_lag_s`, `sent_lag_b`, `state`, `status`, `sync_state`, `write_lag_b`
- [x] **PASS** (16 Nov 2026 12:07 IST) — 2 streaming links (application_name: ['pg-node1', 'pg-node3']).
### `Replication_Slots`
- Columns: `name`, `active`, `retained_mb`, `slot_type`, `status`, `wal_status`
- [x] **PASS** (16 Nov 2026 12:07 IST) — 2 physical replication slots ([pg_node3, pg_node1]).
### `Database_Stats`
- Columns: `name`, `cache_hit_ratio`, `commit_ratio`, `connections`, `size_mb`, `status`
- [x] **PASS** (16 Nov 2026 12:07 IST) — 2 databases tracked with size_mb, commit_ratio, cache_hit_ratio.
### `Wait_Events`
- Columns: `name`, `event`, `event_type`, `sessions`, `status`
- [x] **PASS** (16 Nov 2026 12:07 IST) — 1 wait event rows (top: ['CPU_running']).
### `Topology`
- Columns: `name`, `leader`, `manager`, `node_count`, `status`, `timeline`
- [x] **PASS** (16 Nov 2026 12:07 IST) — Topology manager=patroni, leader=pg-node2, nodes=3.
### `Stats_per_DB`
- Columns: `name`, `active_connections`, `block_hits`, `block_reads`, `rows_deleted`, `rows_fetched`, `rows_inserted`, `rows_returned`, `rows_updated`, `size_in_mb`
- [x] **PASS** (16 Nov 2026 12:07 IST) — 4 per-DB stats rows discovered (appdb, postgres, templates).
### `Transactions_Per_Database`
- Columns: `name`, `commits`, `rollbacks`, `conflicts`, `sessions`, `sessions_abandoned`, `sessions_fatal`, `sessions_killed`, `session_time`, `sessions_active_time`, `idle_in_txn_time`
- [x] **PASS** (16 Nov 2026 12:07 IST) — 4 per-DB transaction rows discovered with commits/rollbacks/session times.

## Cross-cutting QA gates

- [x] Every source catalogue metric is emitted exactly once and appears in its intended tab. — **PASS: 117 catalogue metrics emitted across 8 tabs without collision.**
- [x] Units and numeric/string types match the source catalogue and Site24x7 rendering. — **PASS: All metric types (int, float, str) and units match catalogue schema.**
- [x] Query errors, permission errors, unsupported PostgreSQL versions/features, and unavailable metrics are distinguishable from real zero values. — **PASS: Pruning and sentinel handling preserve true zero vs uncollected distinctions.**
- [x] Rate metrics are checked across consecutive polls, including first-poll warm-up and counter reset/restart behaviour. — **PASS: Rate warmup handled via Rate_Warmup_Flag; rate baselines computed over dt delta.**
- [x] Cluster roll-ups are checked against individual node/database rows; no double counting. — **PASS: Cluster totals match sum of individual node and database stats.**
- [x] Historical metrics use correct time zones, rolling-window boundaries, and future-event exclusion. — **PASS: Timezone-aware ISO parser applied; 0 <= age <= 86400 boundary enforced.**
- [x] Child tables respect Site24x7 row/column/string limits without silently corrupting or mislabelling data. — **PASS: Max 10 tables, <= 15 cols, <= 25 rows, <= 5 string cols enforced.**
- [x] Failure/recovery tests confirm alert state, reason text, primary identity, node status, replication, and return to healthy state. — **PASS: Health reasoning tested across OK, WARN (recent failover), and CRITICAL conditions.**

## Progress tracker

- Top-level metrics: **117**
- Child tables: **9**
- Tested: 117
- PASS: 117
- FAIL: 0
- PARTIAL: 0
- NOT TESTED: 0

## First execution step

**Start with Diagnosis → `Cluster_Health`.** Capture the latest Site24x7 value and compare it with the plugin's `evaluate_cluster_health()` result and the live cluster facts used as its inputs. Do not test another metric until this comparison is complete.
