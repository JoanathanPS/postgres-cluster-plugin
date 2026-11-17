<USER_REQUEST>
# FIX-PROMPT — paste into Antigravity

Copy everything below the line into Antigravity with the repo open. It is deliberately
shorter than the build contract: this is a **repair** job, not a rewrite. It names the
exact defects, the exact behaviour after the fix, and a stop-and-show gate after each one.

Line numbers come from an automated audit — tell the agent to verify before editing, and
to fix by *intent*, not by line number.

---

You are fixing an existing, working-tree Site24x7 plugin. Do **not** rewrite it, do not
restructure it, do not add cluster managers it does not have. It is 2,428 lines and it is
mostly right. Your job is nine surgical fixes plus proof for each one.

Repo root: `postgres_cluster/`. Main file: `postgres_cluster/postgres_cluster.py`.
Also present: `postgres/postgres.py` (the official per-instance plugin, reference only),
`tests/test_plugin.py`, `tester/test_cluster_plugin.py`.

## Rules for this task

- One fix at a time. After each, run the gate command and paste the output. Do not
  proceed to the next fix until the gate is green. Do not batch fixes and report at the end.
- Do not change any public metric name that already works, unless a fix below names it.
- Do not add new dependencies. `psycopg2` only.
- Do not delete existing tests. Add to them.
- If a line number below does not match the code, find the real one and say so — then fix
  the behaviour described, not the line.
- If a fix cannot be done without a decision from me, stop and ask. Do not guess.

---

## Fix 1 — Registration: the plugin must register at all

**This is blocking. Nothing else matters until this is green.**

The WinAgent returns `Invalid data. Plugin Monitor Registration failed.` and never creates
the monitor. Three causes:

**1a. Every child table needs its own unit map.** `units` must contain an entry per child
table, keyed by table name, whose value maps column → unit:

```python
"units": {
    "Cluster_Nodes": {"role": "flag", "status": "flag", "resp_ms": "ms",
                      "lag_bytes": "B", "last_seen_s": "s"},
    ...
}
```

A table with no `units` entry is rejected. This is the main cause.

**1b. Units must be simple — no compound units.** `txns/s`, `rows/s`, `blocks/s`,
`MB/s` are all rejected. Rename the column so the rate lives in the name and declare a
simple unit:

| column today | unit today | rename to | unit after |
|---|---|---|---|
| `Commits` | `txns/s` | `Commits_per_s` | `count` |
| `Tuples_Fetched` | `rows/s` | `Fetched_per_s` | `count` |
| `Block_Reads` | `blocks/s` | `Blk_Read_per_s` | `count` |
| `WAL_Rate` | `MB/s` | `WAL_MB_per_s` | `MB` |

Match whatever the actual names are. If a rename breaks a tab entry, update the tab too.

**1c. String columns get no unit at all.** `node`, `action`, `scope`, `text`,
`status_reason`, `msg` and every other string column must be **absent** from `units`.
Declaring a unit on a string column is the third rejection.

**1d. Tab names may not contain `&`.** `Health & Capacity` → `Health and Capacity`.
`WAL & Archiver` → `WAL and Archiver`. Safe set: letters, digits, space, `_`, `-`.

**1e. Keep at least one integer parent metric.** `Primary_Up` and `Nodes_Total` must stay
ints, never floats.

Generate `units` programmatically from the metric catalogue, per table — do not hand-write
the dict.

**Gate 1 has two parts, and part 2 is the only one that counts.**

*Part 1 — local sanity (necessary, not sufficient).* `python
postgres_cluster/postgres_cluster.py > out.json`, then check: no table missing from
`units`, no `/` in any unit string, no unit on a string column, no `&` in a tab name.
Paste the `units` block and the tab names.

*Part 2 — registration on the real agent (this is the proof).* Deploy to
`C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\<name>\`, restart the
agent, and watch `PluginRegisterLog.log`. Paste the log lines and the resulting monitor
state. A locally written validator agreeing with us proves nothing about Site24x7's
backend — v6 passed local inspection and was still rejected.

If registration fails again, paste the **full** log line. Do not iterate blindly on the
payload: the rejection message is the only ground truth here, and our local rules are
inferred, not documented.

---

## Fix 2 — A wrong password must not show a green monitor

As audited around `postgres_cluster.py:497-511` and the status assignment near `:2347-2359`:
an auth failure returns `Health(code=OK, severity=WARN, ...)`, and the payload then does
`status = DOWN if severity == CRITICAL else UP`, so a bad password produces `status=1`
with `Auth_Failure_Flag=1`. That is a monitor that lies.

**After the fix:** `status = 0` for `auth_failure`, `config_error`, and any cycle where
the primary's core metrics could not be measured. `msg` must say what happened
(`auth failed for user X on pg1`) and must **not** say "primary down". The last-known-good
data may still be emitted, but it may never turn the monitor green.

**Gate 2:** run with a deliberately wrong password. Paste `status`, `Auth_Failure_Flag`,
and `msg`. Expect `status=0`, flag `1`, and an auth message.

---

## Fix 3 — A failed query must never become a zero

As audited: `except Exception as e: self.warnings.append(...); return []`, then downstream
`len([r for r in rep_rows if ...])` turns "not allowed to look" into `Standbys_Streaming=0`,
`Slots_Total=0`, `Lag=0`.

**After the fix:** every collected value is one of three things — a real value, `None`
(could not measure), or a real `0`. `None` increments that metric's unavailable counter
and adds a `metric_unavailable` note naming the metric and the SQL error class
(`insufficient_privilege`, `undefined_table`, `connection`, …).

**Do not omit the key on failure** — Site24x7 keeps the stale previous sample and the chart
looks fine on a metric nobody can collect. That part is certain.

**The sentinel is not yet certain: I do not have evidence that Site24x7 accepts negative
values.** Before choosing, run the 5-minute experiment below and pick from the result.
Do not assume `-1` works just because it is convenient.

| candidate | why it might win | why it might fail |
|---|---|---|
| `-1` | impossible real value for counts; visible; one number to threshold (`< 0`) | unknown whether negative floats are stored, charted, and thresholded correctly |
| `status=1` companion int + omit value | no reliance on negative support | the omitted value charts as stale-but-fine |
| keep `0` + `Metric_Unavailable=1` companion int | safe everywhere | loses per-metric precision; must be a per-table column for node metrics |

**The experiment (do this first, paste the result).** Emit a payload containing three
numeric metrics: `Probe_Neg` = `-1`, `Probe_Zero` = `0`, `Probe_Pos` = `1`. Ship it,
wait for two collection cycles, then check, per metric: does the value appear in the
console, does the chart plot it below the axis, and can a threshold `< 0` fire on
`Probe_Neg`? Paste screenshots or the observed values. Pick the sentinel from what you
see, and record the choice in the README. If `-1` charts and thresholds correctly, use
it; if not, use the companion-int design.

Whichever you pick, it must be uniform across the whole catalogue, documented as
*not measured*, and never used where a real negative is meaningful (lag, offsets,
time zones — those must not be sentinelled).

Also remove any "expected" value derived from a possibly-failed query, e.g.
`Standbys_Expected = max(len(node_specs) - 1, len(rep_rows))` — it must come from config
or discovery, never from a query that might have returned `[]`.

**Gate 3, part A — run the sentinel experiment first.** Gate 3 cannot be written until
the negative-value experiment (above) has a result. Paste the experiment output before
touching the collector.

**Gate 3, part B — depends on what part A proved:**

- If `-1` charts and thresholds correctly: run against a role with no `pg_monitor` grant
  and paste `Standbys_Streaming=-1` (not `0`), the `metric_unavailable` note, and
  `status=0`.
- If `-1` does **not** work: paste `Standbys_Streaming` **omitted**, the companion
  `Metric_Unavailable=1` int set, the `metric_unavailable` note, and `status=0`. Do not
  emit `-1` anywhere, and remove it from the design notes.

Either way the proof is the same three things: the failed query did not become a real
zero, the note names the metric and error class, and the monitor is `status=0`.

---

## Fix 4 — The collection cycle needs a deadline

As audited around `:1846-1858`:

```python
with concurrent.futures.ThreadPoolExecutor(max_workers=workers_count) as executor:
    ...
    for future in concurrent.futures.as_completed(future_map):
```

The `with` block **joins every worker on exit**, so one node that accepts TCP and then
stalls holds the whole poll open past Site24x7's 50 s script budget. `as_completed` does
not help: the `__exit__` waits.

**After the fix, in this order — a deadline alone does not fix this.**

1. **Real socket and statement timeouts.** Every connection must carry
   `connect_timeout=<n>` and every session must execute
   `SET statement_timeout = <ms>` plus `SET lock_timeout` and `SET idle_in_transaction_session_timeout`
   immediately after connecting. There must also be a TCP-level guard: a raw socket
   connect with a timeout, or `socket.setdefaulttimeout`, because `psycopg2.connect()`'s
   `connect_timeout` does not cover every blocking phase (DNS, TLS handshake, a
   half-open peer). **A thread we cannot interrupt is only safe if it is guaranteed to
   return.**
2. **Cycle deadline.** Default 40 s, cfg-overridable. Collect with
   `concurrent.futures.wait(pending, timeout=remaining)`; anything not done is
   `unreachable` with `last_seen` preserved, and `Budget_Exceeded=1` is set.
3. **Do not use the executor as a context manager**, and do not rely on
   `shutdown(wait=False)` to stop anything — it does not terminate a running thread.
   Call `executor.shutdown(wait=False, cancel_futures=True)`; that only stops tasks that
   have not started.
4. **The process must still exit — cleanly, in this preference order.**

   a. **Bounded work first** (steps 1–2). If every operation has a real timeout, no worker
      can outlive the budget and nothing else is needed. This is the fix. Do not reach
      for the options below until 1–2 are demonstrably in place.
   b. **Daemon worker threads — a supporting change, not a replacement.** `ThreadPoolExecutor`
      workers are non-daemon, and Python joins them at interpreter shutdown; that is the
      actual mechanism that keeps the process alive. Plain `threading.Thread(daemon=True)`
      avoids *that* join, but it is **not** a drop-in substitute: you lose futures,
      `as_completed`, exception propagation and pool reuse, and you must collect results
      yourself through a queue. Do not rewrite the fan-out just to get daemon threads.
      The invariant that matters is (a): **every database operation must be bounded** —
      `connect_timeout`, `statement_timeout`, `lock_timeout`, and a socket-level guard.
      Daemon threads only decide what happens to a worker that is already unbounded;
      correctness comes from it never being unbounded. Prove exit by measurement, not by
      argument.
   c. **A watchdog with a clean exit path.** A `threading.Timer` that, at the deadline,
      flushes the payload and calls `sys.exit()` — still runs `finally` blocks.
   d. **`os._exit(0)` only as a documented last resort**, gated behind
      `hard_exit = 1|0` (default `0`), and only after `sys.stdout.flush()`. It skips
      `finally`, `atexit`, and buffer flushing — which means it can hide a leaked
      connection or a half-written payload. If you enable it, you must also prove in the
      gate that the connection is closed and no file handles leak, because `os._exit`
      would mask the evidence.

The invariant: **the payload is emitted on time, and the process is gone when the agent
looks.** A payload that arrives but whose process lingers is a failed cycle in Site24x7's
eyes. Achieve that by never starting unbounded work, not by killing the process.

**Gate 4:** run it twice — once with bounded operations only (futures kept, no threading
rewrite) and once with your chosen exit mechanism — and paste both. On the 3-node rig,
make one node accept TCP and then block forever (a listener that never responds). Run the plugin as the agent would, **with `hard_exit=0`**, and paste:
(a) wall-clock time from launch to last byte on stdout, (b) wall-clock time to process
exit, (c) `ps` showing no surviving plugin process, (d) the payload with the stalled node
`unreachable` and `Budget_Exceeded=1`, (e) proof of clean shutdown — the DB connection is
closed (`pg_stat_activity` shows no session from this plugin a second later) and every
`finally` block ran. All five. If (b) fails with `hard_exit=0`, fix the threading model
(step 4b/4c) rather than flipping the flag.

---

## Fix 5 — Multi-master must not be reported as split brain

As audited around `:523-533` and `:2324-2347`: the health engine has a multi-master
exception, but the call site never passes `is_multi_master=True`, so every second writable
primary becomes `SPLIT_BRAIN` — a false critical on a valid topology.

**After the fix:** detect topology **before** evaluating health, and pass the flag
through. Split-brain is raised only when more than one primary exists in a topology that
is not multi-master, Citus, or a deliberate mesh. A detected multi-master emits
`Topology_Type=multi_master` and per-node lag, and raises no split-brain code.

**Gate 5:** simulate two writable nodes in a multi-master topology. Paste the health code
and `Topology_Type`. Expect no `SPLIT_BRAIN`.

---

## Fix 6 — Cluster-manager detection must be evidence-based

As audited around `:1720-1740`: `if patroni_data and "members" in patroni_data:
cluster_manager = 1`. Any HTTP endpoint returning JSON with a `members` key is declared
Patroni.

**After the fix, detect in this order with these proofs:**

1. **Patroni** — the response contains a member object with `name`, `role` **and** `state`,
   where `role` is one of Patroni's known values (`leader`, `standby_leader`, `replica`,
   `sync_standby`, `async_standby`, `uninitialized`, `master`), **and** `state` is one of
   its 15 known strings. A JSON with `members` alone is not proof.
2. **repmgr** — `repmgr.nodes` exists and the extension/version function resolves.
3. **Citus** — `citus.version()` succeeds.
4. **CloudNativePG** — operator markers present.
5. **Stolon** — keeper metadata endpoint answers.
6. **pg_auto_failover** — `pgautofailover.node` exists.

Two distinct outcomes are required, and they are not the same thing:

- **`native`** — *positively* identified PostgreSQL streaming replication with no external
  manager. Positive evidence: `pg_stat_replication` on the primary lists at least one
  walsender, **or** this node has `pg_is_in_recovery() = true` with `primary_conninfo`
  set, **or** `pg_stat_wal_receiver` shows a live receiver.

  The manager probes do **not** all have to run. Only probes that are *applicable* to the
  environment must return a clean negative (see the applicability table below). A probe
  that is not applicable is recorded as `not_applicable`, which is a clean state, not a
  gap.
- **`unknown`** — we could not establish it. Any **applicable** probe that errored,
  timed out, or returned something ambiguous lands here, and so does an environment where
  no probe could even be attempted. Insufficient evidence is `unknown`, never `native`.

### Which probe is applicable where

Not every manager exposes a universal endpoint, and probing for one that cannot exist
produces false `unknown`s:

| manager | probe | applicable when |
|---|---|---|
| Patroni | `GET /cluster` or `/patroni` | always (cheap HTTP; a refusal is a clean negative) |
| repmgr | `repmgr.nodes` / extension in `pg_extension` | always (one cheap catalog query) |
| Citus | `citus.version()` / `pg_extension` | always (one cheap catalog query) |
| pg_auto_failover | `pgautofailover.node` in `pg_extension` | always (catalog) |
| CloudNativePG | operator markers (env, labels, `cnpg_*` settings) | always (local signals, no network) |
| Stolon | keeper/consul endpoint | **only if** a keeper address or consul URL is configured, or the sentinel/keeper port answers on the local host. No configured endpoint ⇒ `not_applicable`, **not** `unknown` |

So an environment with no Stolon endpoint configured and four clean negatives plus a live
wal receiver is `native` — not blocked by a probe that could not have succeeded.

Record the per-probe outcome (`negative` / `not_applicable` / `error`) in the `Topology`
table so the reasoning is visible instead of assumed.

So: a plain streaming replica on a reachable host must end up `native`; a host we could
not probe, or a JSON blob with a `members` key that is not Patroni, must end up `unknown`.
If you cannot tell the difference in the code, that is the bug.

Do **not** add full per-manager health logic in this task. Detection and honest reporting
only — this is the compatibility tier, and it must not delay anything.

**Gate 6:** point the collector at four targets and paste `Topology_Type` for each:

| target | expected | why |
|---|---|---|
| your Patroni node | `patroni` | member objects with `name`+`role`+`state` |
| plain streaming replica, manager absent **and** probe reachable | `native` | clean negative + positive streaming evidence |
| URL returning `{"members": []}` | `unknown` | not Patroni evidence, no streaming evidence either |
| host that refuses/times out on the **Patroni** probe while a wal receiver is live | `unknown` | a timed-out applicable probe is not a negative |
| no Stolon endpoint configured, other probes clean, wal receiver live | `native` | `not_applicable` is clean |

If #2 and #4 both come out `native`, the distinction is not implemented.

---

## Fix 7 — Version floor and capability gating

As audited around `:289-344`: unversioned SQL such as `pg_control_system()` (10+) and
version-dependent `pg_stat_replication` columns are used with no gate.

**After the fix:** floor is PostgreSQL **9.6**. Below it, emit `unsupported_version` and
stop collecting instance metrics — do not degrade silently. Above the floor, gate each
version-sensitive query behind a capability check (`requires`), reusing the existing
`parse_pg_version`. Parse must tolerate `16.2`, `12.3_TDE_1.0`, `11.22-rds.20241121`,
`17devel`; a parse failure is a warning, not a crash.

**Gate 7:** paste the `requires` map (query → minimum version) and the output on your
newest and oldest available server.

---

## Fix 8 — Regression tests for exactly these bugs

The existing tests are pure-function only and would pass with all of the above broken.
Add one test per fix, in `tests/`:

1. wrong password → `status == 0`, `Auth_Failure_Flag == 1`, msg mentions auth
2. permission-denied query → metric carries the **sentinel proven by the experiment**
   (`-1` or the companion-int design), note is `metric_unavailable`, and the value is
   never a real `0`
3. two primaries, multi-master topology → no split-brain code
4. two primaries, non-multi-master → split-brain code raised
5. stalled node → cycle returns under budget, node `unreachable`
6. JSON `{"members": []}` → `Topology_Type == "unknown"`, not `patroni`
7. version `9.4` → `unsupported_version`
8. payload shape → every child table has a `units` map; no unit contains
   `/`, `+`, `(`; no unit on a string column; no `&` in a tab name
9. `compat_official=1` → every legacy metric name present and numeric; `=0` → none
   present; total metric count ≤ 200 in both; default is `0`
10. stalled node → the **process** exits within budget with `hard_exit=0`, the DB
    connection is closed, and no thread survives
11. sentinel → whatever the negative-value experiment proved, asserted in one test
12. topology reasoning → the `Topology` table records each probe as
    `negative` / `not_applicable` / `error`, and `native` is reachable with a
    `not_applicable` Stolon probe

**Gate 8:** `python -m pytest tests/ -q` — all pass, and paste the count of new tests.

---

## Fix 9 — Backward compatibility with the official PostgreSQL plugin

I over-corrected here last time. The honest position: **I do not know whether your
internship requires drop-in compatibility with the official `site24x7/plugins` `postgres`
plugin, or whether cluster-level monitoring alongside it is acceptable.** So do not decide
it — implement the mechanism, keep it switchable, and flag it for me.

### What "compatibility" means here, precisely

The official plugin is per-instance: one host, one database, 19 documented parent metrics
plus ~15 derived counters, two child tables, three tabs. Verified from its source:

- parent metrics, exact names (case and spacing matter — thresholds are configured
  against these strings): `Active Connections`, `Max Connections`, `Uptime`,
  `Total Rows Deleted`, `Total Rows Fetched`, `Total Rows Inserted`, `Total Rows Returned`,
  `Total Rows Updated`, `Total Commits`, `Total Rollbacks`, `Total Conflicts`,
  `Total Sessions`, `Total Sessions Abandoned`, `Total Sessions Fatal`,
  `Total Sessions Killed`, `Transactions Idle In Transaction`, `Transactions Open`,
  `Locks Count`, `Database Count`
- derived from query columns, title-cased with underscores → spaces: `Table Count`,
  `Active Queries`, `Active Waiting Queries`, `Checkpoints Timed`, `Checkpoints Req`,
  `Checkpoint Write Time`, `Checkpoint Sync Time`, `Buffers Checkpoint`, `Buffers Clean`,
  `Maxwritten Clean`, `Buffers Backend`, `Buffers Backend Fsync`, `Buffers Alloc`,
  `Index Scans`, `Index Rows Read`, `Index Rows Fetched`, `Heap Blocks Read`,
  `Heap Blocks Hit`, `Cache Hit Ratio`
- units are unusual and must be copied verbatim: `connections`, `s`, `rows`,
  `transactions`, `sessions`, `locks`, `databases` — and note these are *not* in
  Site24x7's documented set, yet they register. Do not "fix" them.
- tabs: `DB and IO stats`(1), `BG Writer`(2), `Transactions and Sessions`(3)
- two child tables: `Stats_per_DB` and `Tranasctions_and_Session_per_Database`
  (that spelling is theirs — keep it if you emit compatibility tables)
- child-discovery key: `s247config` with `childdiscovery` list. **The docs say
  `s4z7config`; the shipped plugin uses `s247config`.** Emit `s247config`.

### What to build

Add a cfg option `compat_official = 1|0`, **default `0`**.

Default off is the safe default: the platform cap is 200 metrics, and this adds ~38.
Turning compat on is a deliberate, documented act by the operator — not something a fresh
install picks up silently. Flip the default to `1` only if I tell you the requirement is
drop-in compatibility (see the open question at the end of this fix).

### Read this before you trust it: names are not behaviour

Matching `Total Commits` does **not** make us equivalent to the official plugin. Verified
differences that survive any name matching, and which you must not paper over:

| official plugin | ours | consequence |
|---|---|---|
| one instance, one DB, one connection | cluster-wide fan-out, several servers | `Total Commits` from us means *the local node*, and we must compute it the same way (sum over `pg_stat_database` on one host) — not a cluster sum |
| collects on a fixed list of queries, no version floor | version-gated catalogue | on 9.4 the official plugin degrades per-query; we refuse with `unsupported_version` |
| `str()`s every value → unthresholdable | real numbers | values will look numerically identical in charts but ours can be thresholded; do not "fix" ours to strings |
| errors go into a single `msg` string | classified codes + `metric_unavailable` | a broken official plugin shows partial data; ours shows `status=0` |
| no `s247config` units for child tables | per-table unit maps required | their tables are shaped differently; a copied dashboard widget may not bind |

So: emit the legacy names **and state plainly in the README that this is a compatible
metric surface, not a drop-in replacement**, and list the differences above. If the
requirement turns out to be true drop-in replacement, that is a different product decision
and I will tell you.

When `compat_official = 1`, the payload additionally contains:

1. **Every metric name above, for the local node only** — computed from the same queries
   you already run, on the node the agent is installed against (primary if reachable,
   otherwise the local instance). Same names, same units, same meaning: `Total Commits` is
   *this instance's* `xact_commit`, not a cluster rollup. Do not redefine it.
2. The two compatibility child tables with the official column names, for the local
   instance only.
3. A `s247config` → `childdiscovery` block listing them.

When `compat_official = 0`, none of the above is emitted and the plugin is purely
cluster-shaped.

Keep the cluster-side metrics exactly as they are — compat is additive, never a rename.
The two families must not collide: prefix is not needed because the legacy names are
already distinct (`Total Commits` vs `Cluster_Commits`). If any name collides, stop and
ask me.

### The budget check, which is the real risk

The platform cap is **200 metrics**. Adding ~38 compatibility names to a cluster payload
that may already be near the cap will silently drop metrics server-side. So:

- Compute the total emitted count with `compat_official=1` and paste it. If it exceeds
  ~190, print a warning in `msg` and stop and ask me which family to trim.
- Numeric values must be real numbers, not `str()` — the official plugin stringifies
  everything, which makes it unthresholdable; keep the names, improve the types.

### Do not

- Do not delete the cluster metrics to make room.
- Do not rename cluster metrics to legacy names.
- Do not point both plugins at the same host and call it a fallback — that doubles
  collection and produces two monitors with the same numbers.

**Gate 9:** run with `compat_official=1` and paste (a) the emitted metric count,
(b) the legacy metric list with values from a real server side by side with the official
`postgres.py` run on the same server, (c) confirmation the two names and values agree,
(d) confirmation nothing exceeds 200. Then repeat with `=0` and paste the count.

**Open question I have to answer, not you:** whether the internship requires drop-in
compatibility with the official plugin or coexistence. Until I answer it, ship with the
default `0`, document the surface, and list the semantic differences above. Do not assume
either answer, and do not silently ship compat on.

---

## Explicitly out of scope — do not do these

- **Do not build full repmgr / Stolon / Citus / CloudNativePG / pg_auto_failover support.**
  Detection and honest `Topology_Type` only (Fix 6).
- **Do not rename or restructure the cluster metrics** to look like the official plugin.
  Compatibility is additive (Fix 9), behind a cfg flag, and never replaces the cluster
  shape.
- **Do not refactor for scale.** 25 rows per table is enough for real clusters
  (1 primary + 2–6 standbys).
- **Do not invent a cluster event history table.** We do not have that data.
- **Do not touch** `postgres/postgres.py` except to read it.

## Final report

After all **nine** gates are green, produce:

1. A table: fix → file → what changed → gate output (one line each).
2. The final `units` block and the final tab names.
3. A list of anything still unverified, stated plainly. An honest "unverified" list is
   accepted; a claim without a gate is not.
4. Confirmation that the monitor registered on a real agent, with the `PluginRegisterLog.log`
   lines pasted — this is the only proof that counts.
5. With `compat_official=1`: the total emitted metric count (must be ≤ 200) and a
   side-by-side of legacy names/values against the official `postgres.py` on the same host.

</USER_REQUEST>
<ADDITIONAL_METADATA>
The current local time is: 2026-11-11T17:31:49+05:30.
</ADDITIONAL_METADATA>