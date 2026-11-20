# Site24x7 PostgreSQL Cluster Plugin — Handoff

Everything known about this project as of **2026-11-20**, written for a reader with
zero context: your future self on a new account, or a fresh AI session.

Read sections 1, 2 and 8 first. Section 8 is the one thing that can actually hurt you.

---

## 1. What this is, and the premise that went wrong

**The task:** build a Site24x7 plugin that monitors a whole PostgreSQL cluster as one
monitor — which node is primary, which are standbys, replication health.

**What the TL said:** get the node details — primary/secondary — *"from HAProxy."*

**What that was misread as:** HAProxy must be the discovery *mechanism*.
**What it almost certainly meant:** our cluster happens to sit behind HAProxy.

That single misread drove an architecture where HAProxy was the primary source of
truth, and it is the root cause of most of the scope problem below. The clarifying
question that was never asked, and would have saved thousands of lines:

> *"When you say get it from HAProxy — do you mean HAProxy is how I should find the
> nodes, or just that our cluster sits behind HAProxy?"*

**Why HAProxy is the wrong discovery source** (the argument to use in review):

1. HAProxy does not *know* who the primary is. It learns by health-checking backends,
   usually `httpchk GET /primary` against Patroni's REST API. Reading HAProxy = reading
   a cached copy of Patroni's opinion, one layer stale.
2. **The killer argument:** you are monitoring the cluster *to detect failover*. If
   discovery depends on the proxy and the proxy is the broken thing, you cannot tell
   "failover happened" from "HAProxy is misconfigured." A monitor must not depend on the
   component it monitors.
3. `svname` in the stats CSV is whatever the operator typed in `haproxy.cfg`. It maps to
   nothing inside PostgreSQL.
4. pgpool's equivalent (`SHOW POOL_NODES`) is a different shape, so it does not even
   generalise across proxies.

**HAProxy is still supported, correctly:** the plugin connects *through* the write port
and then asks `inet_server_addr()`, `current_setting('port')` and `pg_is_in_recovery()`.
That uses the proxy as a **transport to reach the primary**, never as a source of truth.
Say this explicitly in review — it is defensible engineering.

---

## 2. Version history (the honest arc)

| Version | What it did | Verdict |
| :--- | :--- | :--- |
| **v1** (~700 lines) | Explicit node list, probe each node, role from `pg_is_in_recovery()`, Patroni demoted to a display string, zero HAProxy | **Architecturally correct from day one.** Platform-naive: stringified numerics, 6 string columns in `Cluster_Nodes`, an inherited unbound-variable bug, and its own `pop(0)` silently dropping one database |
| **v4** | Single-address discovery | Real requirement — a dev asked not to list every port |
| **v5** | Site24x7 platform contract nailed: the limit validator, generating `units`/`tabs` from one catalogue, the never-fabricate rule | The genuinely valuable work. Also where the health engine ballooned to 16 conditions |
| **v6** (current) | SQL-first discovery, correctness fixes, four scope cuts | Where it stands now |

**One-sentence postmortem:** the direction was never wrong — every version solved a real
problem. The failure was that **every version added and none subtracted.**

For scale: Zoho's own shipped `postgres.py` is **313 lines**. This is **4,969**.

---

## 3. Current state

- **Branch: `v6`**, at `d5e133d`, pushed to `origin/v6`. 13 commits ahead of `v5`.
- Working tree clean as of handoff.
- **Note a divergence:** local `main` is `c45d7b4`, `origin/main` is `467b4f7`. These are
  not the same commit. Resolve before merging anything to main.

| Branch | Commit | What it is |
| :--- | :--- | :--- |
| `v6` | `d5e133d` | Current work |
| `v5` | `be1010e` | Last console-verified lineage |
| `v4` | `a91d5bf` | Single-address discovery |
| `origin/v1` | `e38884b` | Previous intern's / original version |
| `main` | `c45d7b4` local / `467b4f7` origin | **Divergent — check before merging** |
| `audit-fixes` | `35798ae` | Older audit branch |

**Sizes:** plugin 4,969 lines; tests 2,864 across 5 files; reference plugin 313.

**Tests: 104 passed, 11 skipped.** All 11 skips are live-Docker tests in
`test_standalone.py`. See section 9 — this number is weaker evidence than it looks.

---

## 4. Architecture — the part worth defending

### The only three topology facts PostgreSQL core has

| Fact | Source | Property |
| :--- | :--- | :--- |
| Am I a standby? | `pg_is_in_recovery()` | **Ground truth. Cannot be stale.** |
| Who streams *from* me? | `pg_stat_replication` | Primary's live view |
| Who do I stream *from*? | `pg_stat_wal_receiver` | Standby's live view |

Everything else — Patroni, repmgr, Citus, etcd, HAProxy — is an **external register** that
can be stale, partitioned or simply wrong.

### The governing rule

> **Registers tell you which addresses exist. PostgreSQL decides what each one is.**

Implemented in `probe_node()`: `is_prim = not client.is_recovery`. Role is **never** taken
from what Patroni or a proxy claimed. A node that fails to connect keeps its last known
role from state for one hour, then becomes `ROLE_UNKNOWN` rather than being guessed.

### Discovery chain (in `run()`, ordered by authority)

1. **Patroni REST `/cluster`** — exact names, roles, states, timelines, plus `/history`
   for failover age. Authoritative when present. **Earns its place because it is the only
   source that can see a node which is currently DOWN** — a stopped standby is simply
   absent from `pg_stat_replication`, indistinguishable from never having existed.
2. **SQL from the seed** (`discover_cluster_via_sql`) — universal. Connects to any
   endpoint; if the seed turns out to be a standby it follows `pg_stat_wal_receiver`
   upstream to the primary and retries once, then reads `pg_stat_replication` for the
   standbys. Covers plain streaming replication, a VIP, a floating IP, HAProxy, pgpool.
   Needs no HA manager and no proxy stats endpoint.
3. **Explicit `nodes` list** — the escape hatch for pinning exact targets.
4. **Single `cluster_host`** — last resort.

Proxy stats (`fetch_haproxy_stats`) are used **only to put a friendly name on the
primary**, with fallbacks: address_map subtraction → `cluster_name` GUC → `host:port`.

**Phrasing to avoid in review:** never say "it needs Patroni" or "/cluster is always the
case." Say: *Patroni is tier one, SQL is the floor.* Plain streaming + keepalived is very
common, repmgr is still widespread, and RDS/Aurora/CloudNativePG have no Patroni at all.

### What "supports a cluster type" actually means here

Three different things, and a TL will hear the strongest one. Be precise:

- **Discovers topology for:** Patroni (exact) and generic streaming replication (universal).
  It does **not** read `repmgr.nodes`, `pg_dist_node` or `pgautofailover.node`.
- **Detects the type of:** ~7 managers, via extension/env probes (`probe_cluster_managers`).
- **Tested live against:** the testbeds in `environments/` — lead with this number.

---

## 5. The Site24x7 platform contract (do not break these)

Hard limits, enforced every cycle by `validate_output()`:

| Limit | Value |
| :--- | :--- |
| Child tables | 10 |
| Columns per table | 15 |
| Rows per table | 25 |
| **String columns per table (including `name`)** | **5** |
| Top-level metrics | 200 |
| `msg` length | 180 chars |
| `name` length | 520 chars |
| Other string cell | 100 chars |

**Current usage:** 118 catalogue metrics → **146 emitted** at runtime, **9 tables**,
**9 tabs**. Comfortable headroom on metrics; `Replication_Links` sits *exactly* on the
5-string-column ceiling and is pinned by a test.

**Three design rules that are genuinely good — keep them:**

1. **`units{}` and `tabs{}` are generated from one `METRICS` catalogue**
   (`build_tabs_and_units`), so they cannot drift apart.
2. **Never fabricate a value.** When a query fails, `prune_omitted_metric()` *removes* the
   metric rather than emitting 0. A zero charts as a real cliff and is worse than a gap.
   Every collection block has an error arm that prunes and appends
   `metric_unavailable: <name> (<class>)`.
3. **The validator ships in the file and runs every cycle.** Violations are appended to
   warnings, never allowed to overwrite the operator's health `msg`.

**Other platform facts learned the hard way:**
- Plugin folder name = `.py` name = `.cfg` name = cfg section name. All four must match.
- **Tabs and templates freeze at first registration.** You cannot change the tab layout of
  an existing plugin name — you need a *new plugin name*. This previously cost a forced
  version bump.
- Deleting a monitor in the console is not enough: delete the agent folder too, or the
  agent recreates it.
- Console lags roughly one poll (~5 min).
- `cfg` needs `use_agent_python=0` and `redirect_output=1`.
- The agent encrypts cfg values at rest.
- Untabbed numeric metrics chart on the built-in Summary tab. Four are deliberately
  untabbed for this: `Cluster_Health`, `Nodes_Up`, `Standbys_Streaming`, `Max_Replay_Lag_s`
  (see `SUMMARY_METRICS`).

---

## 6. What v6 cut, and why

| Cut | Was | Now | Reason |
| :--- | :--- | :--- | :--- |
| Health/severity engine | 263 lines, 16 conditions | 106 lines, availability only | Site24x7 **has** threshold profiles. Encoding severity in Python means a customer cannot retune "lag > 60s = WARN" without editing source |
| `StateStore` | 258 lines | 171 lines | machine-id namespacing, winreg, ProgramData/XDG/var_lib candidate chains — ~300 lines to persist a handful of counters |
| Untested config surface | `read_port`, `discovery_uri`, blind 5000/5500 probing | removed | If no test touches a setting, it is a question in review, not a feature. `write_port` and `proxy_host` **kept** — they are how an operator points at HAProxy, and they are exercised |
| `self_test()` in the plugin | shipped in production file | migrated to `tests/` | Test code should not ship. A test now asserts `self_test` does **not** exist on the module |
| AI-artifact comments | `# Fix 9`, `# Finding 5`, `# Bug 10 protection` | removed | Code-review artifact names leaked into production source — the real tell that it was AI-generated, far more than volume |

**The rule used to decide:** *if you can't demo it, delete it.* Not "if it's wrong" — if
you cannot show it working in the console in 30 seconds, it is surface area you will be
asked about and cannot defend.

---

## 7. Known bugs, fixed and open

### Fixed in v5/v6 (worth knowing they existed)

- **`UnboundLocalError` → fabricated total outage.** `prev_primary_name`,
  `is_same_primary`, `prev_counters` were bound only inside `if row:` of the section-3.1
  aggregate but read by four later blocks. One failed query raised, `main()` caught it, and
  the monitor emitted `status: 0` with an opaque message **while PostgreSQL was serving
  normally.** Reproduced and fixed. **This bug class is inherited from Zoho's own
  `reference/postgres/postgres.py:231-256`**, which assigns `db_table_result` inside a
  `try` and consumes it outside with no default — it was in the DNA, not introduced by AI.
- **`Standbys_Expected` counted from config, not the cluster.** Was
  `max(len(node_specs)-1, 0)`, so a single seed address reported `2/0 streaming`, dropped
  the standby clause from `Health_Reason`, and left the zero-standbys-streaming CRITICAL
  check permanently unreachable. Now `max(configured, discovered, streaming)`.
- **Patroni byte-lag written into a seconds field.** Patroni's `lag` and the proxy query's
  `replay_lag_bytes` are **bytes**; they were assigned to `replay_lag_s`. A standby 4 MB
  behind charted as 4,194,304 seconds. Key renamed `patroni_lag_bytes` and routed to
  `replay_lag_bytes`.
- **Trailing-digit regex matched the port, not the node index** — `172.30.0.12:5432`
  yielded index 5431, so the primary always resolved to `node_ports[0]`; after a failover
  the plugin collected "primary" metrics from the wrong physical node.
- **Down ex-primary counted as writable** → cluster silently relabelled `multi_master`,
  which switched **split-brain detection off**.
- **Schema violations overwrote the health `msg`**, destroying the diagnosis at exactly
  the moment it mattered.
- **Compat child tables had no `name` guard** — nameless rows failed `validate_output()`
  and truncated `msg` to `| schema: Table `. The whole compat path had **zero schema test
  coverage** because every run()-level test used `compat_official=0`.

### Still open (deliberately)

| Item | Where | Severity |
| :--- | :--- | :--- |
| `run()` is still **1,075 lines** | `run()` | Medium — maintainability. The remaining split needs the settings/state ordering untangled first; a scripted mechanical extraction was attempted and **broke 19 tests**, so it was reverted |
| Index guards that cannot work | ~`r_item[2] if len(r_item) > 2 else r_item[1]` | Low — unreachable with the real 9-column query; dead defensive code |
| No history for never-connected nodes | DOWN branch persists only `if "ts_ok" in entry` | Low — probably deliberate |

---

## 8. ⚠ THE OPERATIONAL GAP — read this before shipping

Cutting the health engine moved alerting responsibility to the platform. **That work was
never finished in the console.**

`Health_Code` is an **emitted metric**, therefore a published alerting contract.

**Live codes** (`LIVE_HEALTH_CODES`): `0, 1, 2, 7, 8, 9, 10, 19`
**Retired** (`RETIRED_HEALTH_CODES`, reserved forever, never re-point them):
`3, 4, 5, 6, 11, 12, 13, 14, 15, 16, 17, 18`

Numbers are reserved rather than deleted so that an existing alert cannot silently start
matching a *different* condition. A test enforces that nothing emits a retired code.

### What this means in practice

`Cluster_Health` still uses the 0/1/2 scale, so an existing threshold profile
(`>= 1` Trouble, `= 2` Critical) keeps *working* — **but WARN (1) now only fires for
"node down."**

Lag, XID wraparound, connection saturation, inactive slots and archive failures used to
raise WARN. They now emit a number and nothing else. **If you ship as-is, the plugin is
quieter than v5**, and you would find out when something degraded and nobody got paged.

### Threshold profiles you must create in the console

| Metric | Suggested Trouble | Suggested Critical |
| :--- | :--- | :--- |
| `Max_Replay_Lag_s` | > 60 | > 300 |
| `Max_Replay_Backlog` | > 100 MB | > 1 GB |
| `XID_Wraparound_Pct` | >= 70 | >= 95 |
| `Primary_Connection_Pct` | >= 90 | >= 95 |
| `Inactive_Slots_Count` | >= 1 | — |
| `Slot_Risk` | >= 1 | >= 2 |
| `Archive_Failed` | >= 1 | — |
| `Timeline_Spread` | >= 1 | — |
| `Standby_Disconnect_Flag` | = 1 | — |
| `Cluster_Health` | >= 1 | = 2 |

Until these exist, v6 is a **net regression in alert coverage** versus v5, despite being
better code.

---

## 9. Verification status — be honest about this

| Layer | Status |
| :--- | :--- |
| Unit / in-process | **104 passed, 11 skipped** |
| Payload contract | A full emitted payload validates with **0 violations** |
| **Live PostgreSQL** | **Not run during the v6 work.** All 11 skips are the live-container tests |
| **Site24x7 console** | **Not verified since v5.** Everything after — SQL-first discovery, the health cut, 12 retired codes, the compat guard — has never been seen by the real agent |

**Read "104 passed" carefully.** Almost everything was verified through a *stub written to
model what the queries are believed to return*. If a real query comes back with a
different shape, the tests pass and production breaks. The live testbeds exist in
`environments/` and were not started.

**Highest-value next action, by a wide margin: start a testbed and run the plugin against
real PostgreSQL, then install it on the agent and look at the console.**

---

## 10. Environment

- **Config:** `postgres_cluster/postgres_cluster.cfg` (live) and `.cfg.example`.
  Current live cfg is minimal: `cluster_host="127.0.0.1"`, `username`/`password`
  `site24x7`, `database="postgres"`. Note it sets **no `write_port`**, so HAProxy
  discovery will not be attempted unless a stats endpoint answers on 7000.
- **Testbeds:** `environments/` — `patroni`, `streaming`, `docker`, `testbeds`, `demo`,
  `showcase`. Docker/kind based. Windows + WSL2 means container subnets are not routable
  from the host; everything goes through published ports on `127.0.0.1` — hence
  `address_map` and `node_ports`.
- **`address_map`** translates container `host:port` to a reachable `host:port`. Patroni
  needs **separate entries** for the PostgreSQL port and the REST port.
- **Tests:** `python -m pytest tests/ -q`
- **Version floor:** PostgreSQL **9.6**. Defensible in one sentence:
  *`pg_stat_wal_receiver` and `pg_blocking_pids` both land in 9.6 — below that there is no
  way to observe replication state at all.* Zoho's own plugin floors at 9.2, so this is
  stricter and feature-driven, not arbitrary. **Do not invent a looser policy** — inherit
  the reference plugin's and justify the delta.
- **`PLUGIN_VERSION = 1`.** Bump only for genuinely impacting changes; re-using a plugin
  name whose template is already registered causes "No plugin versions available in DB".
- **Runtime state:** `postgres_cluster_state.json` next to the plugin, plus
  `.pgcluster-*/` dirs. Now gitignored — it was previously committed by mistake.
- **Commit convention in this repo:** plain messages, **no AI co-author or attribution
  trailers.**

### Other docs

| File | Contents |
| :--- | :--- |
| `postgres_cluster/README.md` | Install, config reference, architecture, enum tables, Health_Code live/retired tables, runbooks |
| `docs/V6_REVIEW_NOTES.md` | The four scope cuts, rationale |
| `v5_extra_bugs.md` | Full v5/v6 bug recheck, F1–F9 with evidence |
| `docs/PR_DESCRIPTION.md` | Draft PR text |

---

## 11. Review talking points

**On discovery:**
> The primary is found by asking PostgreSQL directly — `pg_is_in_recovery()` is the only
> answer that cannot be stale. Patroni, repmgr and HAProxy are used to discover *which
> addresses to ask*, not to decide who the primary is. Patroni earns its place because it
> is the only source that can see a node that is currently down. HAProxy is a transport,
> not a source of truth.

**On the health engine cut:**
> The plugin reports facts; Site24x7 decides what is alarming — except for the three
> things only the plugin can know: is there a primary, is there a split brain, did auth
> fail.

**On scope — own it before someone names it:**
> I overbuilt. The reference plugin is 313 lines and this is ~5,000. Here is the minimal
> subset I would ship and why; here is what I cut and why.

Seniors respect that. They do not respect being told 5,000 lines was the right size.

**On size, if pressed:** do not defend the line count — defend the structure. The real
question is *"who maintains this after the internship ends."* `run()` at 1,075 lines is
the honest answer to why that question is still uncomfortable.

**Lead with:** the number of cluster types verified live, and a 30-second console demo of
a failover being detected. That beats every other argument available.

---

## 12. Where the AI advice in this project was wrong

Recorded so it is not re-trusted:

- **Proposed deleting the 12 retired `Health_Code` constants.** Wrong — reserving the
  numbers is correct, and it had already been solved better in-repo.
- **A scripted extraction of the parameter-resolution block compiled cleanly and broke 19
  tests.** Compiling is the dangerous part. Reverted.
- **Claimed `Stats_per_DB`'s 10 string columns violated the platform limit.** Zoho's own
  plugin does the same thing, so either the documented limit is conservative or the
  official plugin violates it. Unresolved — do not assert either way.
- **Reported `&` in the tab name `"Capacity & WAL"` as a defect.** It is deliberate, and
  `tests/test_plugin.py` already carves it out explicitly.
- **Leaned on "104 tests pass" as stronger evidence than it is.** See section 9.

**The meta-lesson, which matters more than any of the above:** AI did not create the
scope problem — it *amplified a misread premise*, fast and convincingly, and it looked
professional the whole way down. The defence is not writing less AI code. It is validating
the premise before spending a week on it.
