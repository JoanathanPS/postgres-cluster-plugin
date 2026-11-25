# PostgreSQL plugin v2: design trade-offs

Two design decisions in version 2 have a cost that should be accepted explicitly before release.

---

## 1. Stand-in values on a monitor's first poll

### Background

Site24x7 builds a plugin's template (its tabs and charts) from the first poll of the first monitor that registers, and every monitor of the plugin shares that template. A chart is created only for a metric that has a value in that poll, and charts are not added later. This was verified on the Site24x7 Linux agent with dedicated test plugins:

| Test | Result |
| :--- | :--- |
| A standalone server registered first, leaving out cluster metrics | The cluster monitors registered later had no charts for those metrics |
| A later monitor left out or emptied tabs in its payload | The tabs stayed, showing "No Data" |
| A second monitor reported a different plugin version | Rejected: "Version (2) not available for the plugin" |

### Decision

- **First poll of each monitor:** every metric and table is sent. Where there is no real value yet, a stand-in is used: 0, or 100 for hit percentages.
- **Every later poll:** only real values are sent. A metric that does not apply, such as Replay Lag on a primary or any cluster metric on a standalone server, is left out and shows "No Data", so no threshold fires on it.

Verified on the Linux agent with a standalone monitor registering first: the template had all 142 entries, none missing, for both the standalone and the cluster monitor. Later standalone polls left the cluster metrics out.

### Cost

Each chart's first data point can be a stand-in rather than a measurement. A threshold evaluated at that single poll can fire once, at registration. This affects "below X" conditions on metrics whose stand-in is 0, for example:

- Last Failover Age below 300 s
- Last Archive Age below a limit
- Nodes Up below 2

The point is recorded only at registration; it never recurs.

### Alternatives considered

| Option | Result | Why not chosen |
| :--- | :--- | :--- |
| Send only real values from the first poll | The template depends on which server registers first | A customer whose first monitor is a standalone server loses the cluster charts on every cluster monitor |
| Stand-ins on every poll (earlier v2 design) | Template always complete | Permanent made-up values, such as a 0 age that reads as "just happened" |
| `-1` as "not applicable" | Visible marker | Site24x7 treats it as a real value: thresholds fire on it and reports average it in |
| Two plugins (`postgres` and `postgres_standalone`) | Each plugin has its own template | More setup for users, and a server that gains a standby has to move to the other plugin |

### Decision needed

Is one stand-in point per chart, at registration only, acceptable?

---

## 2. First-poll detection uses the plugin's `.state` folder

### Background

The plugin keeps a small state file per monitor in the `.state` folder inside the plugin folder. It was already needed for per-second rates, which compare against the previous poll's counters. Version 2 uses the same file to recognise a monitor's first poll: no state file means first poll, so every metric is sent.

### Risk

If the plugin's template is deleted in Site24x7 and the monitors register again from the same plugin folder, the plugin still finds its state file. It treats the poll as a later poll and sends only real values, so charts for metrics that do not apply at that moment are missing from the new template. This is the same effect as the registration-order problem in section 1.

### When it can happen

Only after a manual template deletion in Site24x7, followed by re-registration without reinstalling the plugin. Fresh installs, upgrades from version 1 and new servers are not affected, because they start without a state file.

### Mitigations

| Mitigation | Status |
| :--- | :--- |
| README note: delete the `.state` folder after deleting the template | Done |
| The installer starts a fresh installation without a state folder | Done |
| Treat a state file older than a set age as a first poll | Not done: a template can be deleted and re-registered within minutes, so no age is reliable |

### Decision needed

Is the README note sufficient, or should the re-registration steps also be published as a Site24x7 support article?
