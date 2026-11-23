# TL meeting brief: postgres plugin v2

## Part 1: Questions to ask him

Each question comes with the reason it matters and what you'd suggest, so you aren't just asking. You're proposing.

### 1. "Can a plugin template be updated or pre-declared on the Site24x7 side?"

**Why:**
- All `postgres` monitors share one template, built the first time a monitor registers.
- Only metrics that have a real value in that run get in. We tested this: declaring them in `units`/`tabs` doesn't add them, and neither does sending `null`.
- We now send true values (real zeros, rates measured on the first poll), so 112 of 119 metrics register.
- The last 7 have no honest value until the event happens, for example "Last Archive Age" on a server that has never archived.

**Suggest:** if the backend can refresh a template when a new metric appears, or lets a plugin declare its metric list, we can close the last 7. If not, we accept them as known gaps. Don't fake values.

### 2. "With `use_agent_python=1` on Linux, which Python runs the plugin, and where should psycopg2 be installed?"

**Why:**
- Upstream's cfg says `use_agent_python=1`, but the upstream installer installs psycopg2 with the system `pip3`.
- On the Windows agent we tested, the bundled Python has no psycopg2, so it only worked with `use_agent_python=0`.

**Suggest:** whichever the agent team considers standard. The plugin works with both; it's a cfg and README line.

### 3. "Should a partial failure show in `msg` while the monitor is up?"

**Why:** if, say, `pg_ls_waldir` is denied, the plugin stays up and reports "1 queries failed: permission denied…" in `msg`. That's useful for troubleshooting, but some teams only want `msg` when the monitor is down.

**Suggest:** keep it. It's the only place the user sees which permission is missing.

### 4. "Can a plugin ship default threshold profiles?"

**Why:** the plugin reports facts plus a Health Code (0 OK, 1 node down, 2 no primary, 3 split brain, 4 manager disagrees). Alerts on lag, wraparound and connection saturation need thresholds.

**Suggest:** if plugins can ship defaults: Cluster Health ≥ 1 is Trouble and = 2 is Critical; replay lag > 60 s is Trouble; XID wraparound ≥ 70 % is Trouble. Otherwise we document them in the README.

### 5. "What happens to the other intern's `postgres_cluster` plugin (PR 442, merged)?"

**Why:** v2 `postgres` covers clusters itself. Two plugins doing overlapping jobs will confuse customers.

**Suggest:** deprecate `postgres_cluster` once v2 ships, with a README note pointing to `postgres`.

### 6. "Are PostgreSQL 9.6+ and Python 3.6+ acceptable minimums?"

**Why:** v1 nominally supports older versions. 9.6 is the first version with the views needed to see replication, and every version from 9.6 to 18 is tested.

**Suggest:** yes. Older servers get a clear "unsupported version" message, not broken data.

### 7. "Does Patroni's REST API need HTTPS or authentication support?"

**Why:** v2 reads Patroni over plain HTTP, and only when `patroni_port` is set. Some Patroni setups enable TLS or basic auth.

**Suggest:** ship HTTP now, and add `patroni_scheme` and credentials if customers ask.

### 8. "How should the PR be reviewed? One PR replacing the `postgres` folder?"

**Why:** the repo's Copilot reviewer applies a fixed rubric. A self-review against it is done; a thorough one is planned before the PR.

---

## Part 2: What he's likely to ask you, with answers

**"Why not read the nodes from HAProxy, like I said?"**
HAProxy doesn't know who the primary is. It health-checks Patroni and caches the answer. If discovery depends on the proxy, a broken proxy looks like a failover. So v2 uses the proxy as a way *in* (point `host` at the HAProxy write port and you reach the primary) and asks PostgreSQL itself who is primary. That works with or without HAProxy, since not everyone runs it.

**"How does it find every node from one IP?"**
- From a primary: `pg_stat_replication` lists every standby attached to it.
- From a standby: `pg_stat_wal_receiver` names its primary, and the plugin follows it.
- With a cluster manager, its registry: Patroni's `/cluster` (if `patroni_port` is set), `repmgr.nodes`, Citus `pg_dist_node`, pgpool `SHOW POOL_NODES`, pg_auto_failover's monitor.
- Roles always come from PostgreSQL (`pg_is_in_recovery()`), not from the manager. If they disagree, that's Health Code 4.

**"What if customers have an agent on every node? Won't we get duplicates?"**
Each monitor shows its own node in full, plus the same light cluster view. A customer upgrading from v1 (each server monitoring `localhost`) keeps exactly what they had and gains the cluster view. Other nodes get one light query each, not the full set. For new installs, the README recommends one agent pointed at one cluster address.

**"Is it really backward compatible?"**
- The cfg keys are the same as v1, and every v1 metric name and both v1 tables are kept, including the misspelled `Tranasctions_and_Session_per_Database`.
- Proven on the real Windows agent: v2 dropped over a live v1 install with its encrypted cfg untouched, and it came up with all the old names.
- The Linux installer upgrades in place and keeps the cfg byte-for-byte; that's tested in a container.

**"You said never fake values, but you send zeros."**
Only where zero is the truth:
- archive counts when archiving is off
- replay lag on a primary
- WAL generated on a standby
- scans on a database with no tables

Anything without an honest value is left out, never sent as 0. First-poll rates are a real 5-second measurement, checked against PostgreSQL's own counters (within about 10%).

**"How did you test it?"**
- **Discovery:** 8 cluster types: standalone, streaming, Patroni, repmgr, pgpool, Citus, pg_auto_failover, and logical/multi-master.
- **Versions:** PostgreSQL 9.6, 12, 13, 14, 16, 17 and 18. Python 3.6 checked.
- **Failure scenarios:** standby down and back, primary down, promotion, and split brain (old primary returning writable). It also caught a real pgpool fault where the pool had detached a live primary.
- **Rates:** compared against pgbench.
- **Real agent:** checked the Windows agent's actual payloads, and checked the console through the Site24x7 API (read-only).
- **Unit tests:** 42.

**"What load does it put on the database?"**
About 30 read-only queries per poll, in a read-only transaction, with a 5 s statement timeout. A poll takes 0.1 to 0.5 s; the first poll takes about 5 s longer because of the rate sample. Each other node gets one connection and one query. The whole poll is budgeted at 40 s, under the agent's 50 s limit.

**"Security?"**
- It needs `pg_monitor` only, never superuser.
- Every session is read-only.
- Passwords are scrubbed from any message.
- State and logs stay in the plugin folder.
- The log file name can't point outside the plugin folder.

**"Why is it ~2,000 lines when v1 is 313?"**
More than a third is the metric catalogue: each metric is one entry of SQL plus its version range. The logic is a small engine plus one small adapter per cluster type, and adding a metric or a cluster type means adding an entry or an adapter. v6 was about 5,000 lines; v2 does more in less than half of that.

**"What doesn't it do yet?"**
- A failover hasn't been seen end-to-end in the console; that's planned for tomorrow.
- It hasn't run on a real Linux agent (only the installer, in a container).
- 7 metrics can be missing from the template (see question 1).
- pg_auto_failover data nodes were not tested directly; they're covered as streaming replication.
- Node names can differ between monitors on plain streaming (hostname vs IP).
