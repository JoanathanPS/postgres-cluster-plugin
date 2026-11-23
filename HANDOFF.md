# postgres plugin v2: handoff (2026-11-23)

Read this instead of the old chat. The v6 handoff, research, docs and console evidence were removed from the working tree on 2026-11-23. They are on GitHub on branch `v6` and in local history.

## 1. Where things stand

- **What it is:** a replacement for the official Site24x7 `postgres` plugin. Plugin name `postgres`, `PLUGIN_VERSION = 2`.
- **Code:** `postgres/postgres.py` (single file, ~2,000 lines), `postgres/postgres.cfg`, `postgres/README.md`.
- **Tests:** `tests/test_postgres_v2.py`, 37 tests. Run with `python -m pytest tests -q`.
- **Branch:** `v7`. Not pushed, no PR (not ready).
- **v6 is gone from v7:** the `postgres_cluster/` folder and its tooling were removed. They are still on branch `v6`.
- **Decided with the TL:** no separate cluster plugin; replace `postgres`. Version stays 2 (deleting the monitor and template is fine while testing). Backward compatible: same cfg keys, every v1 metric name and table kept. Discovery works from one address; the user never lists nodes. Patroni is optional, used only if `patroni_port` is set.

## 2. Design

- **Catalogue (section 1 of `postgres.py`):** `QUERIES` (single-row SQL → metrics, version-gated with `Variant(min_ver, sql, fields)`), `TABLES` (child tables), `RATES` (per-second rates and per-poll deltas), `DERIVED`, `CLUSTER_TABLES`. To add a metric, add one entry; there is no new code path.
- **Engine rules:**
  - A failed, NULL or inapplicable query leaves its metric out; it never sends 0.
  - `status = 0` only for: driver missing, connect or auth failure, version below 9.6.
  - Rates need two polls of the same server process (`identity` = host:port plus postmaster start time).
- **Two layers per monitor:**
  - *This node:* full metrics for whatever `host:port` reaches.
  - *Cluster:* the Nodes, Replication_Links and Events tables, plus Health Code.
- **Adapters (section 6):** `detect(seed, ctx)` and `nodes(seed, ctx) -> ClusterView`. Order: Patroni → repmgr → pg_auto_failover monitor → Citus → pgpool → Logical → Streaming → Standalone.
- **Roles:** always from `pg_is_in_recovery()` when the plugin can reach the node. If the manager disagrees, that is Health Code 4.
- **Health codes:** 0 OK, 1 node down or not streaming, 2 no primary, 3 split brain, 4 manager disagrees. Cluster Health is 0/1/2.
- **Remembered nodes:** kept in the state file for 24 h and still probed. That is how a returning ex-primary is caught as split brain.
- **State:** `postgres/.state/<hash>.json`. Events log: `postgres/postgres_events.log`, written only when `logs_enabled`, sent via `applog`.

## 3. Verified so far (real servers)

- **Versions:** 9.6, 12, 13, 14, 16, 17 and 18 return status 1 with 0 failed queries. 9.5 is refused cleanly. Python 3.6 passes the unit tests and a live poll.
- **Discovery:** standalone, streaming (from the primary and from a standby), Patroni (switchover and leader kill), repmgr with witness, pgpool (it caught a real detached primary → code 4), Citus, the pg_auto_failover monitor, and a 3-node logical mesh.
- **Failover sequence:** down → recovered → no primary → promoted (timeline 1→2) → split brain. The events log matched.
- **Access:** login-only user, `pg_monitor` user, wrong password, unreachable host, `sslmode=require`, and `verify-full` refused on a self-signed certificate.
- **Rates vs pgbench:** commits and rows-updated rates match.
- **Real Windows agent:** v2 dropped over v1 with the customer's existing encrypted cfg gives availability 1, version 2, 90 metrics, old names present.
  - Six monitors run from one cfg: `[postgres]` (the original v1 cfg), standalone, streaming, patroni, repmgr, logical. All registered and send data.
  - The user saw several bugs in the console. **They are not written down yet. Get the list first (section 6).**

## 4. Test kit

**Test beds** (`environments/`, all Docker). The repo `.env` holds the streaming credentials; the others use `site24x7/site24x7` unless noted.

| Test bed | Reach from Windows | In-network host |
| :--- | :--- | :--- |
| standalone PG16 | 127.0.0.1:5450 | `tb-standalone-pg16` (network `tb-standalone_default`) |
| streaming (root `docker-compose.yml`) | 5432 primary, 5433 standby | `pg-primary`, `pg-replica` (`pg-cluster-site24x7_default`). Credentials: `.env` MONITOR_* |
| Patroni (`environments/patroni`) | PG 5441-5443, REST 8001-8003, HAProxy 5500 | `pg-node1..3`, `haproxy:5000`, REST 8008 |
| repmgr | 5461-5464 | `repmgr-node1..3`, `repmgr-witness` (`tb-repmgr_default`) |
| logical (`environments/docker/multimaster`) | 5451-5453 | `pg-mm1..3` (`pg-multimaster_default`) |
| pgpool | none | `pgpool:9999` (`tb-pgpool_default`) |
| Citus | none | `citus-coordinator`, user `postgres/pgpass` (`tb-citus_default`) |
| pg_auto_failover | none | `monitor`, user `autoctl_node`, db `pg_auto_failover` (`tb-pgaf_default`). Data nodes block outside access (hba). node1 has crashed in this bed. |

**Testing from Windows:** container IPs are not routable, so pass `address_map` (examples in the agent cfg below). Testing inside a network needs no map: `bash scripts/run_in_network.sh <network> --host <container> --username ... --password ...`. Build the runner once with `docker build -t pgplugin-runner scripts/runner`.

**Real agent (this PC):**
- **Folder:** `C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres\`. Writable without admin.
- **Service:** the plugin agent can't be restarted without admin. It notices a changed `.py` on its own ("Time Change" in the log) and re-registers.
- **Polls:** every 5 min.
- **Agent cfg:** `use_agent_python=0` and `redirect_output=1`. The agent's bundled Python has no psycopg2. The shipped cfg says `use_agent_python=1` to match upstream; this is an open question.
- **Sections installed:** `[postgres]` (original, encrypted) plus `[postgres-standalone]`, `[postgres-streaming]` (logs on), `[postgres-patroni]`, `[postgres-repmgr]`, `[postgres-logical]`. The agent shows them as `postgres-postgres-<x>`, so use short section names like `[patroni]`.
- **Backup of the original v1 `postgres.py` and encrypted cfg:** the session scratchpad `agent-backup/` folder (temporary). v1 is also at `reference/postgres/postgres.py`.
- **Logs:** `...\monitoring\Logs\Details\PluginLog.log` and `PluginRegisterLog.log`.
- **Exactly what the agent sends:** `bash scripts/agent_payloads.sh 6`. The agent wraps the output as `{availability, version, msg, data:{...}}`, with UTF-16 files that are deleted seconds after writing.

**Console:** site24x7.in, org account. View only; never delete or change anything there. The user does deletions.

## 5. Open issues and decisions

**Automated console check works, and is the first thing to run:** `python scripts/api_check.py --period 0`.
- **What it uses:** the Site24x7 REST API, read-only Self Client. Credentials are in `.env` as `S247_*` and are gitignored.
- **What it prints per monitor:** up/down, template size, registered metrics with no data in the period, and catalogue metrics missing from the template. Full responses go to `.api_reports/`.
- **Results at 17:20, 2026-11-23:**
  - All 6 monitors are up. Re-registering after the section rename fixed issue 0.
  - **Bug A (major), the template is missing 29 metrics.** All `postgres` monitors share one template, frozen from the first v2 payload (a primary with no user tables and archiving off). Missing: Replay Lag, Replay Backlog, WAL Receiver Connected, Last WAL Message Age, Last Failover Age, all archive metrics, Index/Heap/Cache Hit Ratio, Dead/Live Tuples, Sequential Scans, WAL Files/Directory Size, Checksum Failures, and others. Confirms issue 2.
    - **Tested on 2026-11-23:**
      1. The template is built only when a monitor registers fresh (a new monitor or plugin name). A changed `.py` or a service restart does not rebuild it while the monitors exist ("already registered").
      2. Declaring the full catalogue in `tabs`/`units` does not add keys (commit `1848d41`; registration at 17:33 still gave 119).
      3. Sending missing metrics as `null` does not add keys either. A fresh `postgres_nulltest` plugin registered 103 metrics, and the 38 nulls were all left out. Reverted.
    - **Conclusion:** a key enters the template only with a real value in the registration run.
    - **Decision needed (user/TL, not Claude):**
      - (a) accept an incomplete template, or
      - (b) send 0 where 0 is true (for example archive counts when archiving is off), or
      - (c) send placeholder 0 for everything at registration, which breaks the never-fabricate rule.
    - **Option (a) note:** register monitors so the richest node registers first; a standby with archiving and user tables covers the most.
    - **Console cleanup:** the `postgres_nulltest-Joana-PC.` monitor can be deleted.
  - **Bug B (minor), repmgr seeded at a standby has no Max Standby Replay Lag or Backlog.** `RepmgrAdapter` only gets links when the seed is the primary. Connect to the registry's primary for `replication_view` like `PatroniAdapter` does.
  - **Expected gaps, not bugs:** Buffers Backend on PG17, primary-only metrics on standby-seeded monitors, no standby lag on standalone.

0. **(Resolved by re-registering) Extra cfg sections receive no arguments (found 15:06, 2026-11-23).**
   - **What happens:** the agent passed `--host/--port/--username/--password/--db` only to the original `[postgres]` section. The five added sections ran with no arguments, so they used the defaults (`localhost:5432`) and are down.
   - **How it was confirmed:** a one-poll debug hook that logged argv names.
   - **Naming:** the agent registered the sections as `postgres-postgres-<x>`. They have since been renamed `[standalone]`, `[streaming]`, `[patroni]`, `[repmgr]`, `[logical]` in the agent cfg, but the agent still uses the old registered names. It reads sections at registration time.
   - **Next step:** the user deletes those five monitors in the console, or restarts the "Site24x7 Plugin Agent" service as admin. Then run `scripts/agent_payloads.sh 6` and check whether short section names now get arguments.
   - **If they still don't:** compare with upstream multi-instance plugins, the `[nginx-localhost]` style in the repo rubric.
   - **Code change worth making either way:** when the plugin gets no `--host` at all, put "no configuration received from agent" in `msg`, so the cause is obvious.
1. **Console bugs the user saw.** List them, then fix them.
2. **Template stability.** All `postgres` monitors share one template, and `finalize()` drops tab and unit entries for metrics not emitted that poll. If the template freezes at the first payload, metrics that only some monitors send (standby Replay Lag, Patroni rows) may never show. Check in the console. If confirmed, always send the full `tabs`/`units` from the catalogue. The repo rubric says every `units` key must exist in the data, so this needs a decision. Then the user deletes the template once and we re-register.
3. **`msg` is sent even when availability is 1,** for example "1 queries failed: permission denied for function pg_ls_waldir". Decide whether partial-failure notes belong in `msg`.
4. **Shipped `use_agent_python`:** 1 (upstream) or 0 (needed on this Windows agent).
5. **Node names can differ between monitors** on plain streaming (a hostname vs an IP). The Patroni, repmgr and pgpool adapters use the manager's names.
6. **Upstream installer** (`installer/Site24x7PostgresPluginInstaller.sh` in site24x7/plugins) is not updated yet.
7. **pg_auto_failover data nodes** were not tested directly (the bed's hba blocks it).

## 6. How to work efficiently (token budget)

- **Don't make the user report bugs by hand, and don't read the console in a browser.** Run `python scripts/api_check.py --period 0`:
  - **What it uses:** the Site24x7 REST API, read-only, with credentials in `.env`.
  - **What it shows:** each monitor's status, template, metrics with no data, and metrics missing from the template.
  - **Pair it with** `scripts/agent_payloads.sh`, which shows what was sent. The difference between the two is the bug list.
  - **Endpoints it uses:** `/monitors`, `/current_status/<id>` and `/reports/performance/<id>?period=0|1|2`. Per-metric points are in `chart_data`; `table_data` only summarises the first metric.
- **Verify fixes locally.** Run `python -m pytest tests -q`, then `scripts/run_in_network.sh` or direct runs with `address_map`, then `scripts/agent_payloads.sh` to confirm what the real agent sends. Most console bugs are payload bugs and show up there.
- **Copy the fixed file into the agent folder** (see section 4). It re-registers by itself; wait for one poll.
- **Commit per fix** on `v7`. Plain commit messages, no AI attribution.
- **Model:** Sonnet is fine for fixing listed bugs, since the code is catalogue- and adapter-shaped and fixes are local. Use Opus only for design calls such as issue 2.
