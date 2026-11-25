# TL questions

## Answered (brief)

1. **Template gaps → "pre-declare them, nothing wrong with that." Done.** Every metric has a value from the first poll. Until the event happens, the 7 that used to be missing get safe stand-ins (ages → 0, hit ratios → 100 %, Last Failover Age → time since monitoring began).
2. **Minimums → "whatever works."** PostgreSQL 9.6+ and Python 3.6+.
3. **Old metric names → "old charts are migrated in the backend, don't carry v1 baggage." Done.** Dropped Cache Hit Ratio, Heap Blocks Read/Hit and Index Rows Read/Fetched, which newer metrics cover. Fixed the `Tranasctions_…` table name. The README's "Upgrading from Version 1" table lists each old name and its replacement (see F for the backend side).
4. **Default thresholds → "customers set them, a plugin can't." Done.** No thresholds ship with the plugin. The Health Code covers what only the plugin can judge.
5. **`use_agent_python` → settled by testing.** The Linux agent's own Python already bundles `psycopg2`, so we ship `=1`. The README tells Windows users to set `0`. Worth mentioning: the Linux agent writes cfg passwords in plain text to `logs/details/plugins.txt`.
6. **Linux agent test → done (2026-11-24).** A real Full-Stack agent, with all 8 cluster types registered and up and complete templates. Found and fixed an installer bug: current agents say "full-stack agent service", which the v1 check didn't recognise.
7. **v1 migration and tabs → "customers upgrade one at a time when they choose to, so it doesn't matter." Done.** No backend migration is needed. The 16 running totals (Total Rows Inserted, WAL Written, Total Deadlocks…) are no longer sent; their Per Sec or New versions are. The plugin now sends 99 metrics. Tabs are now Summary + 8, all visible: Cluster, Replication, Activity, Transactions and Sessions, DB and IO stats, Vacuum and Wraparound, WAL and Archiving, BG Writer. The Plugin tab's 3 metrics moved to Summary. The README's upgrade table says the replacements are the nearest metrics, not equivalents.

---

## Still to ask

### 0. Ask first: hiding the Cluster and Replication tabs on a standalone server

**What's done (in v7, not committed, not in the PR):**
- On a standalone server the payload leaves out the **Cluster** and **Replication** tabs, everything in them, and Cluster Health and Nodes Up on Summary. It sends 6 tabs instead of 8.
- Exception: a standalone server with **replication slots** (for example a CDC tool) keeps its Replication tab, because an unused slot can fill the disk.
- Every cluster type still sends all 8 tabs.

**How Site24x7 handles it (tested on the Linux agent, 2026-11-25):**
- A plugin's tabs and charts are fixed by the **first monitor that registers**, and every monitor of that plugin shares them. One template per plugin per account.
- Removing tabs from a later monitor's payload doesn't hide them. The tabs stay and show "No Data" (test plugin `postgres_dicttest`).
- A second plugin version can't be used to split it: Site24x7 replied "Version (2) not available for the plugin. Update the version in the plugin script to 3".

**So it works when a customer's first postgres monitor matches the rest:**

| Customer | First monitor registered | What they see |
| :--- | :--- | :--- |
| Only standalone servers | standalone | 6 tabs, no empty tabs |
| Only clusters | cluster | all 8 tabs |
| Both, cluster added first | cluster | clusters fine; standalone shows 2 tabs of "No Data" |
| Both, standalone added first | standalone | **clusters have no Cluster or Replication tabs** |
| Starts standalone, later adds a standby | standalone | **the new cluster never gets its cluster tabs** |

The last two rows can only be fixed by Site24x7 rebuilding the template, which happens on the next plugin version release.

**The alternative:** always send everything; a standalone server sends true zeros (Replay Lag 0, Nodes Down 0) and the Cluster tab opens with `standalone | 1 of 1 nodes up | primary`. Nothing breaks for any customer, but standalone shows 2 extra tabs.

**All options compared:**

| Option | Standalone shows | Clusters show | Risk | Customer effort |
| :--- | :--- | :--- | :--- | :--- |
| **A. if/else in one plugin** (built in v7) | 6 tabs | 8 tabs, **if** a cluster registered first | Mixed customer whose first monitor is standalone: clusters lose their Cluster and Replication tabs | None, unless they hit the risk |
| **B. A + template delete as the fix** | 6 tabs | 8 tabs after the fix | **Order again:** deleting the template removes its monitors, and whichever re-registers first sets the new layout. To be reliable, add the cluster monitor first, wait one poll (5 min), then the standalone ones. Not yet tested. | **Manual:** delete the template, lose chart history, re-register (on Windows also remove and re-add the plugin folder). A README troubleshooting step, not normal use. |
| **C. Always send everything** | 8 tabs: true zeros, Cluster tab opens with `standalone \| 1 of 1 nodes up \| primary` | 8 tabs | None | None |
| **D. Two plugins: `postgres` + `postgres_standalone`** | `postgres_standalone`: 6 tabs | `postgres`: 8 tabs | None. Each plugin has its own template, so order doesn't matter. A standalone server that later gets a standby must move to `postgres` (the monitor message can say so). | Picks the plugin at install (installer asks). Same code: the plugin reads its own file name. |

**My recommendation:** D, which gives the clean standalone layout with no order risk; C if one plugin is a must. Site24x7 already splits plugins this way (`oracle` + `oracle_rac`, `redis` + `redis_sentinel`).

**What I need you to confirm:**
0. "Which option: A, B, C or D?"
1. "Is it OK to assume a customer registers one kind of server first, and accept that a mixed customer whose first monitor is standalone loses the cluster tabs on their clusters?"
2. If not: "Always send everything (zeros on standalone), or split into two plugins (`postgres` + `postgres_cluster`), as Site24x7 does with `oracle` + `oracle_rac` and `redis` + `redis_sentinel`?"
3. "Keep the Replication tab on a standalone server that has replication slots?"

### A. Missing `pg_monitor`: how should the warning work?

**Background:**
- `pg_monitor` is PostgreSQL's read-only monitoring role, added in PostgreSQL 10 ([docs](https://www.postgresql.org/docs/current/predefined-roles.html)). It's `pg_read_all_stats` + `pg_read_all_settings` + `pg_stat_scan_tables`, plus the WAL-directory listing functions.
- v1 didn't need it. v1 predates PostgreSQL 10 and only read database-wide counters, which any user can read. v2 also reads replication, WAL and other users' sessions.
- **Who lacks it:**
  - every v1 upgrade, because the v1 installer granted only `pg_read_all_stats`
  - companies that allow only a bare login user
  - managed databases (RDS, Azure, Cloud SQL), which block some file functions

**What breaks without it:**
- WAL Directory Size, WAL Files and Archive Ready Files can't be collected.
- Session metrics (Active Queries, Blocked Sessions, Wait Events, Top Queries) are undercounted.
- Cluster discovery can be weaker.

**What v2 does today:**
- It keeps running, and leaves out only the blocked metrics.
- `msg` names the blocked metrics and says "grant `pg_monitor`". It appears on the first poll, and again only when the list changes.
- A **Permission Gaps** count is sent every poll.
- It's not counted in **Failed Queries**, which stays for real errors such as timeouts.

**Why not `status = 0`:**
- Status 0 means *monitor down*: a down alert, a red monitor, and downtime in the availability report. The database is up and about 95 % of the data is arriving, so it would be a false outage that pages on-call for nothing.
- A plugin has no "warning" state of its own. Trouble (yellow) only comes from thresholds.

**Options to make it louder:**
- (a) Repeat the `msg` note every poll instead of once.
- (b) Recommend a threshold in the README: Permission Gaps ≥ 1 → Trouble.
- (c) Add Health Code 5, "monitoring incomplete", which counts as Trouble.

**My suggestion:** (a) + (b).

**Ask:** "Once or every poll? And should it raise Trouble, through a recommended threshold or a health code?"

### B. More renames: which ones?

**Background:**
- You said the backend migrates old charts, so renaming is fine. So far only the misspelled table has been renamed.
- Chart history is filed under the metric name, so each rename relies on that backend migration.

**Candidates:**

| Current name | Proposed | Why |
| :--- | :--- | :--- |
| `Checkpoints Req` | `Checkpoints Requested` | abbreviation |
| `Maxwritten Clean` | `Background Writer Stops` | internal PostgreSQL column name, meaningless to users |
| `Buffers Backend Fsync` and similar raw column names | plain-English names | same reason |

**Ask:** "Rename these too, or keep the v1 names apart from the typo?"

### C. v6's Primary tab: bring it back or not?

**Background:**
- v6 had a **Primary** tab with about 22 metrics: Primary_Up, Connections, Commits/s, WAL rate, Cache Hit, Checkpoints and so on, read from the primary even when the monitor pointed at a standby.

**Why v2 dropped it:**
- **Duplication.** If the monitor is on the primary, both tabs show the same numbers. It adds about 22 metrics to a roughly 120-metric template.
- **Load.** Every standby's monitor opened a second full session to the primary every poll, within the agent's 50 s limit.
- **Stale data.** v6 needed `Primary_Data_Age_s` and `Primary_Data_Stale` because it showed cached numbers when the primary couldn't be reached.

**What replaces it in v2:**
- **Primary Node** (who the primary is) and **Health Code 2** ("no reachable primary")
- the **Nodes** table, with connection %, uptime and lag for every node
- for full primary metrics: point `host` at the VIP or HAProxy write port, which follows failovers, or monitor the primary itself

**Ask:** "Is that enough, or do you want a small Primary tab back (about 5 key metrics: up, connections %, commits/s, WAL rate, longest transaction)?"

### D. Cluster fields on a standalone server

Replaced by question 0.

### E. Patroni: any setup we don't cover?

**Background:**
- Patroni's REST API (`GET /cluster`) is the only source that also lists *stopped* members. It's used only if `patroni_port` is set, it's read-only, and it has a 3 s timeout.
- If a call is refused, the plugin falls back to SQL discovery and stays up.

**Covered and tested:**

| Patroni setup | cfg |
| :--- | :--- |
| Plain HTTP (VM installs) | `patroni_port` |
| HTTPS (Crunchy PGO) | `patroni_scheme=https` |
| Self-signed (Zalando Spilo) | `patroni_verify=false` |
| Own CA | `patroni_cafile` |
| `verify_client: required` | `patroni_certfile` + `patroni_keyfile` |
| Proxy or ingress with a password | `patroni_username` + `patroni_password` |

`restapi.authentication` doesn't matter here: Patroni only asks for its password on endpoints that change something.

**Ask:** "Does any Zoho customer use a Patroni setup that isn't on this list?"
