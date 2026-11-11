# PostgreSQL Cluster Plugin v5 — Spec + Build Prompt (v2, evidence-based)

**Decisions locked from discussion:**
1. **Node count**: real clusters are 1 primary + 2 standbys (3 nodes) as the canonical HA layout; 5–7 nodes is "large"; >10 per primary is where cascading starts. So 25 rows is *generous*, not a constraint. No fancy tiered-rollup machinery — deterministic priority order + one honest overflow row only if a cluster truly exceeds 25. One plugin monitor per cluster (Patroni scope), many monitors for many clusters.
2. **v4's four per-node tables** (`Node_IO`, `Node_Checkpoints`, `Node_Activity`, `Node_Transactions`): **dropped.** My call. They are 4 of the 10 table budget restating aggregate metrics — this is *why* the old plugin reads as a wall of counters. Their content survives as aggregate tab metrics + 4 useful columns in one `Node_Snapshot` row.
3. **Tier-2 rotation**: **removed.** Research says typical clusters are 3–7 nodes and `pg_stat_*` reads cost <1 % CPU. Rotation was solving a non-problem. Replaced by an **adaptive guard**: per-query `statement_timeout`, per-node budget, and heavy queries skipped once the collection budget is spent (reported in `Collect_Warnings`, never silent).
4. **`Cluster_Events`**: **cut.** No synthesised event history. `last_seen` + timeline + `failover_age` carry the story; the state file stays minimal.
5. Docker/Patroni test rig already exists (Antigravity). The plugin must be testable from its CLI against it; no fixtures shipped in-repo beyond `--self-test`.

---

## 0. Domain model the product must encode (drives every attribute)

### 0.1 What a standby actually is
A standby is **a complete, independent PostgreSQL server** — its own data directory, its own `shared_buffers`, its own WAL, its own processes, its own port. It is not "a copy of data" in the backup sense; it is a **live physical mirror** that continuously replays the primary's WAL stream. `pg_is_in_recovery()` is `true` on it.

Roles that actually exist in the field, and what the plugin must show for each:

| Role | What it is | What monitoring must answer |
|---|---|---|
| Primary | accepts writes, emits WAL via walsender | throughput, saturation, WAL/archive health, xid age, checkpoint pressure |
| Standby (sync) | acknowledged-before-commit replica; zero data loss | is it still sync? lag must be ~0; losing it changes your durability guarantee |
| Standby (async) | replica that may lag | lag seconds / bytes, is replay moving |
| Cascading standby | replica of a replica (tier 2) | own lag **plus** inherited tier-1 lag |
| Delayed replica (recovery_min_apply_delay) | deliberate hours-behind copy | lag is *expected* — must not page as an incident |
| Witness | votes only, no data | up/down and nothing else |
| Offline / failed | not streaming | since when, why, is it a failover candidate |

That last column is exactly the `role` enum in `Cluster_Nodes`. Teaching the user the roles and asserting them in one integer column is the same work.

### 0.2 Timeline = the failover counter
Every promotion starts a new **timeline**. So `Primary_Timeline` is literally "how many times this cluster has branched history since initdb", and `Timeline mismatch` between nodes is *the* objective split-brain/stale-node signal. Keep it prominent — it is the single most under-used metric in the old plugin.

### 0.3 What a standby does when idle
Writes nothing; sits on the WAL stream (`walreceiver` → startup process → buffers). It still runs checkpoints and honours `hot_standby` reads, and it *can* be hurt by monitoring: an idle-in-transaction monitoring session, or a long `hot_standby_feedback` snapshot, holds back vacuum on the primary / delays replay. Therefore the plugin must set `statement_timeout`, `idle_in_transaction_session_timeout`, `default_transaction_read_only=on`, and never open a transaction it doesn't close. **A monitoring plugin is capable of causing the lag it reports** — that is a requirement, not a nicety.

### 0.4 Why monitoring exists when Patroni exists
Patroni is a **control plane**: who holds the leader lock, promote/demote, make followers follow the right upstream. It is healthy by design while any of these are true:
- a replication slot is retaining 500 GB of WAL and the primary's disk fills in 40 minutes,
- `autovacuum` is starved and xid wraparound is 3 weeks away,
- `archive_command` has been failing for 6 hours (your backups are gone, replicas still stream fine),
- the primary is up but commits/sec has collapsed 90 %,
- a standby is "streaming" but 12 minutes behind, so promoting it loses data,
- a standby is paused / in recovery-conflict loops / can't accept connections,
- the failover already happened at 03:00 and nobody knows how long it took.

Patroni answers *"who is primary"*; monitoring answers *"is this cluster currently able to serve, and how close is it to not being able to"*. They compose: the plugin reads Patroni's REST API as its most reliable source of truth. Also HA ≠ backup: three replicas replicate a bad `DROP TABLE` in milliseconds.

### 0.5 Why other cluster types exist at all
Because they break the "1 primary + N standbys" assumption: Citus workers are all writable by design, pglogical/BDR is deliberately multi-primary, Stolon/PGAFO/CloudNativePG disagree on where truth lives, pgpool is a proxy in front of a cluster. v5 keeps detection only to avoid lying (crying "split brain" at Citus). **Patroni-first, generic physical fallback, everything else compatibility mode.**

---

## 1. Platform constraints (verified from Site24x7 docs)

10 tables · 15 columns/table · 25 rows/table · **5 string columns/table incl. `name`** · `name` ≤ 520 chars · other strings ≤ 100 · 200 metrics · 50 s script budget · reserved keys: `plugin_version`, `heartbeat_required`, `status`, `msg`, `units`, `tabs`, `s4z7config`.

Consequence: **states must be integers**; human words go in `name`, `msg`, and the ≤ 4 remaining string columns. That is the whole trick to fitting "everything about every node".

Row budget reality: 3–7 nodes typical, ≤ 25 covers them all. Deterministic ordering (primary → DOWN → WARN → alias) so tables are stable between cycles; one overflow row named `<n> more nodes` only if a cluster exceeds 25, counted in `Nodes_Omitted`.

---

## 2. State file (freshness, rates, dead nodes)

`<plugin_dir>/pgcluster_state.json`, atomic (`tempfile` + `os.replace`), 0600 where supported, no passwords/conninfo.

```
schema, cluster_id, updated,
primary { name, ts, metrics{} },
nodes { "<alias>": { ts_ok, ts_fail, last_role, last_reason } },
prev { ts, counters{} },
failover { ts, to, from_tl, to_tl }
```
Corrupt state ⇒ degrade exactly like v4, note in `msg`. Future timestamps treated as age 0.

**Primary-down contract (locked):** keep last-known-good values clamped (default TTL 1800 s) so charts don't flatline, alongside `Primary_Up=0`, `Primary_Data_Age_s`, `Primary_Data_Stale`, `Primary_Data_Source{live|clamped|none}`. Past TTL: freshness trio only. Never clamp anything that decides alert state.

---

## 3. Tabs (8) and tables (7)

Tabs: `Diagnosis`(1) · `Primary`(2) · `Nodes`(3) · `Replication`(4) · `Health & Capacity`(5) · `Performance`(6) · `WAL & Archiver`(7) · `Workload`(8).

Tables: `Cluster_Nodes` · `Node_Snapshot` · `Replication_Links` · `Replication_Slots` · `Database_Stats` · `Wait_Events` · `Topology`. (3 of 10 slots spare → headroom for future without a version bump that breaks templates.)

Removed vs v4: `Cluster_Info` (folded into `Topology` + Diagnosis metrics), `Stats_per_DB`/`Transactions_Per_Database` (→ `Database_Stats`), `Node_IO`/`Node_Checkpoints`/`Node_Activity`/`Node_Transactions` (→ aggregates + `Node_Snapshot`).

### 3.1 `Cluster_Nodes` — wide row, 14 cols, 4 strings

`name`(520) · `role`(int) · `status`(int) · `status_reason`(str) · `last_seen_s`(int) · `last_seen_ts`(str) · `timeline`(int) · `replay_lag_s`(float) · `replay_lag_bytes`(int) · `conn_pct`(float) · `resp_ms`(float) · `sync`(int) · `patroni_state`(int) · `xact_age_s`(int)

Dead nodes keep a row forever (from state) with `last_seen_ts` + reason. `name` carries a short human label: `pg2 · standby · lag 3s`.

### 3.2 Enums (documented, alertable)
```
status 0 down 1 up
role 0 unknown 1 primary 2 standby 3 witness 4 offline 5 cascading 6 delayed 7 standby_leader
sync 0 async 1 sync 2 quorum
health 0 ok 1 warn 2 critical
patroni_state 0 unknown 1 running 2 stopped 3 starting 4 stopped_failed 5 crashed 6 paused 7 creating_standby 8 n/a
risk 0 ok 1 warn 2 critical 3 lost
```

---

## 4. Probe budgets (replaces rotation)

Tier 0 all nodes (cheap): recovery state, timeline, lag/backlog, connections/max, uptime, oldest xact, Patroni state.
Tier 1 primary only: full Primary tab, archiver, WAL, checkpoints, bgwriter, dead tuples, xid, per-db, waits.
Guard: `statement_timeout=3000ms`, `connect_timeout=2s`, per-node deadline 3 s, collection deadline 8 s; if the deadline is hit, heavy queries are skipped for the remainder and recorded in `Collect_Warnings`. No user-facing rotation switch.

Rates from `prev` counters; first cycle emits 0 + `Rate_Warmup_Flag=1`; counter reset ⇒ 0 + note.

---

## 5. Metric set (unchanged from v1 except removals)

Drop `Collect_Time_ms`→keep, drop `Cluster_Events`, drop `PGSS_Available`→fold into `Collect_Warnings`. Diagnosis tab keeps: `Cluster_Health`, `Health_Code`, `Cluster_Role`, `Topology_Type`, `Health_Reason`, `First_Attention_Node`, `First_Attention_Reason`, `Action_Hint`, `Nodes_Total/Up/Down/Omitted`, `Primary_Timeline`, `Timeline_Spread`, `Failover_Age_s`, `Failover_Count_24h`, `Last_Failover_To`, `Collect_Warnings`, `Auth_Failure_Flag`.

Primary tab, Nodes roll-up, Replication, Health & Capacity, Performance, WAL & Archiver, Workload: as in v1 §4.4–4.5 (unchanged).

---

## 6. Errors, health engine, validation

Error taxonomy: `config_error`, `auth_failure` (+`Auth_Failure_Flag`, **never** "primary down"), `unreachable`, `metric_unavailable`, `pooler_detected`, `unsupported_cluster`, `budget_exceeded`.

Health precedence: CRITICAL (no primary · split brain · 0/N standbys streaming · slot lost/critical · xid ≥ 95 % · no failover candidate) → WARN (node down · lag/backlog · inactive slot · timeline mismatch · failover < window · xid ≥ warn · conn ≥ 90 % · archive failing · stale stats) → OK. Returns `(code, reason≤100, first_attention_node, action_hint)`.

`msg` contract, ≤ 180 chars:
`CRITICAL primary_down: no primary reachable (last seen pg1 07:12:44 IST, 14m ago) | 2/3 nodes up | hint: patronictl list`

In-process `validate_output()` every cycle: table count/cols/rows/strings, metric count, `tabs ∩ emitted = emitted`, `units ⊇ tabs`, name column, int status, truncation. Violations appended to `msg`, never raised.

`--self-test` (pure functions, no DB), `--dry-run`, `--json-out`.

---

## 7. README deliverables
3-step install · grant SQL per cluster manager (copy-paste, no superuser) · enum sheet · threshold table (metric/warn/crit/why) · runbook (symptom → 3 checks → fix) for: primary down, no failover candidate, split brain, standby lag, slot bloat, xid wraparound, WAL disk full, archive failing, auth failure, 25-row truncation, unsupported type · "26+ nodes" note (second monitor) · FAQ (why `Primary_Data_Stale`, why auth ≠ down, why we set `idle_in_transaction_session_timeout`).

---

# BUILD PROMPT (paste into Antigravity)

```
ROLE
Senior Python + PostgreSQL HA engineer. Deliver postgres_cluster.py (Python 3.9+,
stdlib + psycopg2, Linux and Windows agents, also runnable standalone), plus
postgres_cluster.cfg and README.md. One file, production quality, no placeholders.

PLATFORM LIMITS — the code must enforce these itself
10 tables max; 15 cols/table; 25 rows/table; 5 string cols/table incl. "name";
name<=520, other strings<=100; 200 metrics max; 50 s script budget (target <=8 s).
Reserved keys must never be used as metric names: plugin_version,
heartbeat_required, status, msg, units, tabs, s4z7config.
Always emit plugin_version, heartbeat_required, status and at least one numeric
metric, even on total failure.

CONTEXT FACTS (do not design against hypotheticals)
- Canonical cluster: 1 primary + 2 standbys (3 nodes). 5-7 nodes is large. >10
  replicas per primary is where cascading begins. 25 rows covers real clusters;
  order rows deterministically (primary, then DOWN, then WARN, then alias) and
  emit a single "<n> more nodes" overflow row only beyond 25, counted in
  Nodes_Omitted. Do not build a tiered-rollup scheme.
- Patroni is the primary target: REST API (default 8008) /patroni, /cluster,
  /history is the source of truth; SQL is the fallback. Then repmgr,
  pg_auto_failover, CloudNativePG, Stolon, Citus, pgpool-II, plain streaming,
  native/pglogical multi-master, standalone. Detection exists only to avoid
  lying (never report split brain on Citus or multi-master). Unsupported type =>
  status 0 + explicit msg.
- A standby is an independent server in recovery; roles that must be
  distinguishable: primary, standby(sync/async), cascading, delayed
  (recovery_min_apply_delay - high lag is EXPECTED, never page), witness,
  standby-leader, offline. Encode as the role enum.
- Timeline is the failover counter; a timeline mismatch between nodes is a
  first-class alert (Timeline_Spread, Timeline_Mismatch).

NEVER HARM THE MONITORED SERVER
Every connection sets: statement_timeout=3000, connect_timeout=2,
idle_in_transaction_session_timeout=10000, default_transaction_read_only=on.
Never hold an open transaction or a long snapshot (it can delay replay / hold
back vacuum on the primary). No monitoring query may ever cause a server-side
error under an under-privileged user: guard reads with to_regclass(),
has_table_privilege(), has_column_privilege().

STATE FILE — required
<plugin_dir>/pgcluster_state.json, atomic write (tempfile in same dir +
os.replace), 0600 where supported, never contains passwords or conninfo.
{schema, cluster_id, updated, primary{name,ts,metrics}, nodes{alias:{ts_ok,
ts_fail,last_role,last_reason}}, prev{ts,counters}, failover{ts,to,from_tl,to_tl}}
Corrupt/missing => degrade like v4, note in msg. Future ts => age 0.

PRIMARY-DOWN CONTRACT (headline feature)
While the primary is unreachable, keep emitting the last successful Primary-tab
values (clamped) so charts do not flatline, plus Primary_Up=0,
Primary_Data_Age_s, Primary_Data_Stale (1 past TTL, default 1800 s),
Primary_Data_Source (live|clamped|none). Past the TTL emit the freshness trio
only. Never clamp anything that decides alert state. msg names the dead primary,
when it was last seen (absolute local time + relative), how many nodes are up,
and one action hint.

TABS (exact keys/order; every tab metric must be emitted on a healthy cluster and
every emitted metric must live in exactly one tab - assert both in a self-test)
1 Diagnosis: Cluster_Health, Health_Code, Cluster_Role, Topology_Type,
  Health_Reason, First_Attention_Node, First_Attention_Reason, Action_Hint,
  Nodes_Total, Nodes_Up, Nodes_Down, Nodes_Omitted, Primary_Timeline,
  Timeline_Spread, Failover_Age_s, Failover_Count_24h, Last_Failover_To,
  Collect_Warnings, Auth_Failure_Flag
2 Primary: Primary_Up, Primary_Node, Primary_Data_Age_s, Primary_Data_Stale,
  Primary_Data_Source, Primary_Uptime_s, Primary_Connections,
  Primary_Max_Connections, Primary_Connection_Pct, Primary_Active_Queries,
  Primary_Idle_In_Txn, Primary_Longest_Txn_s, Primary_Blocked_Locks,
  Primary_Commits_s, Primary_Rollbacks_s, Primary_Tup_Inserted_s,
  Primary_Tup_Updated_s, Primary_Tup_Deleted_s, Primary_Cache_Hit_Ratio,
  Primary_Blks_Read_s, Primary_WAL_LSN_MB, Primary_WAL_Rate_MBs,
  Primary_WAL_Dir_MB, Primary_Checkpoints_Req_1h, Primary_Checkpoint_Write_ms,
  Primary_Dead_Tuples, Primary_XID_Age, Primary_XID_Wraparound_Pct,
  Primary_Archive_Ok, Primary_Archive_Failed, Primary_Archive_Ready,
  Primary_Archive_Lag_s, Primary_Sessions_Killed, Primary_Stat_Stale
3 Nodes (cluster roll-up): Standbys_Expected, Standbys_Streaming,
  Standby_Disconnect_Flag, Sync_Standby_Count, Cascading_Standby_Count,
  Delayed_Standby_Count, Max_Replay_Lag_s, Max_Replay_Backlog, Worst_Conn_Pct,
  Worst_Conn_Node, Slowest_Node, Slowest_Resp_ms
4 Replication: Replication_Slots_Total, Replication_Slots_Active,
  Inactive_Slots_Count, Max_Slot_Retained_MB, Slot_Risk,
  Logical_Replication_Used, Mesh_Links_Declared, Mesh_Links_Active,
  Mesh_Disconnect_Flag, Max_Logical_Lag_s, Subscription_Apply_Errors,
  Subscription_Conflicts
5 Health & Capacity: XID_Wraparound_Pct, Max_Temp_MB, Stale_Stats_Tables,
  Dead_Tuples_Total, Long_Running_Queries, Blocked_Sessions,
  Connection_Saturation_Pct, PGWAL_Used_Pct
6 Performance: Cache_Hit_Ratio, Index_Hit_Ratio, Blks_Read_s, Blks_Hit_s,
  Checkpoints_Timed, Checkpoints_Req, Checkpoint_Write_ms, Buffers_Backend,
  Maxwritten_Clean, Backend_Fsync, Seq_Scans_s, Idx_Scans_s
7 WAL & Archiver: WAL_LSN_MB, WAL_Rate_MBs, WAL_Dir_MB, Archive_Mode,
  Archive_Success, Archive_Failed, Archive_Ready, Last_Archived_WAL
8 Workload: DB_Count, DB_Total_Size_MB, Largest_DB, Active_Sessions,
  Idle_Sessions, Wait_Event_Top

CHILD TABLES (7, exact columns)
Cluster_Nodes: name, role(int), status, status_reason(str), last_seen_s,
  last_seen_ts(str), timeline, replay_lag_s, replay_lag_bytes, conn_pct,
  resp_ms, sync(int), patroni_state(int), xact_age_s
Node_Snapshot: name, role, commits_s, rollbacks, tup_s, blks_read_s, cache_hit,
  wal_mb, ckpt_req_1h, ckpt_write_ms, temp_mb, autovac_old_s, idle_in_txn,
  max_conn_pct, status
Replication_Links: name, link_type(int), state(int), replay_lag_s,
  replay_lag_bytes, write_lag_bytes, flush_lag_bytes, sync(int), source(str),
  target(str), status
Replication_Slots: name, slot_type(int), active, wal_retained_mb, risk(int),
  wal_status(str), status
Database_Stats: name, size_mb, connections, conn_pct, commits_s, rollbacks,
  cache_hit, blks_read_s, temp_mb, dead_tuples, age_xid, status
Wait_Events: name, wait_type(str), wait_event(str), sessions, avg_ms, max_s,
  blocked_by, status
Topology: name, role(int), addr(str), port, monitored, status
Max 4 string columns besides "name" in every table. Dead nodes keep a row
forever from the state file, with last_seen_ts and status_reason.
Enums: status 0/1; role 0 unknown 1 primary 2 standby 3 witness 4 offline
5 cascading 6 delayed 7 standby_leader; sync 0 async 1 sync 2 quorum;
health 0 ok 1 warn 2 critical; patroni_state 0 unknown 1 running 2 stopped
3 starting 4 stopped_failed 5 crashed 6 paused 7 creating_standby 8 n/a;
risk 0 ok 1 warn 2 critical 3 lost.

PROBING
ThreadPoolExecutor(min(16,N)); per-node deadline 3 s; collection deadline 8 s.
Tier 0 all nodes; Tier 1 primary only (full set). If the collection deadline is
exceeded, skip remaining heavy queries and record it in Collect_Warnings - never
silently. No user-facing rotation setting. Rates from prev counters; first cycle
0 with Rate_Warmup_Flag=1; counter reset => 0 + note. Patroni REST first (1 s
timeout), SQL fallback. Discovery: Patroni /cluster -> repmgr -> Citus -> pgafo
-> wal_receiver/wal_sender walk, always merged with state-file members so
long-dead nodes remain visible. address_map stays for Docker/NAT.

ERRORS
config_error, auth_failure (Auth_Failure_Flag=1, must NOT read as "primary
down"), unreachable, metric_unavailable, pooler_detected, unsupported_cluster,
budget_exceeded. Classify every failure; no bare excepts; collect notes into
Collect_Warnings.

HEALTH ENGINE (pure, unit-tested)
CRITICAL: no primary; split brain (>1 primary and not multi-master/Citus); 0/N
standbys streaming when N>=1; sync standbys below synchronous_node_count; slot
lost or retained > critical; xid >= 95 %; no failover candidate while primary is
down. WARN: node down; lag > threshold or backlog > threshold; inactive slot or
retained > warn; timeline mismatch; failover within window; xid >= warn; conn
>= 90 %; archive failures; stale stats. Delayed standbys are excluded from lag
alerts. Message style:
"<SEVERITY> <code>: <fact> (<quantified>) | <context> | hint: <action>"

VALIDATION (shipped in the file, runs every cycle, cheap)
validate_output(data): table count/cols/rows/string-count, metric count, name
column present, int status, tabs<->emitted<->units both directions, truncation,
reserved keys. Violations go to msg as "schema: ...", never raise.

CLI/CFG
run(param)->dict entry point. argparse: --cluster_host --postgres_port
--patroni_port --username --password (prefer PGPASSWORD) --db --cluster_type
--discover --address_map --cluster_name --state_dir, all thresholds, --json-out,
--dry-run, --self-test, --version. cfg: [global_configurations]
keys_to_encrypt=password + [postgres_cluster] with defaults that work unchanged
for Patroni: cluster_host, postgres_port=5432, patroni_port=8008,
username, password='change_me_monitor', db=postgres, cluster_type=auto,
discover=auto, address_map=, failover_warn_seconds=900, replay_warn_seconds=60,
replay_warn_bytes=104857600, slot_warn_bytes=1073741824,
slot_critical_bytes=10737418240, xid_warn_percent=70, primary_clamp=on,
primary_clamp_ttl=1800, state_dir=. Plus a commented second section showing a
second monitor for another cluster.

README
Install in 3 steps; grant SQL per cluster manager (no superuser); enum sheet;
threshold table (metric/warn/crit/why); runbook symptom->3 checks->fix for:
primary down, no failover candidate, split brain, standby lag, slot bloat, xid
wraparound, WAL disk full, archive failing, auth failure, unsupported type,
25-row overflow; how to monitor many clusters (one monitor per cluster);
FAQ (why Primary_Data_Stale, why auth != down, why no rotation, why replicas are
not backups); appendix: every metric with unit and source query.

STYLE
Type hints on public functions; docstring per function states its invariant;
deterministic ordering; no dead metrics; no unused code; Windows-safe (no fcntl,
no fork, UTF-8 explicit, flush before os._exit); exit 0 always except
--self-test.
```

---

## 8. Still open (small)

- `sync` column needs `synchronous_node_count` from Patroni's `/config` to alert "fewer sync standbys than required" — confirm we read `/config` (extra 1 s call, cached in state).  **Default yes.**
- Delayed standby detection: `recovery_min_apply_delay` on the node (`SHOW`) — cheap, one query on standbys. **Default yes.**
