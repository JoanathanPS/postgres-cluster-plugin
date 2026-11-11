# v5 Architecture — the stable idea

This supersedes the "decisions" section of `SPEC-AND-PROMPT.md`. Read this first; treat it as the document of record for *how* the plugin is built.

---

## 1. What the Datadog file actually is

`PostgreSql(DatabaseCheck)` is an **orchestration shell**. It does almost no metric logic itself. The real design is in:

| Module | What it holds | Why it matters to us |
|---|---|---|
| `util.py` | every query as a *declarative scope*: `{name, query, metrics: {column: (metric_name, submit_fn)}, descriptors}` | metrics are **data**, not code |
| `version_utils.py` + `V9…V18` | version constants and a feature matrix | queries gated by *capability*, not by `if` spaghetti |
| `health.py` / `diagnose.py` | `PostgresHealth`, `HealthEvent`, `HealthStatus`, `run_diagnostics`, submitted with a 6 h cooldown | health is a **first-class object**, separate from metrics |
| `config.py` | `build_config()` → `(config, validation_result)` with errors + warnings | config problems are reported, not silently tolerated |
| `metrics_cache.py` | per-version metric definitions cached | version → metric set resolved once |
| `connection_pool.py` | `LRUConnectionPoolManager`, `statement_timeout` set at pool level, `TokenAwareConnection` | connection hygiene is centralised |

The lesson is not "copy Datadog's metric list". It's that Datadog draws hard lines we don't:

- **metrics are declared, then executed** (never hand-assigned one by one)
- **health/diagnosis is its own object** with codes and severities
- **capabilities gate queries** (version, Aurora, managed cloud, `pg_stat_statements`, superuser)
- **failures are classified and reported** with stable codes, never swallowed
- **the collector measures itself** (`dd.postgres.<scope>.time` histograms, warns when a collector exceeds `min_collection_interval`)

---

## 2. What we are missing today (concrete, from reading it)

| Gap in v4 | What DD does | Fix for v5 |
|---|---|---|
| **No TLS.** `psycopg2.connect(...)` with no `sslmode`/`sslrootcert` | `ssl_mode`, `ssl_cert`, `ssl_root_cert`, `ssl_key`, `ssl_password` all plumbed through `PostgresConnectionArgs` | **Add `sslmode`/`sslrootcert`/`sslcert`/`sslkey` + cfg keys. Blocking for most enterprise customers.** |
| **No `application_name`** — a DBA cannot find the monitor in `pg_stat_activity` | `application_name` set at connect | set `application_name='site24x7_pgcluster'`; also lets the DBA find/kill us |
| Metrics hand-assigned in ~60 `try/except` blocks | declarative scopes in `util.py` | one **metric catalogue** table (see §3) |
| Version read once at connect, never re-checked | `load_version()` **every run**, and `_clean_state()` if it changed | re-detect version per cycle; if it changed (failover to a different PG major) rebuild the metric set, don't emit garbage |
| Capability = cluster type only | gates on version **and** Aurora **and** `pg_stat_statements` availability | explicit capability object (§3) |
| `except Exception: pass` (~40 sites) | `record_warning(code, msg)` with a `DatabaseConfigurationError` enum, reported per run | warning **codes** (§5), surfaced as `Collect_Warnings` + `msg` |
| Timed-out node keeps its psycopg2 connection open (server backend leaks) | cancellation respected (`is_cancelled`), pool owns lifecycle | on deadline miss: `conn.cancel()` + `close()` in a `finally`; count it |
| Bloat-style heavy metrics unconditional | `collect_bloat_metrics` **off by default**, `max_relations` truncation with a debug log | heavy queries off by default, truncation always reported |
| Per-database rows unbounded | `ignore_databases`, cap + debug log | cap `Database_Stats` to top 25 **by size**, report the rest in `msg` |
| Assumed 60 s poll for rates | n/a (backend computes rates) | rate = `Δcounter / Δelapsed` using the **actual** state-file timestamp, so a 1-min or 5-min poll both work |
| `autovacuum_freeze_max_age` hardcoded implicitly | DD reads `pg_settings` for its tunables | read `autovacuum_freeze_max_age`, `wal_segment_size`, `max_wal_senders`, `synchronous_standby_names` per connection → correct `XID_Wraparound_Pct`, correct WAL sizes, correct sync-standby expectations |
| No self-cost metric | `dd.postgres.<scope>.time` histogram | `Collect_Time_ms` + `Slowest_Scope` (string) + `Queries_Run` |
| `_collect_internal` is ~600 lines | phases chained in `check_initializations` | explicit ordered **phase list** (§4), each timed |

Also adopted from DD's query set (this is the "breadth" worth having, all cheap):
`pg_control_checkpoint` (PG10+), `pg_stat_wal` (PG14+, real WAL generation instead of LSN maths), `pg_replication_slot_stats` (PG14+, per-slot lag attribution), `pg_stat_subscription_stats` (PG15+, conflict counters), `pg_stat_recovery_prefetch` (PG15+, standby I/O struggle), `pg_stat_io` (PG16+, per-backend-type I/O), SLRU stats (PG13+, xid/cache pressure), vacuum/analyze/index-build progress (long-running maintenance visibility).

---

## 3. The stable idea: four layers

```
        ┌──────────────────────────────────────────────────────────────┐
        │ 4. HEALTH / DIAGNOSIS OBJECT   (one per cycle)               │
        │    code · severity · fact · quantified · hint                │
        │    → status, msg, Diagnosis tab                              │
        └───────────────▲──────────────────────────────────────────────┘
                        │ reads
        ┌───────────────┴──────────────────────────────────────────────┐
        │ 3. TRUTH MODEL   (resolved once, immutable for the cycle)    │
        │    cluster_id (system_identifier), patroni scope, role,      │
        │    timeline, members[], primary[], standbys[], dcs health    │
        └───────────────▲──────────────────────────────────────────────┘
                        │ feeds
        ┌───────────────┴──────────────────────────────────────────────┐
        │ 2. CAPABILITY SET                                             │
        │    pg_version · role · is_standby · is_patroni · has_pgss ·  │
        │    has_pg_stat_io · is_managed_cloud · is_citus · ssl · is_a │
        └───────────────▲──────────────────────────────────────────────┘
                        │ selects
        ┌───────────────┴──────────────────────────────────────────────┐
        │ 1. METRIC CATALOGUE   (data, one table, ~120 entries)        │
        │    name · unit · tab · sql · type · requires · tier · hint    │
        └──────────────────────────────────────────────────────────────┘
```

### Layer 1 — the metric catalogue (`METRICS`)

One module-level list of plain dicts. Nothing else defines a metric.

```python
{"name": "Primary_XID_Wraparound_Pct", "unit": "%", "tab": "Primary",
 "type": float, "tier": 1, "requires": ("primary", "pg>=9.4"),
 "sql": "SELECT 100.0 * max(age(datfrozenxid)) / current_setting('autovacuum_freeze_max_age')::bigint "
        "FROM pg_database WHERE datallowin = true",
 "hint": ">=70 warn, >=95 critical"}
```

Derived automatically from that one table: `units`, `tabs`, the collector loop, the `--self-test` expectations, and the README appendix. Consequences:

- "declared in a tab but never emitted" becomes **impossible** — the tab list is generated from the catalogue, not hand-written next to it.
- 200-metric budget is auditable: `len(METRICS)` is asserted at import.
- adding a metric = adding one line, not editing four places.
- every metric *declares* its requirement, so capability gaps surface as a warning instead of a missing chart.

Catalogue entries are grouped into **scopes** (DD's word, good word): `cluster`, `primary`, `standby`, `replication`, `archiver`, `perf`, `workload`, `node`. A scope is executed together, timed together, and can fail without killing the cycle.

### Layer 2 — capabilities

```python
caps = {
  "pg": (16, 2), "role": "primary"|"standby"|"witness", "is_patroni": True,
  "has_pgss": False, "has_pg_stat_io": True, "has_slot_stats": True,
  "is_managed": False, "is_citus": False, "is_aurora": False,
  "wraparound_max_age": 200_000_000, "wal_segment_size": 16<<20,
  "sync_standby_names": "*", "synchronous_node_count": 1,
}
```
Requirements are predicates over this dict (`"pg>=14"`, `"primary"`, `"has_pgss"`, `"not aurora"`). One resolver, one place to add a new gate. Managed-cloud exceptions (Aurora raising `FeatureNotSupported` on `pg_stat_wal_receiver`) are handled by capability, not by catching an error every cycle.

### Layer 3 — the truth model

Resolved once per cycle from **Patroni REST first**, SQL second:

```
cluster_id     ← system_identifier (pg_control_system) — stable across renames/redeploys
cluster_name   ← Patroni scope / SHOW cluster_name / cfg
primary        ← exactly one node, or none (that's a finding, not a crash)
members[]      ← discovery ∪ state file (dead nodes retained)
timeline       ← per node; spread computed here
dcs_health     ← optional: etcd/ZooKeeper reachable? (a Patroni cluster can be "up" with no quorum)
```

Everything downstream reads this object. No metric query is allowed to re-derive role. This is what makes the Primary tab trustworthy during a failover: the truth model says *which* node is primary this cycle, so `Primary_*` metrics always come from one coherent source.

`cluster_id` from `system_identifier` is the detail I'd insist on: it survives hostname changes, container restarts and renames, so the state file (rates, last-known-good, last-seen) doesn't reset every time Docker hands out a new IP. Key the state on `cluster_id`, display `cluster_name`.

### Layer 4 — health/diagnosis object

```python
Health(code="primary_down", severity="critical",
       fact="no primary reachable",
       quantified="last seen pg1 07:12:44 IST, 14m ago",
       context="2/3 nodes up, timeline 4",
       hint="patronictl list; failover --candidate pg2")
```
→ renders to `status`, `msg`, Diagnosis tab, and `Health_Code` (int, alertable). One object, one precedence table, pure function, unit-tested.

---

## 4. Execution as phases (not one 600-line method)

```
detect_config → load_state → discover → connect(all nodes, parallel)
  → truth_model → capability_resolve(nodes) → probe(tiers) → rates
  → aggregate → health → emit(+validate) → save_state
```
Each phase: timed, wrapped, appends to `Collect_Warnings` on failure, never aborts the cycle unless it's a `config_error`. `Slowest_Scope` + `Collect_Time_ms` make the plugin's own cost a first-class metric — DD-style self-instrumentation, and it answers "why is my plugin monitor timing out" without a support ticket.

---

## 5. Warning codes (stable, documented, alertable)

```
WARN_PGSS_UNAVAILABLE      WARN_BLOAT_DISABLED        WARN_METRIC_GATED_PG_VERSION
WARN_TRUNCATED_ROWS        WARN_SLOW_SCOPE            WARN_SKIPPED_DEADLINE
WARN_DISCOVERY_CACHED      WARN_AURORA_UNSUPPORTED     WARN_PERMISSION_MISSING
ERR_AUTH_FAILURE           ERR_UNREACHABLE            ERR_POOLER_DETECTED
ERR_UNSUPPORTED_CLUSTER    ERR_CONFIG_INVALID         ERR_NO_PRIMARY
```
`Collect_Warnings` (int count) + `msg` carries up to 3 codes with counts. A customer can alarm on `Collect_Warnings > 0` and immediately know whether it's a permission problem or a real incident. This replaces 40 silent excepts.

---

## 6. What we deliberately do **not** copy

| DD does | We don't, because |
|---|---|
| ~100+ relation-level metrics, per-relation bloat, per-index | Site24x7 allows **200 metrics / 10 tables**, and has no query explorer to consume them. Depth without a UI is noise. |
| `pg_stat_statements` sampling as a product (DBM) | needs a backend to store normalised queries; a plugin can't. We surface top-5/1 by mean time, in `Wait_Events`/Workload only. |
| Per-instance configuration & cross-service tagging | we get one JSON blob per monitor, no tags. Hence **separate metric namespaces** (`Primary_*`) instead of DD's `replication_role:` tag. |
| No memory (a down host just stops reporting) | our customer explicitly wants dead-node history + last-known-good clamp. That's our differentiator, and it's why we ship a state file and DD doesn't. |
| Agent-side config validation raised as an exception | Site24x7 must always get JSON: every failure path returns `status: 0` + `msg`, exit 0. |

---

## 7. Where we can actually beat them

Not on depth — Datadog wins depth, always. On these three, which are what the customer in front of us cares about:

1. **One monitor = one whole cluster.** DD needs an instance per endpoint plus DBM for cross-instance views. We emit the whole topology (roles, timeline spread, who's dead, since when) in a single monitor, with the primary's health as the centre of gravity.
2. **It tells you what to do.** `Health(code, fact, quantified, hint)` with codes, runbook links and thresholds baked into the README. DD gives you charts and a query explorer; a 2-person team on Site24x7 needs the sentence.
3. **Install cost.** One file + one cfg section + one grant script. DD = agent + integration config + model of which of 120 options you need.

Honest limit to state out loud: we will never out-monitor Datadog on query-level analysis. We win on *time-to-understand*, which is a different product.

---

## 8. Net changes to the build spec

1. **Metric catalogue replaces hand-assigned metrics** — this is the core refactor, and the reason the file can be "so perfect".
2. **Add TLS** (`sslmode`, `sslrootcert`, `sslcert`, `sslkey`) + `application_name` — blocking gaps.
3. **Capability set** + per-metric `requires`; version re-detected every cycle, metric set rebuilt if it changes.
4. **Read `pg_settings`** for `autovacuum_freeze_max_age`, `wal_segment_size`, `max_wal_senders`, `synchronous_standby_names` → correct percentages instead of hardcoded ones.
5. **Warning codes** replace silent excepts; `Collect_Warnings` + codes in `msg`.
6. **Phases** with per-phase timing; `Collect_Time_ms`, `Slowest_Scope`, `Queries_Run` as metrics.
7. **Heavy queries (bloat) off by default**; truncation always reported.
8. **Deadline miss ⇒ cancel and close the connection** (no leaking backends).
9. **`Optional: DCS health`** — read Patroni `/cluster` `pause`/quorum when available, because "Patroni says everything is fine but etcd lost quorum" is a real, silent outage mode.
10. Keep everything already decided: cluster = 1 primary + 2 standbys typical (25 rows is plenty), per-node tables dropped, no rotation toggle (per-query cadence only where justified and always reported), no synthetic events, last-known-good clamp for the primary, Patroni-first.
