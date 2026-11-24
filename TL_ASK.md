# TL questions: answers and next steps

## Answered

1. **Template gaps → TL: "pre-declare them as zero, nothing wrong with that." Done.**
   - **Why it has to happen at registration:** Site24x7 builds a monitor's chart layout once, when the monitor first registers, and only from metrics that have a value then. A metric that appears later is never added; we tested that.
   - **What v2 does:** every metric now has a value from the first poll, so every metric gets a chart. The 7 that used to be missing get a safe stand-in until their event happens:
     - Last Archive Age, Last WAL Message Age, Last Subscription Message Age, Oldest Table Vacuum Age → **0** ("nothing pending"; lower is better, so it never alerts)
     - Cache Hit Ratio, Index Hit Percent → **100 %** (no reads yet means no misses; a 0 % hit rate would trip every cache alert)
     - Last Failover Age → **time since monitoring began** ("no failover for at least this long"; 0 would read as "just failed over")
     - WAL Written on a standby → **0**, kept out of rate maths so a later promotion doesn't show a fake WAL spike
   - **Where it's documented:** the README has the same table.

2. **Minimums → TL: "whatever works."** PostgreSQL 9.6+ and Python 3.6+ stay.

3. **Old metric names → TL: keep both, the old metrics plus the new ones.**
   - **v2 already does this.** Every v1 name is still sent exactly as before ("Total Commits", "Checkpoints Req", the misspelled `Tranasctions_and_Session_per_Database`, and the rest), and the new metrics are added next to them. Existing alerts and charts keep working.
   - **Nothing to change**, unless he meant also sending a cleaned-up copy of each old name. Confirm with him.

4. **Default thresholds → TL: "customers do that, a plugin can't."**
   - **Confirmed by Site24x7's plugin docs:** thresholds are set per monitor in the console ("Threshold and Availability"). A plugin cannot ship threshold profiles.
   - **Our side:** the README lists recommended thresholds. The Health Code covers what only the plugin can judge: no primary, split brain, node down.

## Patroni REST API (research done)

From Patroni's documentation (4.1.5) and the main distributions:

| Setup | What it means for us |
| :--- | :--- |
| Username/password (`restapi.authentication`) | **Only protects the endpoints that change things** (switchover, restart). The read we use, `GET /cluster`, needs no password. We don't need username/password support. |
| TLS (`certfile`) | The API becomes HTTPS. **Supported** (`patroni_scheme=https`). |
| Self-signed certificate | **Supported** (`patroni_verify=false`). |
| Client certificate, `verify_client: optional` | Only demanded on the changing endpoints, so reads still work. |
| Client certificate, `verify_client: required` | Demanded on **every** call, which blocks our read. **Not supported yet.** The plugin then falls back to SQL discovery: it still works, but stopped members aren't seen. |

**What real deployments use:**
- **Plain VM installs (Patroni docs, tutorials):** HTTP.
- **Crunchy PGO (Kubernetes operator):** HTTPS, `verify_client: optional`. Works.
- **Zalando Spilo (Kubernetes):** HTTPS, generating a self-signed certificate if none is given. Works with `patroni_verify=false`.

**Suggest:** what's there now covers all three. Add client-certificate options (`patroni_certfile`, `patroni_keyfile`) only if a customer runs `verify_client: required`. A `patroni_cafile` option (verify against the cluster's own CA instead of switching verification off) is small and worth adding.

## Still to ask

5. **Python (`use_agent_python`): answered by testing on a real Linux agent (2026-11-24).**
   - **Linux (Full-Stack agent 22.3.01):** with `use_agent_python=1`, the agent doesn't start a separate Python. It loads `postgres.py` as a module inside its own process and calls `run(param)`, which is why the plugin keeps v1's `run(param)` entry point.
     - The agent's own Python (3.11) **already bundles `psycopg2`**, so the customer installs nothing. Verified: 8 monitors, one per cluster type, all up.
     - The installer now detects the bundled driver and skips installing it.
   - **Windows agent:** its Python has no `psycopg2`, so `use_agent_python=0` plus the server's own Python (with `psycopg2-binary`) is what works there.
   - **Decision:** ship `use_agent_python=1` (upstream default, right for Linux). The README tells Windows users to set `0`.
   - **Worth telling him:** the Linux agent writes each plugin's cfg parameters, including the plain-text password, into `logs/details/plugins.txt` when it loads the plugin. That's the agent's behaviour, not the plugin's, but the agent team may want to know.

6. **Missing permissions (explain to him, then ask once-or-repeat):**
   - **Who it happens to:**
     - **Every v1 customer who upgrades.** The old v1 installer told customers to grant `pg_read_all_stats`, not `pg_monitor`. With only that role, PostgreSQL won't let the user read the WAL directory or the archive status folder, so WAL Directory Size, WAL Files and Archive Ready Files can't be collected. Everything else works.
     - **Security teams that only allow a bare login user.** Some companies won't grant `pg_monitor` at all.
     - **Managed databases** (Amazon RDS, Azure, Google Cloud SQL), which block some of PostgreSQL's file-reading functions even for admin-like users.
   - **What v2 does about it:**
     - The plugin keeps running, and only the blocked metrics are left out.
     - `msg` says once which metrics are blocked and that granting `pg_monitor` fixes it: on the first poll, when something new gets blocked, and when it's fixed.
     - The **Permission Gaps** count is sent every poll, so anyone who cares can set a threshold. Nobody gets the same text every 5 minutes.
     - It isn't counted as a failure. **Failed Queries** stays for real errors such as timeouts.
   - **The only question:** is "once" right, or should the note repeat now and then, for example daily?

7. **Linux agent test: done (2026-11-24).**
   - **Setup:** a real Site24x7 Full-Stack Linux agent (Debian 13 container, server `pg-linux-agent`). The plugin was installed with our installer, and one cfg section was added per cluster type: standalone, streaming, Patroni, repmgr, logical, pgpool, Citus and pg_auto_failover.
   - **Result:** all 8 registered and are up. The four checked first registered the **complete** template (0 metrics missing).
   - **Installer bug found and fixed:** current agents report "full-stack agent service", which the old check (copied from the v1 installer) didn't recognise. It would have told every customer on a current agent that no agent was installed.

8. **Renamed metrics: can Site24x7 carry the old chart history into the new name?**
   - **What he asked for:** use the new, clean names, but keep the old charts' data, so a renamed metric's chart starts with its history already in it.
   - **What the plugin can and can't do:**
     - The plugin only sends "metric name = value, right now". Site24x7 stores history on its side, filed under the metric's **name**.
     - A new name is a brand-new metric on Site24x7's side, with an empty chart. Nothing the plugin sends can say "this is the old metric, renamed".
     - Sending both names keeps the old chart alive, but its history stays on the old chart and doesn't move into the new one.
   - **So history can move only if Site24x7's backend does it** (renaming the metric, or merging the old metric's data into the new one).
   - **Ask:**
     - "Can Site24x7 rename a plugin metric, or merge an old metric's history into a new one, when the plugin version goes from 1 to 2?"
     - "Has it been done for another official plugin?"
   - **If yes:** rename to the clean names, give them a rename list (old → new), and the history moves on their side.
   - **If no:** for each metric, choose between keeping the old name (history kept, old name stays) and renaming (clean name, history starts fresh). In the meantime we can send both names for one version, so nobody's alerts break, then drop the old names in v3.
   - **Renames we'd propose:**
     - `Tranasctions_and_Session_per_Database` → `Transactions_and_Sessions_per_Database` (misspelled)
     - `Checkpoints Req` → `Checkpoints Requested`
     - `Maxwritten Clean` → `Background Writer Stops` (the old name is unclear)
     - `Cache Hit Ratio` (0–1) → `Table Cache Hit Percent` (0–100 %), so it uses the same % as the other metrics
     - Names that are already fine (for example "Total Commits") stay unchanged.

## pg_monitor: why the plugin asks for it (explain if asked)

- **What it is:** PostgreSQL's built-in read-only monitoring role, added in PostgreSQL 10. It lets a user read all statistics and internals without any right to change data or settings.
  - Docs: https://www.postgresql.org/docs/current/predefined-roles.html
- **What it contains:** `pg_read_all_stats` + `pg_read_all_settings` + `pg_stat_scan_tables`, plus permission to run the file-listing functions (`pg_ls_waldir`, `pg_ls_archive_statusdir`).
- **What breaks without it:**

  | A normal user can't… | So the plugin… |
  | :--- | :--- |
  | see other users' queries, state and wait events in `pg_stat_activity` | undercounts Active Queries, Blocked Sessions, Longest Transaction, Wait Events and Top Queries |
  | list the WAL directory or the archive status folder | can't collect WAL Directory Size, WAL Files or Archive Ready Files |
  | read every replication detail (`pg_stat_replication`, `pg_stat_wal_receiver`) | may have weaker cluster discovery (standby addresses and lag can be hidden) |
  | read settings such as `shared_preload_libraries` | finds it harder to detect repmgr or pg_auto_failover (a weaker fallback is used) |

- **Why not superuser:** it can change and delete anything, and no security team should give that to a monitoring tool. `pg_monitor` is the least privilege that still sees everything. Datadog and pganalyze ask for the same role.
- **Why v1 didn't need it:**
  - v1 is old: it predates PostgreSQL 10, where `pg_monitor` was introduced.
  - v1 only read database-wide counters (`pg_stat_database`, `pg_stat_bgwriter`), which any user can read.
  - It didn't look at the WAL directory, replication or other users' sessions, so a basic role was enough. Its README asked for `pg_read_all_stats`.
  - v2 reads much more (replication, WAL, sessions, cluster), so it needs the role made for monitoring.
- **What v2 does if it's missing:** it keeps running, leaves out only the blocked metrics, says so once in `msg`, and sends a "Permission Gaps" count every poll.

9. **Missing pg_monitor: how loud should the warning be?**
   - **Why it matters:** without `pg_monitor`, metrics are missing or partial (sessions undercounted, no WAL directory metrics, weaker discovery). Customers should notice.
   - **Why not make it an error (`status = 0`):**
     - `status = 0` means **"monitor down"**: the down alert fires, the monitor turns red, and it counts as downtime in availability reports.
     - But the database is up, and about 95 % of the metrics are arriving. A down alert for a permission setting is a false outage that pages the on-call engineer for nothing.
     - A down monitor also hides the data it did collect.
     - A plugin can only send up (1) or down (0). It has no "warning" state of its own. In Site24x7, warnings ("Trouble") come from thresholds on metrics.
   - **What v2 does today:** the note in `msg` appears once (and whenever the list changes), and the **Permission Gaps** count is sent every poll.
   - **Options to make it louder, without a false "down":**
     - **(a) Repeat the note every poll** instead of once. It's always visible and doesn't page anyone.
     - **(b) Recommend a threshold "Permission Gaps ≥ 1 → Trouble"** in the README. The monitor then shows **Trouble (yellow)**: not down, but needs attention.
     - **(c) Add a health code**, for example 5 = "monitoring incomplete: grant pg_monitor", shown next to node down and no primary. It's non-critical.
   - **Suggest:** (a) + (b), and (c) if he wants it on the health summary too. Never `status = 0`.
   - **Ask:** "Missing pg_monitor: note once, or every poll? Should it raise Trouble through a threshold or a health code?"
