# PostgreSQL Cluster Plugin — v6 review notes

Branch `v6`. Written for review, so it states what was asked for, what exists, what
I would ship, and what I would not.

---

## 1. The ask, and what happened to it

**Asked:** research PostgreSQL cluster monitoring and get node details into a Site24x7
plugin — primary/standby roles, with the cluster's own view of itself (initially via
HAProxy, since that was the lab setup).

**Built:** a 5,300-line single-file plugin with 117 metrics across 9 tabs, 7 child
tables, a health reasoning engine, a persistent state store, and a shipped Site24x7
contract validator — plus test beds for seven different cluster managers.

For scale: **the Site24x7 postgres plugin this is modelled on is 313 lines.** This is
roughly sixteen times that. That is more than the task needed, and the overbuild is
mine to own rather than something a reviewer should have to discover.

What follows separates the part that answers the ask from the part that does not.

---

## 2. The one thing that was actually wrong, and is now fixed

Discovery only worked through **HAProxy or Patroni**. On a plain streaming-replication
pair with neither, the plugin fell through to "single node" and the operator had to
list every node by hand. Since most PostgreSQL deployments have no HAProxy, that was a
real limitation on the core deliverable.

It turned out to be incidental rather than fundamental. The function named
`discover_primary_via_proxy()` never needed a proxy: it connected to a PostgreSQL
port, called `pg_is_in_recovery()`, read `inet_server_addr()` / `port` / `cluster_name`,
then read `pg_stat_replication`. All pure SQL. The proxy stats CSV was used **only to
put a friendly name on the primary**, with three naming fallbacks already behind it.
Two things tied it to HAProxy: the call site fired only when a stats endpoint answered,
and it gave up if the seed turned out to be a standby.

**v6 reworks it into `discover_cluster_via_sql()`:**

- Works from any one reachable address — a node, a VIP, a floating IP, HAProxy, pgpool.
- If the seed is a **standby**, it follows `pg_stat_wal_receiver` upstream to the
  primary and retries once, so you may point it at any node rather than the leader.
- A proxy stats endpoint is now a naming convenience gated on `stats_port > 0`. Losing
  it costs a nicer label and nothing else.
- The chain is reordered by how authoritative each source is:
  **Patroni REST → SQL from seed → explicit node list → single node.** Patroni is first
  because it is the only source that can provide real failover history.

**Verified against the live 3-node Patroni lab, with the proxy stats endpoint disabled,
using each node in turn as the seed:**

```
seed 127.0.0.1:5441 → primary pg-node3 (127.0.0.1:5443) + 2 standbys  (followed upstream from a standby)
seed 127.0.0.1:5442 → primary pg-node3 (127.0.0.1:5443) + 2 standbys  (followed upstream from a standby)
seed 127.0.0.1:5443 → primary pg-node3 (127.0.0.1:5443) + 2 standbys
```

The honest answer to "not everyone has HAProxy" is therefore: correct, and it no longer
matters. HAProxy is an optimisation, not a requirement.

---

## 3. Other defects fixed in v6

| Severity | Defect | Fix |
|---|---|---|
| **Critical** | Four baselines were bound only inside `if row:` of the main aggregate query but read by four later sections. One failed query raised `UnboundLocalError`, which the top-level handler turned into `status: 0` — **a fabricated total outage while PostgreSQL was serving normally.** | Baselines resolved before the query; added the missing error arm that prunes the 15 affected metrics instead of zero-filling them. Reproduced before and after against a stubbed driver. |
| **High** | `Standbys_Expected` was `len(node_specs) - 1`, i.e. counted from config, not the cluster. With one seed address it reported `2/0 streaming`, dropped the standby clause from `Health_Reason`, and left the zero-standbys-streaming CRITICAL check permanently unreachable. | Derived from the max of configured count, discovered standby rows, and observed streaming count. Live lab now reports `2/2 streaming`. |
| **High** | Discovery ran before the `cycle_deadline` budget was applied, so a seed that accepts TCP but never completes the handshake could consume the entire collection interval before probing started. | Discovery gets its own slice: `max(1s, min(30% of cycle, 10s))`, with the Patroni timeout clamped to what remains and the candidate loop checking the budget before each attempt. |
| **High** | `postgres_port` suppressed discovery entirely — any non-5432 value collapsed a cluster to a single node. | Removed. `postgres_port` names the port to discover *on*; `nodes` is the escape hatch for pinning a target. Live lab with `--postgres_port 5443` now returns 3/3 nodes instead of 1. |
| Medium | Schema violations were silent. The reporting guard read `if status == UP and not payload.get("msg")`, but `msg` is always set above it, so the branch never fired; the warning text was appended after the only code that reads it. A violation causes Site24x7 to drop metrics server-side. | Appended to `msg` (appended, never substituted, so an outage message survives) plus a new alertable `Schema_Violations` metric. |
| Medium | Compatibility metric names were derived from whatever column names the server returned and emitted unconditionally. A fork, a pooler or a future column rename would produce an untabbed, unitless metric and trip the contract check. | Validated against `OFFICIAL_COMPAT_UNITS`; anything undeclared is dropped with a warning. Verified with a stub returning unexpected names: 7 violations before, 0 after. |
| Low | Byte lag from Patroni / `pg_wal_lsn_diff` was written into `replay_lag_s`, a field declared in seconds. | Routed to `replay_lag_bytes`; the spec key is now `patroni_lag_bytes` so the unit cannot be misread again. |

Also removed: code-review artefacts that had leaked into the source as comment names
(`# Fix 9`, `# Finding 5`, `# Bug 10 protection`, `# Issue #2`), each replaced with a
comment explaining why the code is there; and comments that had gone stale (the header
still said "v5 Engine", the tab block claimed "Exact 8 Tabs" when there are nine).

---

## 4. Structure

`run()` was 2,003 lines — the main obstacle to anyone else owning this. Two cohesive
stages are now module-level functions with explicit inputs, outputs and docstrings:

- `collect_primary_metrics()` — 635 lines, 13 inputs, 17 returned values. Everything
  readable only from a live connection. Its docstring states the per-query contract the
  whole stage follows (write on success; prune and record `metric_unavailable` on
  failure; never emit a fabricated zero) which previously had to be inferred.
- `build_child_tables()` — 176 lines. The six child tables, with row-cap truncation in
  one place.

`run()` is now 1,254 lines and reads as the sequence it always was: resolve config,
discover topology, probe nodes, collect, build tables, evaluate health, emit.

Verified behaviour-preserving: every stable payload key is byte-identical to the
pre-refactor run against the live cluster. Only `Failover_Age_s` (seconds elapsed) and
`Slowest_Node` (whichever node answered slowest) differ.

**Note:** the plugin stays a single file deliberately — a Site24x7 plugin is one `.py`
in a folder named after it, so splitting into modules is not available.

---

## 5. What I would ship, and what I would not

**Ship:** the discovery chain, the per-node tables, the Site24x7 contract validator,
and the version gating. These answer the ask and the validator in particular is the
part I would defend hardest — it enforces the 10-table / 15-column / 25-row /
5-string-column / 200-metric caps on every cycle, and the "never fabricate a value"
rule, so a failed query removes its metric rather than reporting a zero that charts as
a real cliff.

**Reconsider before shipping:** the health engine. `evaluate_cluster_health()` encodes
16 prioritised severity conditions in Python — but Site24x7 already has threshold
profiles. As written, a customer cannot retune "standby lag > 60s = WARN" without
editing plugin source. **I would move severity to threshold profiles and have the
plugin emit numbers only.** That is a product decision above my level, so I have left
the engine in place and flagged it rather than ripping it out. It is the change I would
make first if told to cut scope.

**Keep as research, not product:** the seven cluster-manager test beds (Patroni,
repmgr, Citus, Stolon, pgpool-II, CloudNativePG, pg_auto_failover). That work is the
research half of the ask and is worth keeping in-repo, but it is not plugin code.

---

## 6. Version support

`VERSION_FLOOR = (9, 6)`, which is **stricter than the shipped Site24x7 postgres
plugin** (`(major >= 9 and middle >= 2) or major >= 10`, i.e. 9.2+). The floor is
driven by the feature set, not picked arbitrarily: `pg_stat_wal_receiver` and
`pg_blocking_pids` both land in 9.6, and below that there is no way to observe
replication state at all — which is the entire point of this plugin.

Version-gated behaviour, all verified against the real catalog changes:
PostgreSQL 17 split `pg_stat_bgwriter` into `pg_stat_checkpointer` + `pg_stat_io`;
14 added the `pg_stat_database` session counters; 13 added `wal_status` on
replication slots; 12 made `recovery_min_apply_delay` a GUC; 10 renamed `xlog` → `wal`.
Below 10 the `pg_xlog_*` spellings are used.

I did not consider raising the floor to drop compatibility code. The shipped plugin
sets the product's bar and that is not an intern's call to change.

---

## 7. Known limitations

- **Container/NAT addressing.** Discovery returns addresses as the *cluster* sees them.
  On Docker Desktop for Windows those container IPs are not routable from the host, so
  `node_ports` or `address_map` is required to translate them. Without it the plugin
  correctly discovers the nodes and then correctly reports them unreachable — which is
  truthful but could carry a clearer hint than "no primary reachable".
- **Topologies the catalogs cannot express.** `pg_stat_replication` shows a standby's IP
  but not its port, so a standby cannot be followed *downstream*. For Stolon,
  CloudNativePG, pg_auto_failover and plain streaming, listing every node in `nodes`
  remains the reliable option. Patroni, repmgr, Citus and pgpool-II give exact lists and
  need only one address.
- **Not tested below PostgreSQL 17** in a live cluster. The sub-17 query paths are
  version-gated and unit-tested, but the only live bed is PostgreSQL 17 on Patroni.
- **The Linux installer is untested.** Only the Windows agent path has been exercised.
- **One live-dependent test** (`test_scenario_11`) requires a container on port 5441 and
  is flaky when it is not up. Live tests mixed into the unit suite will produce
  intermittent CI failures and should be split into a separate marker.

---

## 8. Verification summary

| Check | Result |
|---|---|
| `--self-test` | 10/10 pass |
| `pytest tests/` | 98 passed, 7 skipped |
| Live 3-node Patroni cluster | `status 1`, 3/3 nodes, primary `pg-node3`, 2/2 streaming, timeline 64, 0 schema violations, 1.3s collect |
| SQL-only discovery, proxy disabled | Correct topology from all three nodes as seed, including both standbys following upstream |
| Refactor equivalence | Every stable payload key byte-identical pre/post |

New tests added in v6: `TestSqlOnlyDiscovery` (plain streaming pair with no proxy and no
Patroni; standby-follow; orphaned standby; proxy stats not contacted when no stats port
is configured) and `TestRunLevelRegressions` (the first `run()`-level tests in the
suite, using a stubbed driver so no database is needed).
