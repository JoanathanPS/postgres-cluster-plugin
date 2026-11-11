# Datadog Postgres check — full teardown

Source: `integrations-core/postgres/datadog_checks/postgres`, version **23.15.0**.
30 files, **8,252 LOC** in the package, plus `data/conf.yaml.example` (49.6 KB, **120 config options**).

## 1. Inventory

| File | LOC | What it actually does | Take it? |
|---|---|---|---|
| `postgres.py` | 1600+ | orchestration shell: init, connect, check(), dynamic query assembly, autodiscovery pass | partial (phases) |
| `util.py` | 1421 | **the metric catalogue**: 49 scope dicts, every SQL query, `DatabaseConfigurationError` enum, `DIAGNOSTIC_METADATA` (description + remediation + docs anchor per code) | **yes — the core idea** |
| `diagnose.py` | 1020 | 15 pre-flight probes, `agent diagnose` style: version, `pg_monitor` role, `pg_stat_statements` (preload/extension/readable/max), `track_io_timing`, `track_activity_query_size`, `pg_stat_database`/`pg_stat_activity` access, datadog schema + usage grants, explain function, column-statistics function, config validation. Cascade-skips downstream probes when an upstream one fails | **yes — adapted** |
| `statements.py` | 632 | `pg_stat_statements` → normalised query metrics (legacy full load) | no (DBM backend needed) |
| `statements_v2.py` | 669 | incremental version: reads only changed rows, obfuscates SQL, ships samples | no |
| `statement_samples.py` | ~1400 | samples queries + runs `EXPLAIN` via a DB-side function (`datadog.explain_statement`) | no |
| `column_statistics.py` | 336 | per-column null/avg/distinct stats via a custom DB function | no |
| `schemas.py` | 410 | catalog of schemas/tables/indexes/columns | no |
| `role_collector.py` / `role_queries.py` | 495 / 422 | catalog of roles, memberships, per-role settings — **with explicit secret handling**: dotted settings (`pgrst.jwt_secret`) only collected for an allowlist of extensions | no, but the secrecy thinking is right |
| `data_observability.py` | 311 | data-quality monitoring product hook | no |
| `health.py` | 100 | `PostgresHealth(Health)` — health events with cooldown, `submit_diagnoses()` | **yes — shape** |
| `config.py` | 572 | `build_config() → (InstanceConfig, ValidationResult)`; features + errors + warnings + deprecations; `sanitize()` for logging | **yes** |
| `config_models/*` | — | pydantic models per feature block, defaults validated | **yes (idea)** |
| `metrics_cache.py` | 251 | version → metric set, cached; `clean_state()` on version change | **yes** |
| `connection_pool.py` | 369 | LRU pool per database, `statement_timeout` set per connection, token providers (AWS IAM/Azure), reuse-health checks | **yes (simplified)** |
| `cursor.py` | 56 | **SQL comment injection**: every query gets `/* service=datadog-agent */`, plus `/* DDIGNORE */` for queries that should not enter `pg_stat_statements` | **yes — cheap and valuable** |
| `encoding.py` | 17 | decode fallback chain for `SQL_ASCII` databases (truncated multibyte) | **yes — real-world crash we'd hit** |
| `filters.py` | 25 | regex include/exclude → SQL fragments for relations | later |
| `discovery.py` | 83 | database autodiscovery with `max_databases` + a warning when exceeded | **yes (idea)** |
| `version_utils.py` | 118 | semver parse tolerant of `12.3_TDE_1.0`, `12beta1`, **`11.22-rds.20241121`** | **yes — v4 breaks on RDS EOL formats** |
| `aws.py` / `azure.py` | 25 / 24 | IAM token / managed-identity auth | no (Site24x7 uses passwords) |
| `features.py` | 46 | `FeatureKey` enum: relation_metrics, query_samples, collect_settings, collect_schemas, collect_roles, query_activity, query_metrics, data_observability, collect_column_statistics | **yes — feature gating** |

### Scale of the metric surface
- **107** column-style metrics + **36** tuple-style = **~143 distinct metric names**, across **30 tag/label keys** (`slot_name`, `wal_app_name`, `wait_event`, `backend_type`, `relation`, `schema`, …).
- Coverage: `pg_stat_database` (+conflicts), bgwriter/checkpointer (v17 split), archiver, `pg_stat_replication` (LSN delays + write/flush/replay lags), `pg_stat_wal_receiver` (connected, msg ages, timeline), replication slots (xmin ages, restart delay) **+ `pg_stat_replication_slots` (PG14, spill/stream/total bytes per slot)**, `pg_stat_wal` (PG14, real WAL generation), `pg_stat_io` (PG16), `pg_stat_recovery_prefetch` (PG15), SLRU (PG13), wait events (grouped), sessions (PG14), snapshot/xip, vacuum/analyze/create-index/cluster progress, buffercache, checksums, subscriptions + subscription stats (PG15), locks-idle-in-txn ages, deadlocks, `pg_control_checkpoint` (timeline id + redo/checkpoint delay), WAL file metrics via SQL, function metrics, table counts per schema.
- **120 config options**, of which ~40 are product toggles (dbm, query_samples, query_metrics, data_observability, column_statistics, schemas, roles, settings…).

## 2. The single most important finding

**`grep -ri "patroni\|failover\|repmgr\|pg_auto_failover" *.py` → zero hits.**

Datadog's Postgres check has **no cluster awareness whatsoever**:
- no primary election, no role management, no topology, no node inventory
- standbys are identified only as a **metric tag** `replication_role:standby|master`
- `control.timeline_id` is collected, but as an untagged gauge on one endpoint — **never compared across nodes**, so it cannot detect split brain or a stale node
- no failover detection, no "when did this happen", no memory of a dead node
- one instance = one endpoint; a cluster is N unrelated instances; they are joined only in the SaaS backend by tags that happen to match

Every HA/failover question a Postgres operator actually asks is **outside** their integration. That is not a flaw in their execution — it's a product boundary. And it is precisely the space we occupy.

## 3. Five patterns worth copying (in priority order)

1. **Catalogue, not code.** `util.py` = 49 scope dicts; `metrics_cache.py` selects per version; `_query_scope` submits generically. Our version: one `METRICS` table → generates `units`, `tabs`, collector loop, self-test, README appendix.
2. **Diagnosis with remediation.** Every `DatabaseConfigurationError` has `description` + `remediation` + `docs_anchor`, used by both the runtime warning path and the pre-flight probes, with **cascade skipping** (don't tell the user to `CREATE EXTENSION` when `shared_preload_libraries` is empty). Our version: ~17 codes, each with fact + fix + runbook anchor, printed into `msg`.
3. **Capabilities gate queries.** Version constants + explicit `is_aurora` branch because Aurora raises `FeatureNotSupported` on `pg_stat_wal_receiver` every cycle — they detect it (extension-comment probe + `AURORA_VERSION()`), cache it, and skip the query.
4. **Robust version parsing.** Ours would fail on `11.22-rds.20241121` (RDS EOL) and `12.3_TDE_1.0`. Adopt their three-stage parse.
5. **Query hygiene.** `/* service=datadog-agent */` on every query + `/* DDIGNORE */` for queries that must not pollute `pg_stat_statements`; `SQL_ASCII` decode fallback; `statement_timeout` at connection level; `sanitize()` before logging config.

Honorable mentions: they explicitly avoid `pg_stat_user_tables` for table counts (sort cost) and query `pg_class` directly; they cap `max_relations` and `max_databases` **and warn when truncating**; they histogram their own collection time and warn when a pass exceeds the collection interval.

## 4. What we will not copy, and why

| Their approach | Why it doesn't fit us |
|---|---|
| 143 metrics × 30 tag dimensions | Site24x7 allows **200 metrics, 10 tables, 5 string columns/table**. Tags don't exist; dimensions must become metric names or table columns. |
| Requires DB-side objects (`datadog` schema, `explain_statement()`, column-statistics function, `pg_stat_statements`) | A Site24x7 plugin must work with a plain `GRANT pg_monitor`. Any setup step beyond one SQL script loses installs. |
| Query sampling + explain plans (DBM) | Needs a backend to normalise/store. A plugin emits one JSON blob. |
| 120 config options | Our user is a sysadmin with a cfg file. 8–10 options + presets, everything else derived. |
| Statelessness | Their down host simply stops reporting. Our differentiator is the opposite: last-seen, last-known-good clamp, dead-node history. |
| One endpoint per instance | Our unit of monitoring is the **cluster**. |

## 5. Where that leaves the architecture

Their shape, our nouns:

```
Datadog:  config(120) → version/aurora caps → scopes(49) → agent → SaaS backend → tags join instances
Ours:     config(10)  → capabilities        → METRICS    → JSON  → Site24x7         → one monitor per cluster
                         + truth model (primary/standbys/timeline/DCS)  ← they have nothing here
                         + health object (code/fact/hint)               ← they have it, but not HA-aware
                         + state file (rates, last-seen, clamp)         ← they have nothing here
```

Three things we add that they structurally cannot:
1. **Cluster truth**: primary election, timeline spread, split brain, sync-standby expectation vs `synchronous_standby_names`, cascading/delayed classification, DCS/quorum health, Patroni state per member.
2. **Failure narrative**: `Health(code, fact, quantified, context, hint)` + dead-node rows with `last_seen_ts` + primary clamp with `Primary_Data_Age_s`.
3. **Self-diagnosis on every cycle** (not on demand like `agent diagnose`): a ~15-check pre-flight whose results are metrics (`Collect_Warnings`, `Auth_Failure_Flag`, `PGSS_Available`) so a permission problem is visible in the site, not in a log file.

## 6. Concrete deltas this research forces into v5

1. `METRICS` catalogue table (single source of truth) — replaces hand-assigned metrics.
2. Diagnosis as a **first-class subsystem**: ~15 probes, ~17 codes, each with `remediation` text; results into `msg` + `Collect_Warnings`; cascade skipping.
3. **TLS**: `sslmode`, `sslrootcert`, `sslcert`, `sslkey`, `sslpassword`.
4. **Robust version parse** (RDS EOL, TDE, beta/rc) + **re-read every cycle** + rebuild metric set on change.
5. **Query tagging**: prefix every query `/* site24x7_pgcluster r<version> */` so DBAs can identify us and so we can be excluded from `pg_stat_statements`; `application_name=site24x7_pgcluster`.
6. **`SQL_ASCII` decode fallback** (our plugin would otherwise throw on the first non-UTF8 database).
7. **`pg_settings` snapshot per connection** → `autovacuum_freeze_max_age`, `wal_segment_size`, `max_wal_senders`, `synchronous_standby_names`, `track_io_timing`, `wal_level` → true percentages, true sync expectations.
8. **Truncation always reported** (`max_relations`/`max_databases` precedent) → our `Database_Stats` top-25-by-size + `WARN_TRUNCATED_ROWS`.
9. **Adopt their newer query coverage** where cheap: `pg_stat_wal` (PG14), `pg_stat_replication_slots` (PG14), `pg_stat_recovery_prefetch` (PG15), `pg_stat_io` (PG16), SLRU (PG13), subscription stats (PG15), `pg_control_checkpoint` (timeline + redo delay), vacuum/analyze/create-index progress (all gated by capability).
10. **Self-timing as metrics** (`Collect_Time_ms`, `Slowest_Scope`, `Queries_Run`) + `WARN_SLOW_SCOPE`.

## 7. Honest competitive read

- **Depth**: they win, permanently. 143 metrics, per-relation, per-role, per-schema, query sampling with explain plans. We cannot and should not chase it inside a 200-metric JSON plugin.
- **Cluster/HA awareness**: **we win by default — they have none.** No Patroni, no failover, no topology, no timeline comparison, no dead-node history.
- **Time-to-understand**: we win. One monitor, one health sentence with a fix, thresholds and a runbook shipped.
- **Install**: we win (one file + one SQL grant), at the cost of features we deliberately don't have.

The pitch to your lead, in one line: *Datadog monitors 143 things per instance and still can't tell you which node is primary or why your standby is 12 minutes behind. v5 monitors fewer things per instance and answers the cluster question in one sentence.*
