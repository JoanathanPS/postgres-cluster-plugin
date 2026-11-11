# PROMPT v5 — the build contract

Feed this whole file to the coding agent, with the `/research` folder beside it.
The prompt is the **operating contract**; `/research` is the **knowledge**. Where they
disagree, the research wins and the agent says so.

---

## 0. Read this first — the agent's reading list

Read these files in order, fully, before writing a line of code. Do not skim; several
contain numbers (limits, row counts, thresholds) that are assertions you must honour.

| File | What it settles |
|---|---|
| `/research/SPEC-AND-PROMPT.md` | what the product is, tabs, tables, enums, decisions already made |
| `/research/ARCHITECTURE-v3.md` | the five nouns: catalogue → capabilities → truth model → health object → emitter |
| `/research/DATADOG-TEARDOWN.md` | what to copy (catalogue, remediation text, query hygiene) and what not (120 options, statelessness) |
| `/research/COMPETITIVE-LANDSCAPE.md` | per-metric cadence + presets, error codes, the gap list we are attacking |
| `/research/TESTING.md` | the six test layers, the chaos table, the definition of done |
| `/research/STATE-FILE.md` | the state-file contract, and why `os.access` is banned |
| `/harness/state_store.py` | reference implementation of the state layer — **port it into the plugin**, do not import it |
| `/harness/s247_validate.py` | the platform-limit validator you must stay green against |
| `/harness/fake_pg.py` | scenario harness; add a scenario for every health code you implement |
| `/harness/test_state_store.py` | the state layer's own tests; they must still pass after porting |

If any instruction here contradicts a `/research` fact, follow the fact and flag the
conflict in your final summary.

---

## 1. Deliverables

1. `postgres_cluster.py` — **exactly one file**, Python 3.9+, stdlib + `psycopg2` only.
   Single file is a Site24x7 hard requirement: the agent executes one script per folder.
   Therefore the state layer from `harness/state_store.py` is **inlined** as a section of
   this file, not imported.
2. `postgres_cluster.cfg` — the agent's config, `[global_configurations]` +
   `[postgres_cluster]` + one commented second section showing a second monitor.
3. `README.md` — install, grant SQL, enum sheet, threshold table, runbook.
4. `tests/test_plugin.py` — unit tests that import the plugin file and exercise the pure
   functions (no DB). This is the `--self-test` content, callable from CI too.

Nothing else ships. The harness stays out of the deliverable.

---

## 2. Absolute platform limits (the plugin must enforce them on itself)

From Site24x7's plugin documentation — not negotiable, not approximate:

| Rule | Value |
|---|---|
| child tables | **≤ 10** |
| columns per table | **≤ 15** |
| rows per table | **≤ 25** |
| string columns per table | **≤ 5, and `name` counts as one** |
| `name` length | **≤ 520 chars** |
| any other string cell | **≤ 100 chars** |
| metrics (numeric or string, top level) | **≤ 200** |
| script budget | 50 s default; target ≤ 8 s at 3 nodes, ≤ 15 s at 25 |
| reserved keys — never reuse as metric names | `plugin_version`, `heartbeat_required`, `status`, `msg`, `units`, `tabs`, `s4z7config` |

Consequences you must design for, not discover later:

- **States are integers.** With 5 string columns including `name`, a per-node row can
  afford at most 4 more strings. Role, sync state, Patroni state, risk, health must all
  be ints. Document every enum in the README; operators threshold on ints.
- **25 rows is plenty.** Real clusters are 1 primary + 2 standbys; 5–7 nodes is large.
  Order rows deterministically (primary → DOWN → WARN → alias). Only if a cluster has
  more than 25 monitored nodes emit one final `<n> more nodes` row and set
  `Nodes_Omitted`. Do not build a rollup scheme.
- **A dead node keeps its row forever**, fed from the state file, with `last_seen_ts`
  and a `status_reason`. This is a shipped feature, not a nicety.
- **Every metric in a tab must be emitted, and every emitted metric must be in exactly
  one tab and in `units`.** The validator enforces both directions. A tab entry with no
  emitted metric is the #1 silent bug in this platform.

---

## 3. The metric catalogue is the contract

Define exactly one module-level structure:

```python
METRICS = [
    {"name": "Primary_XID_Wraparound_Pct", "unit": "%", "tab": "Primary",
     "type": float, "interval": 60,
     "requires": ("primary", "pg>=9.4", "!aurora"),
     "sql": "SELECT 100.0 * max(age(datfrozenxid)) / "
            "current_setting('autovacuum_freeze_max_age')::bigint "
            "FROM pg_database WHERE datallowconn",
     "hint": "warn >= 70, critical >= 95"},
    ...
]
```

Rules:

- `units`, `tabs` and the collector loop are **generated** from `METRICS`. Never
  hand-maintain a second list; that is how drift starts.
- `len(METRICS) ≤ 200` is asserted at import.
- **Never invent a metric name that is not in the table.** If a metric can't be
  produced on a given server, omit it and report a warning code — do not emit 0.
- Every entry needs `unit`, `tab`, `type`, `sql`, `requires`, `interval`, `hint`.
- `requires` is a tuple of predicates over the capability dict (§4). If you cannot
  verify a SQL against PostgreSQL 13–18, add it with the tightest `requires` you can
  justify **and** a runtime guard; never guess.
- Runtime gating beats static version tables: wrap every catalog read in
  `to_regclass()` / `has_table_privilege()` / `has_column_privilege()` so an
  under-privileged monitor can never cause a server-side error.

Presets (from the competitive research): `minimal | standard | exhaustive | patroni |
managed | debug`, each a `{metric_name: seconds}` map, with the default `standard`.
A cycle counter in the state file decides whether a metric is due. This is the *only*
cadence mechanism — no hidden rotation.

---

## 4. Capabilities, resolved once per node per cycle

```python
caps = {
  "pg": (16, 2),            # parsed tolerantly: "11.22-rds.20241121", "12.3_TDE_1.0", "12beta1"
  "role": "primary" | "standby" | "witness",
  "is_patroni": bool, "patroni_state": int, "patroni_scope": str,
  "provider": "self" | "rds" | "aurora" | "cloudsql" | "azure" | "neon" | "supabase" | "crunchy" | "heroku",
  "has_pgss": bool, "has_pg_stat_io": bool, "has_slot_stats": bool, "has_recovery_prefetch": bool,
  "autovacuum_freeze_max_age": int, "wal_segment_size": int,
  "max_connections": int, "max_wal_senders": int,
  "synchronous_standby_names": str, "patroni_sync_node_count": int,
  "recovery_min_apply_delay": int, "is_delayed": bool, "is_cascading": bool,
  "track_io_timing": str, "wal_level": str, "archive_mode": str,
}
```

Read `pg_settings` for the GUCs once per connection; never hardcode
`autovacuum_freeze_max_age` (2e8) or assume 16 MB WAL segments.

**Version parsing** must tolerate real-world strings: `16.2`, `10.0`, `12.3_TDE_1.0`,
`11.22-rds.20241121`, `12beta1`, `17devel`. A parse failure is a warning code, not a crash.

**Provider detection** suppresses queries that break per provider (Aurora raises
`FeatureNotSupported` on `pg_stat_wal_receiver` every cycle; RDS and Cloud SQL restrict
several functions). Detect once, cache in state, gate with `requires`.

---

## 5. The truth model (this is our differentiator — do not simplify it away)

Resolved once per cycle, Patroni REST first, SQL second:

```
cluster_id   = system_identifier (pg_control_system)   # stable across renames/IPs
cluster_name = Patroni scope | SHOW cluster_name | cfg
primary      = exactly one node, or none (that is a finding, not a crash)
members[]    = discovery ∪ state-file members (dead nodes retained)
timeline     = per node; spread = max - min
dcs          = Patroni /cluster pause flag + quorum reachability, when available
```

Rules:
- No metric query may re-derive role. Everything reads the truth model.
- `Primary_*` metrics always come from the node the truth model says is primary, so a
  failover mid-cycle cannot mix two nodes' numbers.
- Distinguish roles: primary, standby (sync/async), **cascading**, **delayed**
  (`recovery_min_apply_delay > 0` — high lag is expected, must not alert), witness,
  standby-leader, offline.
- Timeline is the failover counter. A timeline mismatch between nodes is a first-class
  alert (`Timeline_Spread`, `Timeline_Mismatch_Flag`).

---

## 6. Health object, error codes, and `msg`

```python
Health(code="primary_down", severity="critical",
       fact="no primary reachable",
       quantified="last seen pg1 07:12:44 UTC, 14m ago",
       context="2/3 nodes up, timeline 4",
       hint="patronictl list; failover --candidate pg2")
```

Precedence (document it in the README, implement exactly this order):

- **CRITICAL** — no primary · split brain (>1 primary, not multi-master/Citus) · 0 of N
  expected standbys streaming · sync standbys below expectation · slot `wal_status=lost`
  or retained > critical · XID wraparound ≥ 95 % · primary down with no failover candidate.
- **WARN** — any node down · lag > threshold or backlog > threshold · inactive slot ·
  slot retained > warn · timeline mismatch · failover within window · XID ≥ 70 % ·
  connections ≥ 90 % · archive failures rising · stale stats · prepared transactions
  older than N.
- **Delayed standbys are excluded from lag alerts.**

`msg` is the only sentence a customer reads on the monitor card. One line, ≤ 180 chars:

```
CRITICAL primary_down: no primary reachable (last seen pg1 07:12:44 UTC, 14m ago) | 2/3 nodes up | hint: patronictl list
```

Error taxonomy — every failure is classified, none swallowed:
`config_error` · `auth_failure` (sets `Auth_Failure_Flag`; **must never read as
"primary down"**) · `unreachable` · `metric_unavailable` · `pooler_detected` ·
`unsupported_cluster` · `budget_exceeded` · plus the `WARN_*` codes from STATE-FILE.md.

No bare `except`. Pattern is always: catch → classify → append a note with a code →
continue.

---

## 7. The primary-down contract (headline feature)

State file, inlined from `harness/state_store.py` with these properties preserved:

- location ladder: cfg `state_dir` → plugin dir → `/var/lib/site24x7/…` or
  `%PROGRAMDATA%\Site24x7\…` → temp dir **as last resort only**
- **never `os.access`** — probe by writing, delete the probe file
- key the file by `machine_id + cluster identity + plugin dir`; store the key inside
  the JSON and refuse a mismatched file
- atomic write: `mkstemp` in the same dir → `flush` → `fsync` → close → `os.replace`
- corrupt / oversize / foreign / wrong-schema → `{}` + a code, never an exception
- prune node entries unseen for 7 days
- emit `State_File`, `State_Persistent`, `State_Age_s`, `State_IO_Errors`,
  `State_Reason` every cycle

While the primary is unreachable:
- keep emitting last-known-good Primary-tab values, clamped, so charts don't flatline
- `Primary_Up=0`, `Primary_Data_Age_s`, `Primary_Data_Stale` (1 past TTL, default
  1800 s), `Primary_Data_Source` ∈ `live|clamped|none`
- past the TTL emit the freshness trio only
- **never clamp** anything that decides alert state
- on a cold start (no state), emit `Rate_Warmup_Flag=1` and no rates — never a spike
  computed against a missing baseline

---

## 8. Tabs (exact keys and order) and tables (exact columns)

Tabs: `Diagnosis`(1) · `Primary`(2) · `Nodes`(3) · `Replication`(4) ·
`Health & Capacity`(5) · `Performance`(6) · `WAL & Archiver`(7) · `Workload`(8).

Table shapes are specified in `/research/SPEC-AND-PROMPT.md` §4 and
`/research/COMPETITIVE-LANDSCAPE.md` §6. Implement those exactly; keep to 7 tables so
three slots stay free. Every table needs `name` and per-row `status`; at most 4 further
string columns.

**Build the tables last.** Get the metrics + validator green first; tables are the
surface most likely to break a limit, and they are pure formatting over data you
already have.

---

## 9. Build order — one gate at a time, run the command, paste the output

Stop at the end of each step and show the result. Do not proceed on an unverified step;
a fast model that "continues anyway" produces a 2,000-line file that fails at the end.

| Step | What to write | Gate command | Pass condition |
|---|---|---|---|
| 0 | skeleton: constants, enums, `METRICS` with 10 entries, `units`/`tabs` generated, `validate_output()` | `python3 postgres_cluster.py --self-test` | exits 0; asserts catalogue consistency |
| 1 | health engine + enums + version parsing + address-map/alias helpers | `python3 tests/test_plugin.py` | all pure-function tests pass |
| 2 | emitter: build payload from `METRICS` + capability stubs, no DB | `python3 harness/fake_pg.py --run healthy-3node --plugin postgres_cluster.py --snapshot out.json && python3 harness/s247_validate.py out.json` | **0 errors** |
| 3 | real connection layer for one node; run against the Docker PG | `python3 postgres_cluster.py --nodes localhost:5432 --json-out out.json && python3 harness/s247_validate.py out.json` | 0 errors, `Collect_Warnings=0` |
| 4 | Patroni REST + discovery + 3-node fan-out | same, against the 3-node rig | 3 rows in `Cluster_Nodes`, correct roles, ≤ 8 s |
| 5 | state file + clamp + rates | paste primary mid-run, re-run | `Primary_Data_Source=clamped`, age rises, no crash, status still 1 |
| 6 | tables (`Cluster_Nodes`, `Node_Snapshot`, `Replication_*`, `Database_Stats`, `Wait_Events`, `Topology`) | validator | ≤ 10 tables, ≤ 15 cols, ≤ 5 strings, ≤ 25 rows each |
| 7 | cfg + README + grant SQL + threshold table + runbook | manual read | every error code in the README has a remediation string in the catalogue |
| 8 | hardening: TLS, `application_name`, query comment tag, `SQL_ASCII` decode, Windows-safe paths, stdout purity | `python3 -c "import json;json.load(open('out.json'))"` after a forced failure | still one JSON object on stdout |

Every new health code added in step 1 or 6 gets a scenario in `harness/fake_pg.py` in
the same change.

---

## 10. Hard "don'ts" — each one is a known failure of this kind of code

- No `os.access` for writability. No `fcntl`, no `fork`, no `signal` handlers, no
  `os.geteuid`-dependent logic.
- No printing anything to stdout except the single final JSON object. Library warnings
  and tracebacks go to stderr or are captured into `msg`.
- No `except Exception: pass`. No bare `except:`.
- No `sys.exit()` before `print`; `sys.stdout.flush()` then `os._exit(0)` as in v4.
- No passwords, DSNs or conninfo strings in any metric, table cell, log line or `msg`.
  Scrub before truncating to 100 chars, not after.
- No NaN/Infinity in JSON (`float('nan')` is not valid JSON and the agent will drop the
  payload). Guard every division; cast floats to 2 dp.
- No negative rates. Counter reset (restart) ⇒ 0 for that cycle + a note.
- No timestamps without a timezone. `last_seen_ts` is ISO-8601 UTC with an explicit
  offset, because the Site24x7 console is not in the operator's timezone.
- No assumption that the monitored server's clock matches the agent's. Clamp negative
  ages to 0.
- No metric whose SQL you have not run at least once on a real server of the version
  you claim to support. Gate it instead.
- No placeholder `TODO`, no `pass  # implement later`, no fictional function names.
  If something cannot be done, say so in `msg` and in the final summary.

---

## 11. When the agent must stop and ask instead of guessing

1. The SQL for a metric behaves differently than `/research` says for PG 13–18.
2. A Site24x7 limit at §2 appears to conflict with a table shape required by `/research`.
3. A real server returns a column or view that is not in the research (new PG version,
   extension, fork).
4. The chaos table in `/research/TESTING.md` §5 has a row whose expected behaviour the
   design cannot produce.
5. Anything that would require a second file, a daemon, a DB-side function, or a grant
   beyond `pg_monitor`.

Report the first unknown; do not invent a workaround that hides it.

---

## 12. Final summary the agent must produce

- metric count vs the 200 limit, tables/columns/strings used vs the limits
- every health code, and the scenario name that exercises it
- every metric that is capability-gated, and on what
- the exact commands run, with their pass/fail
- anything still unverified, in a list, with the reason

A deliverable with an honest "unverified" list is accepted. A deliverable claiming
everything works, without the commands and their output, is rejected.
