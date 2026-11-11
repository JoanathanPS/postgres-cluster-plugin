# How the industry tests PostgreSQL collectors — and the tester/builder we need

Research date 2026-11-11. All numbers measured from the repos (source trees, workflow files, issue trackers). Companion tools already built: `harness/s247_validate.py`, `harness/fake_pg.py`.

---

## 1. Measured: how much do they actually test?

| Project | Source LOC | Test LOC | Ratio | Test mechanism |
|---|---|---|---|---|
| `prometheus-community/postgres_exporter` | 20,475 | **10,263** (61 files) | **50 %** | Go unit tests + `//go:build integration` tag + real `postgres` service container |
| `cybertec-postgresql/pgwatch` | 28,019 | **17,051** (55 files) | **61 %** | Go unit + YAML-catalogue validation (`metrics_yaml_test.go`, `yaml_test.go`) |
| `percona/pmm` | 614,721 (incl. TS frontend) | **127,147** (429 files) | 21 % | Go unit + `api-tests/` + per-PG-version matrix |
| `newrelic/nri-postgresql` | 6,973 | 2,827 (19 files) | 41 % | Go tests + `tests/docker-compose*.yml` per scenario (pgbouncer, performance) + `testdata/` |
| `dalibo/temboard` | 30,216 | 4,572 (36 files) | 15 % | pytest (`ui/tests`, `agent/tests`, `toolkit/tests`) + `tests/test_60_alerting.py` |
| `OPMDG/check_pgactivity` | 1 script, 53 services | **6,111** (51 TAP files) | ~high | **TAP, one `.t` file per service**, spun up a real cluster via `PostgresNode` |
| `pganalyze/collector` | ~? (tree includes `vendor/`) | 11,913 (39 files) | — | `integration_test/` with **`Dockerfile.test-postgres` per PG version** and **`.expected` golden outputs** (`citus.expected`, `guided-setup.*.expected`) |
| `DataDog/integrations-core@postgres` | 8,252 | `test_unit.py` 634 + `common.py` 541 + `conftest.py` 193 | — | pytest `@pytest.mark.unit` vs integration, `aggregator` assertions, `mock.patch`, `parametrize`; **`metadata.csv` (245 rows) is machine-validated** |
| `netdata/netdata@go.d/postgres` | ~4,700 in module | `testdata/` snapshot dirs | — | Go golden-file tests + `config_schema.json` + `metadata.yaml` |
| `rapidloop/pgmetrics` | 9,989 | **0** | **0 %** | none |
| **`site24x7/plugins@postgres`** (our baseline) | 313 | **0** | **0 %** | none |

**Two things to take from the table.** (a) Serious collectors spend 40–60 % of their code on tests — that is the industry norm we're below. (b) The two zero-test projects (`pgmetrics`, the official Site24x7 plugin) are exactly the two that sell on "it runs and prints something". Reliability is not the market's default, which means it is available as a differentiator.

### Version matrices (from the CI files)
- `postgres_exporter/.github/workflows/integration.yml`: `postgres_version: [13.22, 14.19, 15.14, 16.10, 17.6, 18.1]`, real service container, `DATA_SOURCE_NAME` pointing at it, integration build tag.
- `pmm`: matrix through **18**.
- `pganalyze`: `Dockerfile.test-postgres`, `Dockerfile.test-systemd`, plus per-provider expectations.
- `check_pgactivity`: TAP harness creates real nodes (`t/lib/PostgresNode.pm`), so every service is exercised against a live server.

---

## 2. The five test patterns worth copying

1. **Test-per-feature mapping.** `check_pgactivity` has one `.t` per service (`01-archiver.t`, `01-hot_standby_delta.t`, `01-replication_slots.t`…). If you can name the service, you can name the test file. → We need one scenario per health code and per table, named identically.
2. **Golden/snapshot output.** `pganalyze` keeps `.expected` files per scenario and diffs real output against them. Datadog keeps `metadata.csv` (the full metric surface) and asserts against it. → Our validator's `--expect` diff mode is the plugin-sized version of this; snapshots are the integration-sized version.
3. **Real server, multiple versions, real grants.** Not "does the SQL parse" but "does it return rows on 13 and on 18, as the monotoring role". Most plugin bugs live in the gap between those.
4. **Integration tag separate from unit.** `//go:build integration` / `@pytest.mark.unit` — fast tests always, slow tests on demand. → Our `--self-test` (2 s, no DB) vs scenario/integration runs (minutes).
5. **Self-validating metadata.** Datadog validates `metadata.csv` in CI, Netdata validates `metadata.yaml` against a schema. → Our catalogue must be validated at import: `len(METRICS) ≤ 200`, every entry has unit+tab+sql+requires.

---

## 3. The issues they actually hit (evidence, not speculation)

Real issue titles, pulled from the trackers:

**postgres_exporter** (24 results for "duplicate metrics"):
- *"auto-discover-databases duplicated metrics should tell the user to add `master: true`"* and *"autoDiscoverDatabases:true gives error 500 (collected metric … was collected before with the same name and label values)"* → **dimensional collision**: the same metric name scraped twice with identical labels kills the export. Our version of this is the 5-string-column problem and duplicate `name` values in a table — both now hard errors in our validator.
- *"Legacy collector can exceed `--collection-timeout` when PostgreSQL stops responding"* → **a hung server breaks the deadline**, exactly why we need per-node deadlines and cancel+close.
- *"`/probe` accumulates connections when database replies are lost"* → **connection leak on failure**. Must be tested: count backends from our `application_name` before/after a chaos run.
- *"loggableDSN prints a key=value password that contains `=`"* → **secret leaked into logs by a redaction bug**. Ours: never log the cfg, scrub conninfo before it enters a string column.

**pgwatch:**
- *"Single faulty host with postgres-continuous-discovery breaks metrics collection for all hosts"* → **one bad node takes down the fleet**. Our fan-out must isolate per-node failures; a test scenario exists for this now (`slow-node`, `privilege-gap`).
- *"Cannot fetch psutils_mem metric"* → an optional metric silently missing, discovered by a user.

**Categories that recur across all of them** (each becomes a test in our matrix): permission gaps (`pg_monitor` missing, `pg_stat_statements` not readable) · version-specific views (`pg_stat_io` 16+, `pg_stat_checkpointer` 17+, `recovery_prefetch` 15+) · managed-cloud exceptions (Aurora `FeatureNotSupported`) · silent truncation · counter resets on restart · metric rename breaking dashboards · config drift (agent re-encrypts password, plugin reads the old key) · `SQL_ASCII` decoding · timezone/DST in "last seen" · **identity drift after failover** (Datadog keys on host:port, so a node that was a standby becomes primary and its historical graphs silently change meaning — we avoid this with `cluster_id` + role separation, and we must *test* that names stay stable).

**The one that matters most for us and nobody can test cheaply:** failover. Every tool above either doesn't model it or tests it with a bespoke script. It's the highest-value event in a Postgres deployment and the least covered.

---

## 4. Why our case is harder than all of theirs

| Their situation | Ours |
|---|---|
| Compiled/typed code catches shape errors | Python: a typo in a tab list is a silent empty chart |
| CI runs the collector | The **Site24x7 agent** runs it, remotely, with a 50 s budget |
| Container service they control | Customer's network, firewall, NAT, HAProxy, managed cloud |
| Rich test frameworks, fakes, assertions | No test framework, no assertion channel: **stdout JSON is the only output** |
| 143 metrics with tags | **200 metrics, 10 tables, 25 rows, 5 string columns** — every dimension must be packed or dropped |
| One OS | **Linux + Windows agents** (no `fcntl`, no `fork`, path separators) |
| Errors visible in logs | A failure mode is "the metric quietly stops appearing" |

But there is a compensating fact, and it is our whole quality strategy: **our surface is ~10× smaller than theirs.** Datadog cannot exhaustively test 143 metrics × 30 tag dimensions. We can exhaustively test ~120 metrics, 7 tables, 8 tabs, ~17 health codes and 6 error classes. Small enough that "every branch has a test" is achievable rather than aspirational.

---

## 5. The tester + builder we need — six layers

```
L0  --self-test         pure functions, no DB, <2 s, runs on Windows too
L1  payload validator   platform-limit compliance (built)
L2  fake cluster        scenario → payload, golden snapshots (built)
L3  real clusters       PG 13…18 + Patroni 3-node in Docker
L4  chaos               kill the primary, revoke grants, fill WAL, break the network
L5  the real agent      packaging, cfg encryption, non-root, stdout purity, Windows
L6  soak                24–72 h, leak and drift detection
```

### L0 — `--self-test` inside the plugin
Pure functions only: health engine (every rule + precedence + every enum value), discovery/alias/address-map parsing, version parsing (`11.22-rds.20241121`, `12.3_TDE_1.0`, `12beta1`), row-budget and truncation logic, rate maths incl. counter reset, `validate_output()`, catalogue self-consistency (`units ⊇ tabs`, `tabs ∩ emitted`). No DB, no network, no filesystem. Target < 2 s so it can run on every commit and on Windows.

### L1 — `harness/s247_validate.py` (built, working)
Takes the JSON the plugin emits and checks every documented Site24x7 rule: ≤10 tables · ≤15 columns · ≤25 rows · ≤5 string columns (name included) · `name` ≤ 520 · other strings ≤ 100 · ≤200 metrics · at least one numeric parent · `status` ∈ {0,1} · row `status` ints · **tab metric never emitted** (the silent bug) · metric in no tab · unit orphans both directions · ragged rows · duplicate row names · NaN · long `msg` · tab order. Plus **`--expect baseline.json` diff mode**, which proves a change removed no metric/column/table and fails if the metric surface changed without a `plugin_version` bump.

Its own `--selftest` passes 9/9 — a test for the tester, because an untested validator gives false confidence.

### L2 — `harness/fake_pg.py` (built, working)
`psycopg2` is replaced by a fake module; statements are matched by substring per node; scenarios script rows, delays, and raised errors. Eight scenarios included:

`healthy-3node` · `primary-down` · `lagging-standby` (12 min, 400 MB) · `privilege-gap` (one view denied, rest fine) · `slow-node` (deadline blowout) · `split-brain` (two primaries, different timelines) · `no-pgss` (extension absent) · `short-strings` (over-long values)

It records **UNMATCHED** statements — meaning the collector asked for something the scenario doesn't model. That list is a free coverage report of your own plugin's query surface.

Demonstrated run (against a 40-line stand-in collector, since v5 doesn't exist yet):
```
$ python3 fake_pg.py --run healthy-3node --plugin _sample_plugin.py --snapshot sample_out.json
$ python3 s247_validate.py sample_out.json
ERROR [TAB_METRIC_NEVER_EMITTED] Primary_Typo: declared in tab Primary but absent from the payload
warning [TAB_METRIC_NO_UNIT] Primary_Typo: no entry in units{}
verdict: FAIL
```
That is the loop: **scenario → payload → platform rules → verdict**, in about a second, with no cluster.

### L3 — real clusters (once per release, ~30 min)
Docker: PG 13.22 / 14.19 / 15.14 / 16.10 / 17.6 / 18.1 single-node (mirror postgres_exporter's matrix), then a 3-node Patroni + etcd cluster, a repmgr cluster, and one pg_auto_failover cluster. Assertions per run:
- `status == 1`, `Collect_Warnings == 0` on a healthy cluster
- **every catalogue metric appears at least once** (auto-generated assertion from `METRICS`)
- no `pg_stat_activity` leak from our `application_name` after the run
- collect wall time recorded per version, with a **regression budget** (p95 ≤ 8 s at 3 nodes; fail the build if it grows >30 %)
- the emitted JSON passes L1 with zero errors

### L4 — chaos (the part nobody else does well)
Each fault is a script with a *documented expected outcome*, so "did the plugin behave?" is a comparison, not an opinion:

| Injection | Expected result |
|---|---|
| `docker pause` the primary | `Primary_Up=0`, clamped values + `Primary_Data_Age_s` rising, `Primary_Data_Stale=1` after TTL, code `primary_down`, **no crash, status stays 1** (monitor up, cluster degraded) |
| `patronictl failover` | `Failover_Age_s` small, `Primary_Timeline` +1, timeline spread 0, `Last_Failover_To` = new primary |
| `REVOKE` on `pg_stat_replication` mid-run | `Collect_Warnings ≥ 1` with code `WARN_PERMISSION_MISSING`, replication metrics absent **but the rest of the payload intact** |
| `recovery_min_apply_delay=10min` on a standby | role `6` (delayed), lag high, **no lag alert** |
| `synchronous_standby_names` changed | `Sync_Standby_Expected` vs actual mismatch raised |
| fill `pg_wal` | slot/`PGWAL_Used_Pct` warnings, correct severity order |
| `tc` blackhole one node | that node down with `unreachable`, collection deadline respected, other nodes complete |
| `pg_sleep` in a monitoring-visible session | `Primary_Longest_Txn_s` / blocked locks report it |
| restart a node mid-collection | counter reset → rates 0 for one cycle + note, **no negative rates, no division by zero** |
| wrong password | `Auth_Failure_Flag=1`, `status=0`, msg says config problem — **must not read as "primary down"** |
| kill the agent's own connection (`pg_terminate_backend`) | reconnect once, then report; no infinite retry |

Each row is a scenario name in the harness, so the L2 fake and the L4 real run share one vocabulary.

### L5 — the actual Site24x7 agent (the layer everyone forgets)
- **Packaging**: directory name must equal script name (`plugins/postgres_cluster/postgres_cluster.py`). Wrong = never discovered.
- **stdout purity**: the agent parses stdout as the payload. One stray `print`, one library warning, one traceback on stdout = payload corruption. Test: run the plugin with a deliberately broken node and assert stdout is exactly one JSON object.
- **cfg handling**: agent rewrites `password` → `encrypted.password`; plugin must accept both forms and must not crash when `global_configurations.keys_to_encrypt` adds `username`.
- **user and permissions**: plugin runs as `site24x7` (non-root). Prove the state dir is writable, the state file is created and readable, and the plugin degrades gracefully when it isn't (read-only FS is a real case). **This is the open question blocking the primary-clamp design** — one throwaway plugin printing `os.getuid()`, `os.access(dir, W_OK)` settles it in the Docker agent.
- **timeout**: agent default 50 s. Test the plugin under a forced 45 s ceiling to ensure a partial cycle still emits valid JSON.
- **registration**: first run registers the monitor; `plugin_version` bump creates a new template (validator enforces the bump).
- **Windows agent**: path handling, no `fcntl`/`fork`, UTF-8 explicit, `os._exit` after flush.

### L6 — soak
72 h at a 60 s poll against a 3-node Patroni cluster under constant write load, asserting: flat memory in the agent, no backend leak (`count(*) from pg_stat_activity where application_name='site24x7_pgcluster'` ≈ 1×nodes), bounded state file (old node entries age out), no rate drift, no duplicate metric accumulation across `plugin_version` bumps.

---

## 6. Definition of done ("sufficient" — an actual checklist)

1. `--self-test` green on **Linux and Windows**, < 2 s.
2. Every emitted payload passes L1 with **0 errors**; every warning has a written reason.
3. Every one of the ~17 health codes is reachable by ≥1 named scenario (list checked in CI).
4. Every catalogue metric is emitted in ≥1 real-cluster run, auto-generated assertion.
5. Zero **UNMATCHED** statements in the fake-cluster coverage report.
6. Chaos table: 11 injections → 11 documented behaviours, all passing.
7. Collect time p95 ≤ 8 s at 3 nodes, ≤ 15 s at 25 nodes; no per-node probe > 3 s.
8. Agent-level pass on Linux **and** Windows; stdout purity test green.
9. Golden snapshots committed and diff-reviewed for every change; `plugin_version` bumped whenever the surface changes (enforced, not remembered).
10. README ships the threshold table + runbook; every error code there has a remediation string in the catalogue.

---

## 7. What this means for the Antigravity workflow

The division of labour is the point:

- **The prompt builds the plugin once.** Claude/Antigravity can produce a 2,000-line `postgres_cluster.py` in one shot. It cannot produce *evidence* that it behaves under failover, missing grants, a hung server, or a Windows agent.
- **The harness builds the evidence, forever.** ~600 lines of tooling we own, runnable in seconds, that survives every regeneration of the plugin. That is the asset.
- **Review gates** (put these in the prompt as acceptance criteria, not suggestions):
  - no bare `except`; every failure classified into a code
  - every new metric added to `METRICS` (which implies tab + unit)
  - every new health code gets a scenario in `fake_pg.py` **in the same change**
  - `s247_validate.py` clean, `--expect` diff reviewed
  - `plugin_version` bumped

The honest summary for your lead: any of us can get a `.py` from a prompt. What nobody can prompt their way out of is the eleven-row chaos table in §5 and the agent-level checks in L5 — and those are exactly where every competitor in §3 got burned.
