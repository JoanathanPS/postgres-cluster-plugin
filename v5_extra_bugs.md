# v5 Plugin — Bug Recheck (full re-read from line 1)

**Reviewed:** `postgres_cluster/postgres_cluster.py` — **5,096 lines**, branch `v5`, working tree
(uncommitted, on top of `1702da8`). md5 `6de3e262d4b5476fb60601579234761c`.

This supersedes the earlier version of this file. I re-read the whole file from line 1 and did
not reuse the previous findings. The file grew ~200 lines since then and **most of what I
reported before has been fixed** — the table below records that, then the new findings follow.

**Verification:** `--self-test` passes (10/10). `python -m pytest tests/` → **91 passed, 7 skipped**.
Findings F1 and F2 were reproduced by running `run()` against a stubbed psycopg2; the rest are
from reading, and each says which.

---

## 1. What is now fixed

### The 8-item fix plan — all applied

| Plan item | Where | State |
|---|---|---|
| 1. `datfrozenxid` on `pg_stat_database` | 3787 | **Fixed** — subquery against `pg_database WHERE NOT datistemplate` |
| 2. PG17 `pg_stat_bgwriter` | 4249-4262 **and** 2523-2532 | **Fixed in both places** — `pg_stat_checkpointer` + `pg_stat_io`. The compat copy at 2528-2529 now supplies `buffers_backend`/`buffers_backend_fsync` from `pg_stat_io` too |
| 3. `Failover_Age_s` permanent WARN | 872 + 1349 + 1809 | **Fixed properly** — guard is now `0 < failover_age_s <= window`, the catalogue carries `"default": -1`, and `get_empty_payload()` honours a per-metric `default` |
| 4. `patroni_tl: 1` fabricated | 2370, 2419 | **Fixed** — both proxy specs now `patroni_tl: 0`, so `pg_control_checkpoint()` is queried |
| 5. Hardcoded `"pg1"` | 4711-4712 | **Fixed** — falls back to `Primary_Node` then `cluster_host` then `"cluster node"` |
| 6. Availability semantics | 4744, 4821 | **Fixed in both branches** — `status = 0` only on primary down/absent, split brain, auth failure, conn failure or unsupported version. Degraded replication now stays `status = 1` with `Cluster_Health = 1/2` |
| 7. Plain-language `Health_Reason` | 4795-4815 | **Done** — composes "`<node> stopped; failed over to X; N of M nodes up; …`" (but see **F2**, which empties it) |
| 8. Regression tests | `tests/` | 91 passing (but see the test-gap note under **F1**) |

### Findings from my previous pass — fixed

| Previous finding | Now |
|---|---|
| Trailing-digit regex matched the port (`172.30.0.12:5432` → index 5431) | **Fixed** — 368-375 strips the port and skips IPv4 before matching |
| `resolve_mapped_endpoint` port-only form wrong without `cluster_host` | **Fixed** — 354, 365 now `cluster_host or "127.0.0.1"` |
| Down ex-primary counted as writable → silent "multi_master", split-brain check off | **Fixed** — 4661 now filters `status == STATUS_UP` |
| Primary-down + standby-up on PG14+ emitted untabbed metrics | **Fixed** — `compat_client_version` tracked separately (4377/4387/4407), injection gated on `compat_metrics` (4841), tablist entries added only `if m_item in compat_metrics` (4859) |
| Schema violations clobbered `msg` | **Fixed** — 4901-4906 no longer overwrites an operational message (but see **F5**) |
| 41 compat metrics zero-filled when nothing reachable | **Fixed** — 2496-2497 returns `{}, [], []` before seeding defaults |
| `temp_bytes` / `dead_tuples` / `xact_age_s` structurally 0 | **Fixed** — now queried per node at 3439-3451 |
| `Queries_Run` fabricated (`+= 4`) | **Fixed** — `NodeClient.query_count` (490, 615) summed at 3493 |
| `fetch_haproxy_stats` fired before the isolation check | **Fixed** — 3090 gates on `discovery_port > 0 and seed_host` |
| Blind credentialed probe to 5000/5500 | **Fixed** — 3102-3107 only tries them when HAProxy stats actually answered; plus a `system_identifier` cross-check at 3664-3676 rejects alien nodes |
| `discovery_uri` / `read_port` parsed but unused | **Fixed** — wired at 3094/3122 and 2424-2434 |
| Sort put DOWN nodes first (healthy ones truncated at 25) | **Fixed** — 3679-3683 live primary → live standbys → down primary → down |
| `Replication_Links` duplicate row names | **Fixed** — 4541-4545 prefers `application_name` and de-duplicates |
| `Nodes_Omitted` row unsanitised / ragged | **Fixed** — 4503 `safe_name`, 4514 `sync` added |
| `Wait_Events` / `Database_Stats` fabricated fallback rows | **Fixed** — both now emit nothing when there is no data (4603-4634); `Wait_Event_Top` = `"none"` (4368) |
| Patroni lag discarded | Now used — but **incorrectly**, see **F3** |

Also improved since last pass: rate deltas are gated on `is_same_primary` so counters are not
differenced across a failover (3809/3813/3895/4279/4322); the archiver only warns on *new*
failures via `last_failed_time` (3991, 4013); PG 9.6 fallbacks added for `pg_xlog_*`
(2337, 3408, 4202); `has_database_privilege` guards added to the size queries (2627, 4041, 4222).

---

## 2. New findings

### F1 — CRITICAL: `UnboundLocalError` turns one failed query into a total false outage

**Confirmed by execution. — FIXED, see §4.**

`prev_primary_name` and `is_same_primary` are assigned at **3808-3809**, which is *inside*
`if row:` (3793). They are then read **outside** that block:

* **3895** — `if is_same_primary and prev_counters and 0.5 <= dt <= 900.0:`
* **4012** — `prev_arch_failed = safe_int(prev_counters.get("arch_failed", …))`
* **4279** — `if is_same_primary and 0 < dt <= 7200:`
* **4322** — `if is_same_primary and 0.5 <= dt <= 900.0:`

So if the section-3.1 aggregate query errors, `row` is `None` and the next read raises.
Reproduced by stubbing psycopg2 and making only that one query raise `42501`:

```
File "postgres_cluster/postgres_cluster.py", line 3895, in run
    if is_same_primary and prev_counters and 0.5 <= dt <= 900.0:
UnboundLocalError: cannot access local variable 'is_same_primary' where it is not associated with a value
```

`main()`'s blanket handler catches it and emits:

```json
{"plugin_version":1,"heartbeat_required":true,"status":0,
 "msg":"CRITICAL: Unhandled plugin exception: cannot access local variable 'is_same_primary' …"}
```

**Impact:** `status: 0`. Every metric and every child table is lost for that poll, and the
monitor shows a full outage while PostgreSQL is serving normally — the exact failure mode plan
item 6 was written to eliminate. One unrelated query error escalates to a fabricated outage.

**Triggers:** the monitoring role losing `SELECT` on `pg_stat_database`/`pg_database`; the 3 s
`statement_timeout` firing; or the connection dropping between `connect()` and this query.

**Fix:** initialise `prev_primary_name = str(prev_state.get("primary_name") or "")`,
`is_same_primary`, `prev_counters` and `max_xid_age` *before* `row = active_client.query_one(db_sql)`,
and add the `elif active_client.last_error_class is not None: prune…` arm that every other
block in section 3 already has.

**Test gap:** the 91-test suite passes with this bug live. No test exercises a failing 3.1 query.

---

### F2 — HIGH: `Standbys_Expected` is counted from config, not from the cluster

**Confirmed by execution. — FIXED, see §4.**

Line **3913**: `payload["Standbys_Expected"] = max(len(node_specs) - 1, 0)`.

`node_specs` is what discovery/config produced, not what the primary reports. With one seed
address and a primary that has two live streaming standbys, my run produced:

```
msg           = HEALTHY c0: Cluster healthy: 1/1 nodes active (timeline 1) | primary: pgnode1 | 2/0 streaming (lag: 0.0s)
Health_Reason = 1 of 1 nodes up
```

Three consequences:

1. **The operator sees `2/0 streaming`** in the monitor message (built at 827 and 950).
2. **The new plain-language `Health_Reason` silently drops the standby clause** — line 4809
   gates it on `expected_standbys_count > 0`, so plan item 7's whole point ("…, 1 of 2 standbys
   streaming") disappears in exactly the single-endpoint setup v5 is designed around.
3. **CRITICAL check #3 is disabled.** Line 776 is `if expected_standbys > 0 and streaming_standbys == 0`.
   With `expected_standbys == 0`, a primary that loses *every* standby never raises
   `HEALTH_CODE_NO_STANDBYS_STREAMING`. `Standby_Disconnect_Flag` (4152) is dead for the same reason.

**Fix:** take the expected count from the maximum of the configured standbys, the standby rows
actually discovered, and the peak `Standbys_Streaming` persisted in state — or straight from
`pg_stat_replication` when the node count is 1.

---

### F3 — HIGH: Patroni/proxy lag is in **bytes** but is written into `replay_lag_s` (**seconds**)

**Confirmed by reading.**

Lines **3454-3455**, for a node that failed to connect:

```python
if spec.get("patroni_lag") is not None:
    row_res["replay_lag_s"] = round(safe_float(spec.get("patroni_lag")), 2)
```

`patroni_lag` holds **bytes** on both paths that populate it:

* Patroni `/cluster` members — the `lag` field is byte lag (`parse_patroni_member`, 2111-2119 → 3189).
* The HAProxy/proxy path — the SQL at **2326** is
  `pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_lag_bytes`, read at 2351 as
  `lag_b`, then stored as `"patroni_lag"` at **2371**.

`replay_lag_s` is declared `"s"` in `TABLE_UNITS` (1138) and emitted in `Cluster_Nodes` (4489).
A stopped standby 4 MB behind is charted as **4,194,304 seconds** of replay lag. It is excluded
from the `Max_Replay_Lag_s` roll-up (3702 filters `STATUS_UP`), so it does not trip the lag WARN,
but it is wrong on the per-node chart and in `First_Attention_Reason`.

**Fix:** assign to `row_res["replay_lag_bytes"]`, and rename the spec key to `patroni_lag_bytes`
so the unit is unambiguous at every call site.

---

### F4 — MEDIUM: compat metric names are taken from server column names, unchecked

**Confirmed by reading; reproduced incidentally.**

`collect_official_compat` derives metric names from whatever the server returns —
line **2572**: `m_name = col.replace("_", " ").title()` — and they are emitted verbatim by
`payload.update(compat_metrics)` (**4887**) with no check against `OFFICIAL_COMPAT_UNITS`.

Any column name outside the expected set becomes a metric with **no unit and no tab**, i.e. an
`EMITTED_METRIC_NO_TAB` violation. My harness hit exactly this (7 violations) when the stub
returned differently-named columns.

With stock PostgreSQL every `SELECT` aliases its columns, so this is latent rather than live.
It is unguarded against PostgreSQL forks, a pooler sitting in front, and future column renames —
and the PG17 branch already shows how fast those aliases change.

**Fix:** `if m_name in OFFICIAL_COMPAT_UNITS or m_name == "Server Version"` before assigning;
count anything else as a warning.

---

### F5 — MEDIUM: schema violations are now completely silent

**Confirmed by reading.**

The clobbering is fixed, but the replacement never fires. Lines **4900-4906**:

```python
violations = validate_output(payload)
if violations:
    all_warnings.append(f"schema: {'; '.join(violations[:2])}")
    payload["Collect_Warnings"] = len(all_warnings)
    if payload.get("status") == STATUS_UP and not payload.get("msg"):
        payload["msg"] = f"schema: …"
```

`payload["msg"]` is unconditionally set by the health block just above (4740 / 4793), so
`not payload.get("msg")` is **always false** and the branch is dead. The appended warning text
is never read either: the `metric_unavailable` scan that surfaces warnings into `msg` runs at
**4827**, *before* this append.

So a schema violation produces no message, no metric and no log line — only
`Collect_Warnings` ticking up by one, with no way to tell what it was. Given F1 and F4 both
surface as schema/exception problems, this is the difference between a five-minute diagnosis and
an afternoon.

**Fix:** append to `msg` the way the `metric_unavailable` note does, or add a dedicated
`Schema_Violations` count metric plus a `Schema_Reason` string.

---

### F6 — LOW: the Patroni-discovery guard is always true

Line **3137**: `if not node_specs or patroni_ports or patroni_port:`

`patroni_port` is `int(merged.get("patroni_port") or 8008)` (**3033**), so it is never 0 and the
condition never evaluates false. The `not node_specs` short-circuit is dead: Patroni REST
discovery runs on every poll even when HAProxy already returned the complete topology, costing
an HTTP probe per candidate per cycle.

If that is deliberate (to keep `/history` fresh for `Failover_Age_s`) the condition should just
be removed and the intent commented; as written it reads like a guard that guards nothing.

---

### F7 — LOW: index guards that cannot work

Lines **3933-3934**:

```python
streaming_count = len([r for r in rep_rows if str(r[2] if len(r) > 2 else r[1]).lower() == "streaming"])
sync_count      = len([r for r in rep_rows if str(r[3] if len(r) > 3 else r[2]).lower() in ("sync","quorum")])
```

The `len(r) > 2` guard falls back to `r[1]` without checking `len(r) > 1`; a 1-column row raises
`IndexError` (I hit it with a deliberately malformed mock). The real `SELECT` always returns 9
columns, so it is unreachable — which makes it dead defensive code that implies a safety it does
not provide. Same shape at 4446-4452. Either index directly or guard correctly.

---

### F8 — LOW / not a defect: `&` in a tab name is deliberate

`TAB_ORDER` line **1126** contains `"Capacity & WAL"`, the only tab key with a character outside
`[A-Za-z0-9 ]`. **This is a known, deliberate choice** — `tests/test_plugin.py:286-289` asserts
no tab name contains `&` *except* `"Capacity & WAL"`, so it was considered and carved out.

Nothing to change in the code. The only open question is external: tab names become JSON keys
the Site24x7 UI renders and freezes at first registration, so confirm in the console that `&`
round-trips before this template is registered under a new plugin name — tabs cannot be altered
afterwards. If there is any doubt, `"Capacity and WAL"` costs nothing.

---

### F9 — LOW: a node that has never connected accumulates no history

Lines **3593-3598**: in the DOWN branch, `new_state["nodes"][alias] = entry` sits *inside*
`if "ts_ok" in entry:`. A node that has never once connected therefore never gets its `ts_fail`
or `last_reason` persisted, so a permanently misconfigured endpoint shows no history across
polls. The UP branch persists unconditionally (3592). Probably deliberate (it keeps junk aliases
out of state and feeds the offline-row TTL at 3635) — worth a comment either way.

---

## 3. Priority

| # | Severity | Finding | Verified | State |
|---|---|---|---|---|
| F1 | **CRITICAL** | `UnboundLocalError` → false total outage | by execution | **FIXED** |
| F2 | **HIGH** | `Standbys_Expected` from config; disables the zero-standbys CRITICAL and empties `Health_Reason` | by execution | **FIXED** |
| F3 | **HIGH** | byte lag emitted as seconds | by reading | open |
| F4 | MEDIUM | compat metric names unvalidated | by reading | open |
| F5 | MEDIUM | schema violations silent | by reading | open |
| F6 | LOW | dead discovery guard | by reading | open |
| F7 | LOW | incorrect index guards | by reading | open |
| F8 | — | `&` in tab name is deliberate; console check only | n/a | not a defect |
| F9 | LOW | no history for never-connected nodes | by reading | open |

---

## 4. Fixes applied (F1 and F2)

Both were in `run()` and both undermined plan items 6 and 7, which had just been implemented.

### F1 — `postgres_cluster/postgres_cluster.py`

* **3791-3794** — `prev_primary_name`, `is_same_primary`, `prev_counters` and `max_xid_age` are
  now resolved *before* `row = active_client.query_one(db_sql)`, so the WAL-rate, archiver,
  checkpoint and scan sections can never read them unbound.
* **3807-3809** — the now-duplicate assignments inside `if row:` were removed; `prev_ts` and `dt`
  stay local to the rate calculation.
* **3848-3863** — added the `elif active_client.last_error_class is not None:` arm that every
  other block in section 3 already had. It prunes the 15 metrics the aggregate feeds
  (`Primary_Connections`, `Active_Sessions`, the five `*_s` rates, `Blks_Read_s`, `Blks_Hit_s`,
  both cache-hit ratios, `Primary_XID_Age`, both wraparound percentages), sets
  `Rate_Warmup_Flag = 1` and appends a `metric_unavailable` warning — pruning rather than
  zero-filling, consistent with the no-fabricated-values rule.

Behaviour with only that query failing, measured:

```
status        = 1            (was: 0, "Unhandled plugin exception")
msg           = HEALTHY c0: Cluster healthy: 1/1 nodes active … | metric_unavailable: Primary_Connections (insufficient_privilege)
metric count  = 144          (was 159: the 15 affected metrics are dropped, not zeroed)
validate_output violations = 0
```

### F2 — `postgres_cluster/postgres_cluster.py`

* **3927-3938** — `Standbys_Expected` is now
  `max(configured_standbys, discovered_standbys)`, where `configured_standbys` is the old
  `len(node_specs) - 1` and `discovered_standbys` counts node rows whose role is
  `ROLE_STANDBY`, `ROLE_DELAYED`, `ROLE_CASCADING` or `ROLE_STANDBY_LEADER`.
* **3961-3966** — after `Standbys_Streaming` is known it is folded in:
  a standby the primary is actively streaming to is by definition expected.

Deliberately **not** persisted as a high-water mark in state: that would catch a standby that
vanished from both config and `pg_stat_replication`, but it would also pin the expected count
high forever after an intentional scale-down, producing a permanent WARN that cannot be cleared.
The two live sources cover the realistic cases — a stopped standby keeps `ROLE_STANDBY` from
state for an hour (3468-3471) and stays in `node_specs` from Patroni/`address_map` beyond that.

Measured on one seed address with two streaming standbys:

```
msg           = … | primary: pgnode1 | 2/2 streaming (lag: 0.0s)     (was "2/0 streaming")
Health_Reason = 1 of 1 nodes up; 2 of 2 standbys streaming           (was "1 of 1 nodes up")
Standbys_Expected = 2                                                 (was 0)
```

`HEALTH_CODE_NO_STANDBYS_STREAMING` (line 776) is therefore live again.

### Regression tests

Added `TestRunLevelRegressions` to `tests/test_plugin.py` — the first `run()`-level tests in the
suite, with a stubbed psycopg2 so no database is needed:

* `test_core_aggregate_failure_does_not_crash_or_fake_an_outage` — asserts `status == 1`, no
  exception text in `msg`, the affected metrics pruned rather than zeroed, the
  `metric_unavailable` note present, and `validate_output() == []`.
* `test_standbys_expected_reflects_reality_not_just_config` — asserts `2/2`, the standby clause
  in `Health_Reason`, and `Standby_Disconnect_Flag == 0`.
* `test_zero_standbys_streaming_is_critical_when_standbys_are_known` — guards the corollary.

**Suite: 94 passed, 7 skipped** (was 91/7). `--self-test`: 10/10. Both defects were reproduced
in this working tree *before* the fix using the same stub mechanism the tests use, so the tests
are known to catch the regressions.

F3 through F7 and F9 are untouched.
