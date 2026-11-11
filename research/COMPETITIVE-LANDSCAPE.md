# Competitive landscape — PostgreSQL monitoring, top 10 tools + every OSS collector

Research date: 2026-11-11. Every claim below about an open-source project comes from **reading its source**, not from marketing pages. Repos cloned/read: 15. Files read in full or in relevant part: ~120.

**Line counts are measured on the actual trees** (`find *.go|*.py|*.sql` → `wc -l`), not estimated.

---

## 0. Framework: six axes every tool sits on

Tool comparisons in this category are usually fake, because they compare feature bullets. These six axes are the real design decisions, and every tool in this document is a different point in that space:

| Axis | Values | Why it matters to us |
|---|---|---|
| **A. Collection model** | pull via agent · long-running daemon · one-shot binary · log parsing · eBPF · DB-side extension · SaaS agent | decides our timeout budget and install story |
| **B. Unit of monitoring** | instance · **cluster** · fleet · query · application request | our product bet is the **cluster** |
| **C. Where truth lives** | hardcoded in code · declarative YAML catalogue · `.sql` files · DB-side functions | decides how maintainable the plugin is |
| **D. How it answers "what's wrong"** | raw gauges + dashboard · static thresholds · rules with severity + remediation · ML baseline · nothing | our `Health(code, fact, hint)` object |
| **E. HA / cluster awareness** | none · role tag only · topology walk · full (primary election, timeline, failover) | **the gap we exploit** |
| **F. Cost shape** | per host · per instance · per DB · per server/yr · per GB · per monitor · free/self-hosted | Site24x7 is per-monitor, which is our advantage |

---

## 1. The ten tools, ranked by how they actually navigate

### 01 — Datadog Database Monitoring + Postgres check
- **Repo (agent check, open source):** `DataDog/integrations-core` → `postgres/datadog_checks/postgres`, v23.15.0
- **Size:** 30 files, **8,252 LOC** in the package; `util.py` 1,421 (the catalogue), `diagnose.py` 1,020, `statement_samples.py` ~1,400, `relationsmanager.py` 523, `config.py` 572, plus `data/conf.yaml.example` 49.6 KB = **120 config options**
- **A:** pull, long-running Python agent, per-endpoint instance
- **B:** **instance**. A cluster is N unrelated instances joined in SaaS by tags that happen to match.
- **C:** declarative scopes in `util.py` — **49 scope dicts**, each `{name, query, metrics:{col:(metric, submit_fn)}, descriptors, relation}`; `metrics_cache.py` selects the set per PG version
- **D:** raw metrics + **`diagnose.py`: 15 pre-flight probes** with `DatabaseConfigurationError` enum + `DIAGNOSTIC_METADATA{description, remediation, docs_anchor}` and **cascade skipping** (never says `CREATE EXTENSION` when `shared_preload_libraries` is empty)
- **E:** **none.** `grep -ri "patroni\|failover\|repmgr\|pg_auto_failover"` → **0 hits**. Standby = metric tag `replication_role:standby`. `control.timeline_id` collected but never compared across nodes.
- **F:** per host, + per-DBM-host
- **Metric surface:** ~**143** distinct metric names, 30 tag keys, 107 column-style + 36 tuple-style
- **Steal:** catalogue-not-code · remediation text per error code · capability gating (`is_aurora`, `V9…V18`) · cursor that prefixes `/* service=datadog-agent */` and `/* DDIGNORE */` · `SQL_ASCII` decode fallback · version parse that survives `11.22-rds.20241121` and `12.3_TDE_1.0` · `pg_settings` load · LRU connection pool with `statement_timeout` · truncation warnings
- **Avoid:** 120 options; DB-side objects (`datadog` schema, `explain_statement()`, column-stats function) as a prerequisite; statelessness (a dead host just stops reporting)

### 02 — Percona PMM
- **Repo:** `percona/pmm` (1,135★, **614,721 LOC** Go+TS+SQL, 1,849 files read by pattern)
- **A:** agent (pmm-agent) + collectors (`mysqld_exporter`, `postgres_exporter` fork, `mongodb_exporter`) + a **self-hosted server** (VictoriaMetrics + Postgres for QAN)
- **B:** fleet of instances; QAN is per-query per-schema
- **C:** **`managed/data/checks/*.yml` — 112 check files, 27 for PostgreSQL**, each = `{name, summary, description, family, advisor, interval, queries:[{type: POSTGRESQL_SELECT, query}], script: <Starlark>}`
- **D:** **advisors** — the Starlark `check_context(docs, context)` returns rows of `{summary, description, read_more_url, severity}`. This is *advisor output as data with a docs URL*. Interval tier is a keyword (`interval: standard`).
- **E:** partial — dedicated dashboards for HA clusters, `pg_stat_replication` metrics, but no primary election/timeline logic
- **F:** free, self-hosted; the cost is the server + operator
- **Steal:** **the advisor file format.** Our health codes should carry exactly this triplet: *what it is, why it matters, read-more link*, computed in code but documented in one place. Also `interval` tiers as keywords.
- **Avoid:** running a server. Not our budget.

### 03 — pganalyze (+ open-source collector)
- **Repo:** `pganalyze/collector` (408★, Go; **input/postgres = 35 files**, `state/` = 30 files, `output/` 12 files; total tree ~12 MB source)
- **A:** agent, continuous collection, upload to SaaS (or self-hosted)
- **B:** instance + **query-level** (normalised statements, plans) + schema/relations
- **C:** Go code per subsystem: `input/postgres/{backends,buffer_cache,databases,relation_stats,relation_stats_ext,explain,explain_analyze,replication,roles,schema,server_stats,extensions,functions,plans,…}.go`; `input/system/{rds,azure,google_cloudsql,heroku,neon,supabase,crunchy_bridge,tembo,…}` for managed-cloud variants
- **D:** **advisors as a product** — Index Advisor (what-if index combos), VACUUM Advisor, Log Insights with 100+ PII filters, plan comparison over time
- **E:** partial — `input/postgres/replication.go`, but the product story is tuning, not HA
- **F:** per-server subscription
- **Steal:** the **split by cloud provider** (`input/system/rds`, `azure`, `google_cloudsql`, `neon`…) — we should recognise managed Postgres and suppress the queries it breaks on, per provider, not just "Aurora". Also the idea of `state/` giving **delta computation** (they diff relation stats between runs, same requirement as our rates).
- **Avoid:** plan collection (needs backend + `auto_explain` + PII story).

### 04 — Netdata (go.d postgres collector)
- **Repo:** `netdata/netdata` (81,366★), module at `src/go/plugin/go.d/collector/postgres/`
- **Size:** `charts.go` **1,400** · `metadata.yaml` **1,277** · `queries.go` 778 · `collect_metrics.go` 367 · `do_query_global.go` 285 · `metrics.go` 231 · `do_query_databases.go` 160 · `do_query_replication.go` 91, plus `do_query_{tables,indexes,bloat,columns,misc}.go`, `func_top_queries.go`, `func_running_queries.go`
- **A:** pull, per-second, one Go plugin binary inside the agent; Functions for top/running queries queryable by the UI
- **B:** instance **with per-database fan-out** (`collect_databases_matching` regex, caps `max_db_tables`, `max_db_indexes`)
- **C:** chart definitions in `charts.go` + metric metadata in `metadata.yaml` (per-chart: unit, dimension, description) — the **taxonomy is a separate machine-readable file**
- **D:** **alerts ship with the collector** (defined in metadata/health config) + ML per metric
- **E:** partial — replication/receiver charts, but no primary election or timeline logic
- **F:** free agent, per-node pricing for cloud
- **Steal:** **metric metadata as a machine-readable file** (`metadata.yaml`) separate from collection code — Site24x7's `units`/`tabs` should be *generated from* the same structure. Also the per-domain query file split (`global / databases / replication / tables / indexes / bloat`), and function-based drilldown (top queries) as an *optional* on-demand feature.
- **Avoid:** per-second collection (we have a 50 s script per poll), and chart-granular dashboards (Site24x7 renders what we declare, nothing more).

### 05 — pgwatch (CYBERTEC)
- **Repo:** `cybertec-postgresql/pgwatch` (904★, **28,019 LOC** Go)
- **Size:** `internal/metrics/metrics.yaml` = **5,288 lines**, **96 metric definitions** + **14 presets**
- **A:** long-running daemon; pluggable **sources** (`internal/sources`) and **sinks** (`internal/sinks`: postgres, prometheus, json, rpc, multiwriter)
- **B:** fleet, with per-database granularity; supports Patroni clusters and pgbouncer/pgpool sources
- **C:** **YAML catalogue per metric**: `{sqls: {11:..., 13:..., 16:...}, init_sql, statement_timeout_ms, gated_by, …}`
- **D:** mostly raw metrics + Grafana; plus **`reco_*` metrics** (recommendations *as metrics*): `reco_add_index`, `reco_drop_index`, `reco_disabled_triggers`, `reco_nested_views`, `reco_partial_index_candidates`, `reco_sprocs_wo_search_path`, `reco_superusers`, `reco_default_public_schema`
- **E:** **partial-plus** — has a **`patroni` preset**, `instance_up`, `change_events`, `configuration_hashes`, `privilege_changes`
- **F:** free
- **★ The single best idea in this entire survey:** every metric carries **its own collection interval**, and presets are just `{metric: seconds}` maps — `minimal`, `basic`, `standard`, `exhaustive`, `full`, `exhaustive_no_python`, plus cloud/preset variants `aiven`, `aurora`, `azure`, `gce`, `rds`, `patroni`, `pgbouncer`, `pgpool`, `recommendations`, `debug`. Example from `aiven`: `db_stats: 60, index_stats: 900, table_bloat_approx_summary_sql: 7200, reco_add_index: 43200`.
- **Steal:** **per-metric cadence with named presets.** This is the correct answer to "why rotation?" that I fumbled earlier: it is not a hidden heuristic, it is a **declared, documented, per-metric interval**, with a preset name the user chooses (`preset = standard`). It also fixes 30-node scaling honestly: cheap stuff every cycle, expensive stuff every N cycles, *stated in the README instead of discovered in a timeout*.
- **Avoid:** the daemon + external sink requirement.

### 06 — postgres_exporter (Prometheus community)
- **Repo:** `prometheus-community/postgres_exporter` (3,648★, **20,475 LOC** Go, 136 files)
- **Size:** **36 collector files** (`pg_stat_*`, `pg_replication*`, `pg_locks`, `pg_long_running_transactions`, `pg_wal`, `pg_database_wraparound`, `pg_process_idle`, `pg_roles`, `pg_setting`, `pg_buffercache_summary`, + 10 `aurora_*` collectors)
- **A:** pull (Prometheus scrapes `/metrics`)
- **B:** instance; `--auto-discover-databases` fans out
- **C:** one Go file per collector, self-registering by name → `--collector.<name>` toggles; custom SQL via `--extend.query-path` + `queries.yaml`
- **D:** none — **raw counters only**; `rate()`/`avg_over_time` happen in PromQL, alerts in Alertmanager rules
- **E:** **none** — no role, no topology, no `pg_is_in_recovery` per se beyond `pg_replication` counters
- **F:** free
- **Steal:** **collector-per-view modularity** (a broken/blocked view breaks one collector, not the export) and the flags: `--disable-default-metrics`, `--collection-timeout`, `--collector.<name>` allow/deny list, `config/redact.go` (masking secrets in logs).
- **Avoid:** counters-only (the reason Prometheus needs PromQL is that the exporter has no memory — we have a state file, so we ship rates directly).

### 07 — pganalyze… (see 03). Next: **New Relic `nri-postgresql`**
- **Repo:** `newrelic/nri-postgresql` (27★, **6,973 LOC** Go; legacy SDK)
- **Size:** `queries/{database_queries,instance_queries,inventory}.pgsql` + `legacy/postgresql-definition.yml` (YAML metric definitions with `event_type`, `unit`, `inventory` sections)
- **A:** agent (infrastructure agent integration)
- **B:** instance → surfaces as NR entities
- **C:** **SQL in `.pgsql` files + YAML definitions** (metric name, unit, event type) — closest to "SQL is data" of all the small collectors
- **D:** none native; DBmarlin integration supplies time/waits/top-SQL
- **E:** none
- **F:** per-GB ingest
- **Steal:** the **three-file split**: instance-scope queries vs database-scope queries vs inventory (what objects exist, reported once). Inventory = "what am I monitoring" as a separate report — we should do that with `Topology`.

### 08 — SolarWinds DPA — *closed source, navigation from docs*
- **A:** agentless remote collector (single appliance pulling from DB)
- **B:** instance; per-database
- **D:** **wait-time analysis** — the primary abstraction is *time spent waiting*, broken into disk I/O / locks / CPU / network
- **E:** partial (RAC/AG style HA for Oracle/SQL Server; Postgres support is metric-based)
- **F:** per-instance subscription
- **Takeaway for us:** wait-time is the highest-signal abstraction in the category. We already have `Wait_Events` table + `Wait_Event_Top`; make **`Primary_Wait_Top` + `Wait_Time_Pct`** a first-class Diagnosis-tab pair rather than a Workload afterthought.

### 09 — Redgate Monitor — *closed source*
- **A:** agent-based, self-hosted or SaaS
- **B:** estate of instances
- **D:** alerts + **deployment tracking** (correlates releases with performance regressions) + "Monitor AI"
- **E:** partial (SQL Server AGs; Postgres is metrics + sessions)
- **F:** per-server per-year
- **Takeaway:** *change correlation* is the one feature nobody open-source ships. Our version: `pg_stat_database` × timeline change × `change_events`-style detection of DDL/`shared_preload_libraries` change between polls. Cheap, and it answers "what changed?".

### 10 — Dynatrace — *closed source* · **Site24x7** (our own host platform) · **ManageEngine Applications Manager** — *closed source*
- **Dynatrace:** A app + OneAgent (deep, eBPF-ish), B instance+request, D **Davis AI** (baseline + causal), E partial, F per-host-per-GB-RAM. 1-minute minimum interval noted even by Netdata's own list.
- **Site24x7:** A agent + agentless DB monitors, B instance, D **wait-time analysis** + thresholds, E none/instance-level, F **per monitor** — and, from reading its official public plugin: `site24x7/plugins/postgres/postgres.py`, **313 lines, PLUGIN_VERSION 1, credentials hardcoded at the top**, one tab list containing the literal typo `"Tranasctions_and_Session_per_Database"`. **That is the quality bar we are replacing.**
- **ManageEngine:** A agentless, B instance/fleet, D thresholds + query monitor, E none, F per-monitor. Wins on legacy engine breadth (DB2/Informix/Sybase), loses on depth.

---

## 2. The other collectors (not in the top-10 lists, but they shape the design)

| Tool | Repo | Size | Navigation | What to take |
|---|---|---|---|---|
| **check_postgres** | `bucardo/check_postgres` (604★, Perl, **12,560 LOC**) | 1 file, **87 actions** | **one action per invocation**, Nagios exit code + perfdata. Actions incl. `replication_slots`, `hot_standby_delta`, `btree_bloat`, `table_bloat`, `invalid_indexes`, `sequence_exhausted`, `pg_dump_backup`, `last_analyze`, `last_vacuum`, `wal_files`, `autovacuum` | **Closest philosophy to ours**: a check, not a dashboard. Steal its action list as a checklist of what operators actually alert on. |
| **check_pgactivity** | `OPMDG/check_pgactivity` (188★, Perl) | 1 script, **53 services** | Nagios plugin, `--service=…`, thresholds with `--warning/--critical`, has `is_master` / `is_hot_standby` / `is_replay_paused` as first-class services | Role detection and replay-pause as **alertable services**; also `orphan_files`, `pgdata_permission`, `checksum_errors`, `sequence_exhausted` |
| **pgmetrics** | `rapidloop/pgmetrics` (1,114★, **9,989 LOC** Go) | `model.go` 1,304 lines, **766 JSON fields**; `collector/{collect,citus,pgbouncer,pgpool,log,system_*}.go` | **one-shot binary**: collect everything once, print JSON/report, exit. Normalises by version into one giant struct; also collects OS-level (`system_linux.go`) | **Our output should be this complete.** 766 fields is far past our 200-metric limit, but it is the best checklist of *what exists to collect*. Also: OS + DB in one snapshot (we can add `PGWAL_Used_Pct` via `statvfs`). |
| **pgbadger** | `darold/pgbadger` (4,074★, Perl) | log parser | **log mining** — the only source for autovacuum detail, checkpoint timing, connection errors, lock waits | Reminds us what we cannot see from `pg_stat_*`: the server log. Document it in the runbook ("if you need this, enable `log_autovacuum_min_duration`, `log_checkpoints`"). |
| **coroot** | `coroot/coroot` (8,010★, Go) | `auditor/postgres.go` **1,661 LOC**, `constructor/postgres.go` 345, `model/postgres.go` 186 | eBPF + agent; **auditor = rule engine** producing per-instance statuses (`autovacuum_disabled`, `checkpoint` settings, `replication_slot`, `prepared_transaction`, `max_connections` reserved…) and a **topology constructor** | **Closest existing tool to our thesis**: rules with statuses + topology. Steal the rule *names* and the idea that the model is built once and the auditor reads it. |
| **temboard** | `dalibo/temboard` (769★, **30,216 LOC** Python) | agent + UI, probes per plugin (`activity`, `monitoring`, `statements`, `maintenance`, `pgconf`) | agent pushes probe data to a central UI | **`plugins/monitoring/alerting.py` `bootstrap_checks()`** ships sensible warn/crit pairs per metric out of the box: `wal_files_archive 10/20`, `wal_files_total 50/100`, `sessions_usage 80/90`, `replication_lag 1 MB/10 MB`, `hitreadratio_db 90/80`, `waiting_sessions_db 5/10`, `fs_usage_mountpoint 80/90`. **This is exactly the threshold table our README must ship** — authoritative, because it comes from a DBA tool vendor. |
| **pganalyze collector** | above | `input/system/*` per cloud | provider-specific query suppression | recognise RDS/Aurora/CloudSQL/Azure/Neon/Supabase/Crunchy/Heroku |
| **pg_stat_monitor** | `percona/pg_stat_monitor` (593★) | DB extension | better `pg_stat_statements` (buckets, histograms, query plans) | if present, our Workload tab can use buckets instead of a single sample |

---

## 3. What "how they navigate" actually looks like, side by side

| Tool | A. collection | B. unit | C. truth | D. answers "what's wrong" | E. cluster/HA | F. cost |
|---|---|---|---|---|---|---|
| Datadog | agent pull | instance | 49 YAML-ish scopes in code | **15 probes + remediation text** (on demand) | **none** (role tag only) | per host + DBM |
| PMM | agent + server | fleet+query | **112 check YAMLs + Starlark** | **advisors w/ severity + docs URL** | partial | free/self-hosted |
| pganalyze | agent push | instance+query | Go per subsystem, per cloud | advisors (index/vacuum/plan) | partial | per server |
| Netdata | per-second agent | instance+db | charts + **metadata.yaml** | alerts + ML | partial | free agent |
| **pgwatch** | daemon + sinks | fleet+db | **96 metrics, per-version SQL, per-metric interval** | `reco_*` metrics + Grafana | **patroni preset** | free |
| postgres_exporter | scrape | instance | 36 self-registering collectors | **nothing** (PromQL) | none | free |
| nri-postgresql | agent | instance | `.pgsql` + YAML | nothing native | none | per GB |
| DPA | agentless pull | instance | product | **wait-time analysis** | partial | per instance |
| Redgate | agent | estate | product | alerts + **deployment tracking** | partial | per server/yr |
| Dynatrace | OneAgent | instance+request | product | Davis AI baseline | partial | per host+RAM |
| Site24x7 | agent | instance | **313-line plugin, hardcoded creds** | thresholds | none | **per monitor** |
| ManageEngine | agentless | instance+fleet | product | thresholds + query monitor | none | per monitor |
| check_postgres | one-shot | instance | 87 actions | **exit code + perfdata** | partial | free |
| check_pgactivity | one-shot | instance | 53 services | exit code + perfdata | partial (`is_master`) | free |
| pgmetrics | one-shot | instance(+OS) | **766-field struct** | none (report) | partial | free |
| coroot | eBPF+agent | fleet+topology | **auditor rules** | **per-instance status rules** | **best in class (topology)** | free/paid |
| temboard | agent push | instance | probes + UI | **built-in warn/crit defaults** | partial | free |

---

## 4. Patterns ranked by value-per-effort for our v5

1. **Per-metric declared interval + named presets** *(pgwatch)*. Kills the "rotation" hand-wave, scales to 25 nodes honestly, costs ~30 lines. `preset = minimal|standard|exhaustive|patroni|…`, `{metric: seconds}` map in the catalogue, cycle counter in the state file. **Adopt.**
2. **Error codes with description + remediation + docs anchor** *(Datadog `DIAGNOSTIC_METADATA`, PMM advisors)*. Already planned; now with PMM's `{summary, description, read_more_url, severity}` shape and Datadog's cascade skipping. **Adopt.**
3. **Shipped warn/crit defaults per metric** *(temboard `bootstrap_checks`)*. We cannot set Site24x7 thresholds programmatically, so we ship the table in the README *and* encode `hint` in the catalogue. **Adopt.**
4. **Catalogue as data, metadata as a separate machine-readable file** *(Datadog `util.py`, Netdata `metadata.yaml`)*. `units`/`tabs` generated, never hand-maintained. **Adopt.**
5. **Role as a first-class alertable service** *(check_pgactivity `is_master`, `is_hot_standby`, `is_replay_paused`)*. We already emit role; add `Replay_Paused_Flag`, `Recovery_Conflicts_Active`. **Adopt.**
6. **Wait-time as the primary abstraction** *(SolarWinds DPA)*. `Primary_Wait_Top`, `Wait_Time_Pct` on Diagnosis, not Workload. **Adopt.**
7. **Recommendations as metrics** *(pgwatch `reco_*`)*. A `Recommendations_Count` + `Top_Recommendation` string, from cheap rules (unused index, bloated table, autovacuum off, idle-in-txn). Very high perceived value, low cost. **Adopt (light).**
8. **Inventory as a separate report** *(nri-postgresql `inventory.pgsql`)*. `Topology` table = what exists (nodes, roles, ports, tiers, managed-cloud flags). **Adopt.**
9. **Change detection** *(Redgate deployment tracking, pgwatch `change_events` / `configuration_hashes`)*. Between polls: timeline change (failover), `shared_preload_libraries` / `max_connections` change, DDL count delta. Emit `Changes_Detected` + last change string. **Adopt (cheap).**
10. **Collector-per-view isolation** *(postgres_exporter)*. Our phase/scope model already does this; add "one failing view cannot zero the whole tab".
11. **On-demand drilldown functions** *(Netdata Functions)*. Site24x7 has no such channel — skip. *(But note: the agent runs our script, so a `--top-queries` CLI mode is a legitimate "ask the agent" path for support engineers.)*
12. **ML baselines** *(Netdata/Dynatrace/Datadog)*. Site24x7 does anomaly detection server-side; we should export clean, stable metric names and let the platform do it. **Don't build.**

---

## 5. The gap list — what nobody in this survey does

Ranked by how much it matters to *our* customer (Site24x7, 20–30 nodes as clusters of 3, small team):

1. **Cluster truth in one monitor.** Only coroot has topology; nobody combines *primary election + timeline spread + sync-standby expectation + Patroni/DCS state + cascading/delayed classification* into one object. Datadog has literally zero of it.
2. **Death narrative.** Nobody records "this node died at 07:12:44 and has been down 14 m" inside the monitoring payload. Datadog/pganalyze go silent; exporters stop exporting.
3. **Last-known-good for the primary.** Every tool flatlines to zero or stops reporting when the thing you care about most dies. No tool clamps + stamps freshness (`Primary_Data_Age_s`, `Primary_Data_Stale`).
4. **Action sentence instead of a chart.** PMM advisors are the only ones producing `{summary, description, url, severity}` — and only for *advisory* topics, never for "your primary is gone, do this."
5. **Sync-standby actual vs expected** (`synchronous_standby_names` / Patroni `synchronous_node_count` parsed and compared to reality). Everyone shows `sync_state`; nobody tells you your durability guarantee silently dropped.
6. **XID wraparound as a thresholded percentage** (`age(datfrozenxid) / autovacuum_freeze_max_age`). pgwatch/PMM/coroot approximate it with hardcoded 1e9 or 2e9; we read the GUC.
7. **Delayed-replica awareness** (`recovery_min_apply_delay`). Everyone alerts on lag; nobody suppresses the alert for a replica that is supposed to be behind.
8. **Auth-failure ≠ down.** Nobody distinguishes "primary is dead" from "my monitoring password is wrong" as separate alert classes.
9. **Self-cost as a metric.** Datadog warns in logs; nobody emits `Collect_Time_ms` / `Slowest_Scope` as alertable metrics for a plugin-based monitor.
10. **DCS/quorum blindness.** A Patroni cluster can have a healthy primary and no quorum to fail over. Nothing in this survey checks etcd/ZooKeeper reachability as part of cluster health.

---

## 6. Concrete changes this research forces into v5

1. Catalogue entry gains **`interval`** (seconds) and the config gains **`preset`**; presets `minimal|standard|exhaustive|patroni|managed|debug` replace any hidden rotation logic.
2. Every health code gains **`description` + `remediation` + `docs_anchor`**; codes and text live in one dict (Datadog `DIAGNOSTIC_METADATA` / PMM advisor shape).
3. README ships **temboard-grade default thresholds** (warn/crit per metric), mirrored as `hint` in the catalogue.
4. New metrics: `Replay_Paused_Flag`, `Recovery_Conflicts_Active`, `Primary_Wait_Top`, `Wait_Time_Pct`, `Recommendations_Count`, `Top_Recommendation`, `Changes_Detected`, `Last_Change`, `Sync_Standby_Expected`, `Delayed_Standby_Count`.
5. **Managed-provider capability layer** (`rds|aurora|cloudsql|azure|neon|supabase|crunchy|heroku|self`) instead of a single `is_aurora` flag.
6. `Topology` table = the inventory report (node, role, addr, port, tier, managed flag, monitored).
7. Keep: cluster truth model, state file, primary clamp, 25-row determinism, numeric enums, 8 tabs / 7 tables.
8. Never adopt: daemon, server, DB-side functions, 120 options, per-relation metric explosion.

---

## 7. Sources

- Netdata buyer's guide (the list that seeded this survey): `netdata.cloud/resources/best-database-monitoring-tools/` — vendors ranked: Netdata, SolarWinds DPA, Percona PMM, Dynatrace, pganalyze, Redgate Monitor, New Relic, Site24x7, ManageEngine.
- Source read directly: `DataDog/integrations-core@postgres`, `percona/pmm`, `pganalyze/collector`, `netdata/netdata@go.d/postgres`, `cybertec-postgresql/pgwatch`, `prometheus-community/postgres_exporter`, `newrelic/nri-postgresql`, `bucardo/check_postgres`, `OPMDG/check_pgactivity`, `rapidloop/pgmetrics`, `darold/pgbadger`, `coroot/coroot`, `dalibo/temboard`, `percona/pg_stat_monitor`, `site24x7/plugins@postgres`.
- Site24x7 plugin platform limits: `site24x7.com/help/admin/adding-a-monitor/plugins/custom-plugins.html` (10 tables, 15 cols, 25 rows, 5 string cols, 200 metrics, 520-char name, 50 s timeout).
- Closed-source navigation (DPA, Redgate, Dynatrace, ManageEngine, Site24x7 DB monitors) is taken from vendor docs + the Netdata vendor profiles; marked as such above.
