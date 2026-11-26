# PostgreSQL plugin v2: what to know

- Code: branch `v7` of this repo. Upstream PR: https://github.com/site24x7/plugins/pull/467
- Plugin documentation: [`postgres/README.md`](postgres/README.md)

## 1. Site24x7 has to enable the plugin's layout

The plugin uses an 8-tab layout: Cluster, Replication, Activity, Transactions and Sessions, DB and IO stats, Vacuum and Wraparound, WAL and Archiving, BG Writer, next to Site24x7's own Summary. A regular custom plugin can't show this layout; Site24x7 has to enable it. They enabled it on our account.

## 2. How Site24x7 builds the template (all tested)

- A plugin has one template (tabs and charts), shared by all its monitors.
- The template is built when a monitor registers, only from the metrics that have a value in that payload. Metrics listed only in `units` or in a tab are ignored.
- Every registration replaces the template. A metric that first appears later never gets a chart.
- The agent runs a registration exactly like a normal poll (same arguments, folder and environment), so the plugin can't tell them apart.
- The Windows agent sometimes registers a monitor a second time, for example after a registration timeout.

## 3. Metrics: static list, dynamic values

- **Static:** the list of metrics is fixed in the plugin's code (`postgres.py`). The plugin never invents new metrics.
- **Dynamic:** which metrics have a value depends on the server: its role (Replay Lag only on a standby), cluster or standalone (Nodes Up only on a cluster), PostgreSQL version (Total Sessions only on 14+), and events (Last Failover Age only after a failover).
- Which metrics to send is decided live on every poll by asking PostgreSQL. It is not stored in a file.

## 4. The `.state` folder

**What it is:** the plugin's memory between polls. Each poll starts with no memory of the last one. It belongs to the plugin, not to Site24x7, and sits inside the plugin folder:
- Windows: `C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres\.state\`
- Linux: `/opt/site24x7/monagent/plugins/postgres/.state/`

There is one small JSON file per monitor, named by a hash of its host, port and database.

**What it's used for:**

| Use | Metrics | Example |
| :--- | :--- | :--- |
| Rates | The 12 Per Sec metrics (Transactions, Rows Inserted, WAL Generated...) | PostgreSQL reports 5,000,000 commits in total; last poll it reported 4,997,000. (5,000,000 − 4,997,000) ÷ 300 s = 10 per second. |
| New since last poll | New Deadlocks, New Conflicts, New Requested Checkpoints, New Archive Failures, New Checksum Failures, New WAL Buffers Full | Total deadlocks were 12, now 14: 2 new. |
| Cluster history | Failovers 24h, Last Failover Age, the Events table | Last poll node A was primary, now node B is: a failover, remembered with its time. |
| Remembered nodes | Nodes Down, the Nodes table, Health Code 3 (split brain) | Node A disappears and stays listed as "down" for 24 hours, so if it returns as a second primary, split brain is caught. |
| Say things once | The missing-permissions message | Shown on the first poll, and again only when the list changes. |
| First-poll detection | Every metric (see section 5) | No file means first poll, so every metric is sent. |

Deleting `.state` is safe: rates restart one poll later (the first poll uses a 5-second sample), and cluster history starts empty.

## 5. The trade-off: "No Data" needs the `.state` folder

**Decision:** a metric that doesn't apply to a server is not sent, so it shows "No Data". Nothing fake, no false alerts.

**Why that needs `.state`:** a metric not sent at registration gets no chart (section 2). So on a monitor's first poll the plugin sends every metric, using stand-ins where there's no value yet (0, or 100 for hit percentages). Later polls send only real values. The plugin recognises the first poll by having no state file.

**The problem case, as an example:**
1. A customer monitors Server A (standalone) and Server B (a primary with a standby).
2. Both are added. Their first polls send every metric, and the template is complete.
3. The customer deletes the plugin template in Site24x7 (or the agent registers a monitor a second time).
4. The monitors register again. Their state files are still in the plugin folder, so the plugin thinks "not my first poll" and sends only real values.
5. Server A registers first. Its payload has no Nodes Up, Replay Lag and so on, so the new template has no charts for them.
6. Server B, the real cluster, never shows those charts again.

Seen on the Windows agent: the template went from 134 to 119 metrics, then to 109.

**Fix:** delete the template, delete the `.state` folder, then re-add the plugin folder. The README tells users this. Fresh installs, upgrades from version 1 and new servers are not affected, because they start without a state file.

**Reminder:** a chart's first point can be a registration stand-in. A "below X" threshold on a metric whose stand-in is 0 can fire once, at registration only.

## 6. The alternative: fixed values on every poll

The usual Site24x7 approach is to always send a fixed value (0 or -1) for "doesn't apply". Every payload then has every metric, the template can never shrink, and `.state` is back to rates and history only. The cost is that the values are fake.

**What 0 or -1 would say:**

| Metric | When it has no real value | 0 or -1 would say |
| :--- | :--- | :--- |
| WAL Receiver Connected | Primary | 0 = "standby lost its primary": a false alert on every primary |
| Nodes Up, Nodes Total | Standalone | 0 = "no nodes up": a false alert |
| Last Failover Age | No failover yet | 0 = "just failed over": a false alert |
| Index Hit Percent | No index reads | 0 = "every read misses the cache": a false alert |
| Health Code | Standalone | -1 = an unknown code: trips alerts |
| Replay Lag, Replay Backlog, Last WAL Message Age | Primary | 0: harmless |
| Standbys Streaming, Sync Standbys, Nodes Down, Failovers 24h | Standalone | 0: true |

Threshold profiles are usually shared by all monitors of the plugin, so an alert meant for standbys also fires on primaries.

**A refinement, safe values:** choose a value per metric that is true or can't trip an "above X" alert. That means Nodes Up = 1 on a standalone server (itself), Index Hit = 100, Last Failover Age = time since monitoring began, and 0 for the rest. WAL Receiver Connected has no honest value, so it would move to the Cluster_Info table as text ("Streaming", "Disconnected", "Not a standby"); Health Code 1 already alerts on it. Empty tables would send one text row ("No events", "No replication links", "pg_stat_statements not installed").

**Still fake with safe values (9 metrics):**
- Replay Lag and Replay Backlog on a primary
- Last WAL Message Age on a primary
- Last Archive Age with archiving off or never run
- Oldest Table Vacuum Age with nothing vacuumed yet
- Last Subscription Message Age with no subscriptions
- Index Hit Percent with no index reads (really 0 ÷ 0)
- New Checksum Failures with checksums off
- The PostgreSQL 14+ session and WAL buffer counters, and the 15+ subscription error counters, on older versions

None of them can fire an alert, but on a standalone server the Cluster and Replication charts show flat filler lines instead of "No Data", which is not what the TL asked for.

## 7. The choice

| | A: No Data (shipped) | B: Safe values |
| :--- | :--- | :--- |
| Charts that don't apply | "No Data" | Flat filler lines |
| Fake values | One registration point per chart | 9 metrics, on every poll |
| Template after a deletion or an agent retry | Can come out incomplete; fixed by deleting `.state` | Always complete |

You can't have both "No Data" and a template that survives every re-registration: "No Data" means not sending, and Site24x7 doesn't chart what isn't sent at registration.

**Recommendation:** keep A. It's what the TL asked for, it's honest, and it's built, tested and in the PR. The edge case is rare and documented.

**Ways to shrink the edge case without fake values (not built):**

| Option | Covers | Doesn't cover |
| :--- | :--- | :--- |
| Treat a monitor's first 10 minutes as registration | The agent's retry | A template deletion |
| Treat a state file not updated for about 30 minutes as a fresh start | A template deleted and re-registered later (deleted monitors stop polling) | Deleted and re-added within minutes |
| Keep the list of metric keys in `.state` | Nothing on its own: the plugin already knows every key. The problem is knowing *when* to send them, and the agent's registration run looks like a normal poll. Its "short gap" part is the same as the two rows above. | |
| Find why the agent's registration timed out (`pgaf_node` hung for 2 minutes) | Fewer retries | The risk itself |
| Site24x7 merges metrics on re-registration instead of replacing the template | Everything | Needs a change on Site24x7's side |

## 8. How to explain it to the TL

> No Data costs us one thing: if someone deletes the plugin template, they also have to delete the plugin's `.state` folder, or the new template can miss the cluster charts. The alternative is filler values on every poll, like Nodes Up = 1 on a standalone server and flat 0 lines for Replay Lag, which you didn't want. Plain 0 or -1 would be worse: Nodes Up = 0 and Last Failover Age = 0 fire false alerts.
