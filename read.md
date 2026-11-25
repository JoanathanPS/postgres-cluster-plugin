# PostgreSQL plugin v2: what to know

- Code: branch `v7` of this repo. Upstream PR: https://github.com/site24x7/plugins/pull/467
- Plugin documentation: [`postgres/README.md`](postgres/README.md)

## The plugin needs Site24x7 to enable its layout

The plugin uses an 8-tab layout: Cluster, Replication, Activity, Transactions and Sessions, DB and IO stats, Vacuum and Wraparound, WAL and Archiving, BG Writer, next to Site24x7's own Summary. A regular custom plugin can't show this layout; Site24x7 has to enable it. They enabled it on our account.

## How Site24x7 builds the template

- A plugin has one template (tabs and charts), shared by all its monitors.
- The template is built from the metrics that have a value in the registration payload. Metrics listed only in `units` or in a tab are ignored.
- Every registration replaces the template. Later polls can't add metrics to it.

## Trade-off: first-poll detection uses the `.state` folder

**Design:** a monitor's first poll sends every metric, using a stand-in (0, or 100 for hit percentages) where there's no real value yet, so the template is complete. Later polls send only real values. A metric that doesn't apply shows "No Data" and never trips a threshold.

**How the first poll is recognised:** the plugin keeps a state file per monitor in `.state` inside the plugin folder. No state file means first poll. There is no other way: the agent runs registration exactly like a normal poll (same arguments, folder and environment), so the plugin can't tell them apart.

**When the template comes out incomplete:** a monitor registers while its state file already exists. Two cases:
- The template was deleted in Site24x7 and the monitors register again from the same plugin folder.
- The agent registers a monitor a second time, for example after a registration timeout. Seen on the Windows agent, where the template went from 134 to 119 metrics, then to 109.

**Fix:** delete the template, delete the plugin's `.state` folder, then re-add the plugin folder. The README tells users this. Fresh installs, upgrades from version 1 and new servers are not affected.

### Possible fixes (to discuss)

| Option | What it fixes | Cost |
| :--- | :--- | :--- |
| **Site24x7 keeps every metric it has seen** instead of replacing the template on each registration, or builds the template from `units` | Both cases, completely, with no stand-ins needed | Needs a change on Site24x7's side. Ask the devs, who earlier offered a server-side workaround. |
| **Send 0 for every metric on every poll** | Both cases, completely | False values forever: Last Failover Age 0 reads as "just failed over", Nodes Up 0 on a standalone server fires alerts. Rejected earlier. |
| **Treat the first 10 minutes as registration:** send the full set while the state file is younger than 10 minutes | The agent's retry (the case seen in testing) | A second or third stand-in point. A template deletion is not covered. |
| **Treat an old state file as a first poll:** if the state wasn't updated for, say, 30 minutes, the monitor was stopped or deleted, so send the full set | A template deleted and registered again later | One stand-in point after any long agent outage. A deletion followed by re-registration within minutes is not covered. |
| **Find and remove the cause of the agent's timeout** (`pgaf_node` hung for 2 minutes on registration) | Fewer retries | Doesn't remove the risk, only makes it rarer. |

The 10-minute and old-state rules together cover almost every case without false values. A full fix needs Site24x7.

## Reminder: the first chart point can be a stand-in

A chart's first point can be the registration stand-in rather than a measurement. A "below X" threshold on a metric whose stand-in is 0 (Last Failover Age, Last Archive Age, Nodes Up) can fire once, at registration only.
