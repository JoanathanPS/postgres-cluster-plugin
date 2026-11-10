# Site24x7 PostgreSQL Cluster Monitoring Plugin

Monitor a PostgreSQL cluster from one Site24x7 plugin monitor. The plugin discovers cluster members where possible and reports node availability, primary/standby roles, replication, WAL, database activity, and performance metrics.

For a single PostgreSQL instance, use Site24x7's [PostgreSQL plugin](https://github.com/site24x7/plugins/tree/master/postgres). This plugin adds cluster topology and per-node views while retaining the standalone plugin's core metrics.

## Quick installation

The plugin includes Linux and Windows installers. This v4 review has not run either installer against a live Site24x7 agent; follow the installation steps below and validate the installer in your environment before production use.

### Windows

Run PowerShell as Administrator from the plugin directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\Site24x7PostgresClusterPluginInstaller.ps1 `
  -ClusterHost "postgres-primary.prod.internal" -Username "site24x7"
```

The interactive installer prompts for the password without echoing it. For unattended installation, set `MONITOR_PASSWORD` in the process environment and add `-NonInteractive`; avoid passing `-Password` on the command line. For a non-Patroni cluster, use `host:port:none` and omit `-PatroniPort`. The installer supports `-DryRun`, `-PluginFolderName`, and threshold parameters `-ReplayWarnSeconds`, `-ReplayWarnBytes`, `-FailoverWarnSeconds`, `-SlotWarnBytes`, and `-SlotCriticalBytes`.

### Linux

```bash
sudo bash installer/Site24x7PostgresClusterPluginInstaller.sh
```

For non-interactive installation, export `PG_CLUSTER_HOST`, `MONITOR_USER`, and `MONITOR_PASSWORD` (`MONITOR_DB` defaults to `postgres`, `POSTGRES_PORT` defaults to `5432`, `PATRONI_PORT` defaults to `8008`); `PG_NODES` is supported as a legacy fallback. Optionally set `ADDRESS_MAP`, `REPLAY_WARN_SECONDS`, `REPLAY_WARN_BYTES`, `FAILOVER_WARN_SECONDS`, `SLOT_WARN_BYTES`, and `SLOT_CRITICAL_BYTES`. Install `psycopg2-binary` in the system Python environment used by the Site24x7 agent.

## Prerequisites

- The Site24x7 server monitoring agent on a host that can reach every PostgreSQL node being monitored.
- A dedicated monitoring role. The provided `prerequisites/create_user.sql` grants `pg_monitor`, `pg_read_all_stats`, and `pg_read_all_settings`; repmgr discovery grants are optional and documented in that SQL file.
- Python 3.9 or newer and `psycopg2` available to the agent's Python runtime.
- For Patroni discovery, the Patroni REST API port (normally `8008`) must be reachable from the agent.

Create the monitoring role on the primary for physical replication clusters. Create it on every node for Citus or multi-master deployments. See [Create the monitoring user](#create-the-monitoring-user).

## Plugin installation

The installer copies the plugin into the Site24x7 agent directory and runs a connectivity check. To install manually:

1. Create a `postgres_cluster` directory in the agent's plugin directory.
2. Copy `postgres_cluster.py` and `postgres_cluster.cfg` into it.
3. Edit the configuration as shown below.
4. Run the command in [Verify the installation](#verify-the-installation) and confirm valid JSON.

| Operating system | Plugin directory |
| --- | --- |
| Linux | `/opt/site24x7/monagent/plugins/postgres_cluster/` |
| Windows | `C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster\` |

The plugin folder, Python file, configuration file, and config section should use the same name: `postgres_cluster`.

## Configuration

Example `postgres_cluster.cfg`:

```ini
[global_configurations]
use_agent_python=0
redirect_output=1

[postgres_cluster]
# Required: IP address or internal DNS name for a reachable cluster seed
cluster_host="postgres-primary.prod.internal"

# Optional: default is 5432
# postgres_port="5432"

# Optional: default is 8008 when Patroni is used (set to "none" to disable)
# patroni_port="8008"

username="site24x7"
password="<password>"

# Optional: default is postgres
# db="postgres"

# Advanced options
# cluster_type="auto"
# discover="auto"
# address_map=""
# replay_warn_seconds=60
# replay_warn_bytes=104857600
# failover_warn_seconds=900
# slot_warn_bytes=1073741824
# slot_critical_bytes=10737418240
```

`cluster_host` accepts a single bare IP address or hostname. Ports default to 5432 (`postgres_port`) and 8008 (`patroni_port`). The database in `db` defaults to `postgres`. The legacy `nodes` parameter is still supported for backward compatibility with `host:port[:patroni_port]` entries.

| Cluster type | Seed addresses |
| --- | --- |
| Patroni | One member, with its PostgreSQL and Patroni REST ports |
| repmgr, Citus, pgpool-II, multi-master | One address where the manager exposes a member list |
| Stolon, CloudNativePG, pg_auto_failover, plain streaming replication | List each node; discovery follows upstream links but cannot always find downstream standbys |

Set `discover="off"` to monitor only listed nodes. If a cluster advertises internal Docker/NAT addresses that the agent cannot reach, use `address_map` to map each reported `host:port` to a reachable address. For Patroni, map both the PostgreSQL and REST API ports. Example:

```ini
address_map="pg-node1:5432=127.0.0.1:5441,pg-node1:8008=127.0.0.1:8001,pg-node2:5432=127.0.0.1:5442,pg-node2:8008=127.0.0.1:8002"
```

The plugin stores recent topology and endpoint names in `topology_cache.json` beside the collector. Cached topology is used as a discovery fallback for up to 24 hours when live discovery returns no members; node metrics still require the PostgreSQL endpoints to be reachable. Make sure the Site24x7 agent can write to the plugin directory, and remove this file if you need to discard stale cached topology immediately.

The monitoring password is stored in the plugin configuration file. Restrict access to the plugin directory and use a dedicated monitoring account. On Linux, the installer sets the config file to mode `600`; after manual installation, use `chmod 600 postgres_cluster.cfg` and make sure the agent account can read it. Rotate credentials by changing the monitoring role password and updating this config file. The plugin does not expose libpq `sslmode` as a configuration option. For certificate verification, configure libpq environment variables such as `PGSSLMODE=verify-full` and `PGSSLROOTCERT` for the agent service, then restart the service; otherwise make a code change to expose connection parameters.

## Verify the installation

Run the plugin from its directory without putting the password in the process argument list:

```bash
PGPASSWORD='<password>' python postgres_cluster.py \
  --nodes 10.0.0.5:5432:8008 --username site24x7 --db postgres
```

In PowerShell, set `$env:PGPASSWORD` before running the same command without `--password`.

The command should print one JSON object. Check `status`, `Cluster Health`, `Nodes Up`, and the `msg` field. The agent normally registers the monitor within five minutes. On Windows, `redirect_output=1` is required for large JSON output; restart the agent service after changing its Python runtime or PATH.

## Metrics

### Flat metric reference

The following metrics are emitted at the top level of the plugin JSON. Metrics are grouped by purpose, following the standalone PostgreSQL README's metric-name and description reference.

#### Cluster and failover

| Metric | Unit / type | Description |
| --- | --- | --- |
| `Cluster Health` | status | Cluster health code: `0` healthy, `1` degraded, `2` critical. |
| `Nodes Up` | nodes | Configured or discovered nodes reachable during collection. |
| `Nodes Configured` | nodes | Seed node addresses supplied in the plugin configuration. |
| `Nodes Discovered` | nodes | Additional cluster members added through discovery. |
| `Nodes Omitted` | nodes | Count of known configured or discovered omissions at the 25-node cap; it may overcount nodes present in both sets or undercount when discovery reaches its cap or deadline. |
| `Nodes Total` | nodes | Nodes included in this collection attempt. |
| `Primary Count` | nodes | Primary nodes identified in the topology. |
| `Primary Timeline` | timeline | PostgreSQL timeline reported by the selected primary. |
| `No Primary Flag` | flag | `1` when no usable primary is identified; otherwise `0`. |
| `Split Brain Flag` | flag | `1` when an unexpected multiple-primary condition is detected; otherwise `0`. |
| `Timeline Mismatch Flag` | flag | `1` when node timelines indicate a mismatch; otherwise `0`. |
| `Server PID` | pid | Process ID of the selected PostgreSQL server. |
| `Failover Age Seconds` | s | Seconds since the most recently observed failover event. |
| `Failovers Last 24h` | failovers | Failover events observed in the previous 24 hours. |
| `Last Failover To` | text | Node recorded as the destination of the latest failover. |
| `Last Failover Timeline` | timeline | Timeline recorded for the latest failover. |

#### Replication and slots

| Metric | Unit / type | Description |
| --- | --- | --- |
| `Standbys Expected` | standbys | Standby nodes expected from the discovered/configured topology. |
| `Standbys Streaming` | standbys | Expected standbys currently streaming. |
| `Standby Disconnect Flag` | flag | `1` when an expected standby is not streaming; otherwise `0`. |
| `Sync Standby Count` | standbys | Synchronous standbys reported by the primary. |
| `Cascading Standby Count` | standbys | Reachable standbys that stream from another standby. |
| `Max Replay Backlog` | bytes | Largest observed WAL replay backlog. |
| `Max Replay Delay` | s | Largest observed WAL replay delay in seconds. |
| `Replication Slots Total` | slots | Replication slots observed by the collector. |
| `Replication Slots Active` | slots | Slots currently active. |
| `Inactive Slots Count` | slots | Slots currently inactive. |
| `Max Slot Lag Bytes` | bytes | Largest WAL retention attributed to a replication slot. |
| `Slot Wal Status Risk` | risk | Highest observed slot WAL risk: `0` normal, `1` unreserved, `2` lost. |
| `Logical Replication Used` | flag | `1` when logical replication evidence is present; otherwise `0`. |
| `Mesh Links Declared` | links | Logical links/subscriptions declared across a multi-master topology. |
| `Mesh Links Active` | links | Declared logical links currently active. |
| `Mesh Disconnect Flag` | flag | `1` when one or more declared mesh links are inactive; otherwise `0`. |
| `Max Logical Lag Bytes` | bytes | Largest logical replication lag in bytes. |
| `Max Logical Lag Seconds` | s | Largest logical replication lag in seconds. |
| `Subscription Apply Errors` | errors | Subscription apply errors reported by PostgreSQL. |
| `Subscription Conflicts` | conflicts | Subscription synchronization conflicts reported by PostgreSQL. |

#### Database, I/O, and checkpoints

| Metric | Unit / type | Description |
| --- | --- | --- |
| `Table Count` | tables | Number of tables in the monitored database statistics view. |
| `Database Count` | databases | Number of non-template databases on the instance. |
| `Uptime` | s | Seconds since the PostgreSQL server started. |
| `Total Rows Inserted` | rows | Cumulative rows inserted across databases. |
| `Total Rows Updated` | rows | Cumulative rows updated across databases. |
| `Total Rows Deleted` | rows | Cumulative rows deleted across databases. |
| `Total Rows Fetched` | rows | Cumulative rows fetched across databases. |
| `Total Rows Returned` | rows | Cumulative rows returned across databases. |
| `Total Block Reads` | blocks | Cumulative database blocks read from storage. |
| `Total Block Hits` | blocks | Cumulative database blocks served from shared buffers. |
| `Heap Blocks Read` | blocks | Cumulative heap blocks read from storage. |
| `Heap Blocks Hit` | blocks | Cumulative heap blocks served from shared buffers. |
| `Cache Hit Ratio` | ratio | Ratio of heap buffer hits to total heap reads and hits. |
| `Index Scans` | scans | Cumulative index scans. |
| `Index Rows Read` | rows | Cumulative index entries returned by scans. |
| `Index Rows Fetched` | rows | Cumulative table rows fetched by index scans. |
| `Dead Tuples` | tuples | Estimated dead tuples in user tables. |
| `Checkpoints Timed` | checkpoints | Cumulative checkpoints initiated by the timeout. |
| `Checkpoints Req` | checkpoints | Cumulative checkpoints requested by other causes. |
| `Checkpoint Write Time` | ms | Cumulative checkpoint write time in milliseconds. |
| `Checkpoint Sync Time` | ms | Cumulative checkpoint synchronization time in milliseconds. |
| `Buffers Checkpoint` | buffers | Buffers written during checkpoints. |
| `Buffers Clean` | buffers | Buffers written by the background writer. |
| `Maxwritten Clean` | buffers | Background-writer rounds stopped after reaching the write limit. |
| `Buffers Backend` | buffers | Buffers written directly by backend processes; omitted on PostgreSQL 17+. |
| `Buffers Backend Fsync` | calls | Backend fsync calls; omitted on PostgreSQL 17+. |
| `Buffers Alloc` | buffers | Buffers allocated by the background writer. |
| `Server Version` | text | PostgreSQL server version reported by the selected primary. |

#### Transactions and sessions

| Metric | Unit / type | Description |
| --- | --- | --- |
| `Active Connections` | connections | Current connections across databases on the selected primary. |
| `Active Queries` | queries | Queries currently active, excluding idle sessions. |
| `Active Waiting Queries` | queries | Active queries waiting on a PostgreSQL wait event; available on PostgreSQL 10+. |
| `Max Connections` | connections | Configured maximum number of concurrent connections. |
| `Connection Usage Percent` | % | Active connections as a percentage of `Max Connections`. |
| `Locks Count` | locks | Locks currently visible in `pg_locks`. |
| `Transactions Open` | transactions | Sessions with a transaction start time. |
| `Idle Transactions` | transactions | Sessions idle while holding an open transaction. |
| `Oldest Transaction ID Age` | xids | Age of the oldest transaction ID reported by PostgreSQL. |
| `Oldest Running Txn Age` | s | Age in seconds of the oldest running transaction. |
| `Total Commits` | transactions | Cumulative commits across databases. |
| `Total Rollbacks` | transactions | Cumulative rollbacks across databases. |
| `Total Conflicts` | conflicts | Cumulative conflicts read from the active primary; this is not a cluster-wide standby conflict total. |
| `Total Sessions` | sessions | Cumulative sessions started across databases; available on PostgreSQL 14+. |
| `Total Sessions Abandoned` | sessions | Cumulative sessions abandoned; available on PostgreSQL 14+. |
| `Total Sessions Fatal` | sessions | Cumulative sessions ended by fatal errors; available on PostgreSQL 14+. |
| `Total Sessions Killed` | sessions | Cumulative sessions terminated by administrator action; available on PostgreSQL 14+. |

#### WAL and recovery

| Metric | Unit / type | Description |
| --- | --- | --- |
| `WAL Write Position` | MB | Current WAL write position, expressed in megabytes. |
| `WAL Insert Position` | MB | Current WAL insert position, expressed in megabytes. |
| `WAL Flush Position` | MB | Current WAL flush position, expressed in megabytes. |
| `WAL Files Count` | files | WAL segment files currently present in the WAL directory. |
| `WAL Total Size` | MB | Total size of WAL files currently present. |
| `Archive Mode` | text | Configured WAL archive mode (`off`, `on`, or `always`). |
| `Archive Status Success` | files | Cumulative WAL files successfully archived since the statistics reset. |
| `Archive Status Failed` | files | Cumulative WAL archive attempts that failed since the statistics reset. |
| `Archive Ready Files Count` | files | Current WAL files marked `.ready` in the archive status directory. |
| `Last Archived WAL File` | text | Name of the most recently archived WAL file. |
| `Recovery Conflicts Total` | conflicts | Sum of five recovery-conflict types read from the active primary; this does not aggregate standbys or include PostgreSQL 16+ `confl_active_logicalslot`. |
| `Conflicts Tablespace` | conflicts | Recovery conflicts caused by tablespace removal. |
| `Conflicts Lock` | conflicts | Recovery conflicts caused by lock acquisition. |
| `Conflicts Snapshot` | conflicts | Recovery conflicts caused by snapshot cleanup. |
| `Conflicts Buffer Pin` | conflicts | Recovery conflicts caused by pinned buffers. |
| `Conflicts Deadlock` | conflicts | Recovery conflicts caused by deadlocks. |

Conflict metric caveat: these flat conflict values are collected from the active primary. PostgreSQL records recovery conflicts on standby servers, so the values may be zero and do not summarize conflicts across the cluster. The collector currently sums five conflict categories; PostgreSQL 16+ also exposes `confl_active_logicalslot`, which is not included. See the [PostgreSQL 16 statistics documentation](https://www.postgresql.org/docs/16/monitoring-stats.html). PostgreSQL statistics counters are cumulative since the last statistics reset, not per-second rates. Session metrics are absent before PostgreSQL 14, and `Active Waiting Queries` is absent before PostgreSQL 10. PostgreSQL 17+ uses the new checkpoint statistics view and omits the two backend buffer metrics shown above. `Slot Wal Status Risk` appears only when the server exposes `wal_status`; `Failover Age Seconds` and `Last Failover Timeline` appear only after a failover is identified. Primary-dependent metrics can be absent when no primary is reachable.

### Dashboard tabs

| Tab | What it shows |
| --- | --- |
| Cluster | Cluster type and health, node count, primary count/timeline, failover information, and node details |
| Replication | Standby streaming/lag, replication slots, logical replication and mesh status |
| Node Performance | Per-node I/O and checkpoint counters, database I/O statistics, and standalone database metrics |
| Transactions and Sessions | Per-node activity, transactions, sessions, locks, and per-database transaction statistics |
| WAL and Recovery | WAL positions/files, archive status, and recovery conflicts |

### Child tables

Site24x7 supports up to 25 rows per child table. This plugin emits at most 25 rows in each table; when additional rows exist, `msg` identifies the affected table and available row count. `Nodes Configured` counts seed addresses from config; `Nodes Discovered` counts additional members discovered; `Nodes Omitted` counts configured or discovered omission records at the 25-node cap; it is not guaranteed to be a unique-node count. If configured nodes beyond the cap are returned again by discovery, they can be counted twice; if topology discovery stops at its cap or deadline, additional unknown members may not be counted. `Nodes Total` counts nodes actually considered for polling. `Cluster Health` is evaluated against these considered nodes; when `Nodes Omitted` is greater than zero, the plugin may report a healthy status for only the polled subset. Configure a Site24x7 Trouble threshold on `Nodes Omitted > 0` until the collector health policy explicitly accounts for incomplete coverage.

| Table | Tab | Contents |
| --- | --- | --- |
| `Cluster_Info` | Cluster | Cluster type, evidence, primary, health reason, node counts, and timeline. Columns: `name`, `cluster_type`, `type_evidence`, `primary_node`, `health_reason`, `nodes_total`, `nodes_up`, `primary_timeline`, `status`. Server version is available as the `Server Version` summary metric. |
| `Cluster_Nodes` | Cluster | Per-node identity, role, reachability, timeline, response time, connections, replay backlog/delay, and monitoring status; optional fields depend on node evidence. |
| `Replication_Links` | Replication | Physical streaming links or logical subscriptions: `name`, `link_type`, `source`, `target`, `state`, `replay_lag_bytes`, `write_lag_bytes`, `flush_lag_bytes`, `replay_lag_s`, `is_sync`, `active`, `status`. Some fields vary by link type. |
| `Replication_Slots` | Replication | Slot name, plugin, type, activity, retained WAL, status, and `wal_status` when the server exposes it. |
| `Node_IO` | Node Performance | `name`, `status`, row insert/update/delete/fetch/return counters, block reads/hits, heap reads/hits, cache-hit ratio, and index scan/read/fetch counters. |
| `Node_Checkpoints` | Node Performance | `name`, `status`, checkpoint counts/times, checkpoint/clean buffers, maxwritten count, and allocated buffers. PG17+ omits `buffers_backend` and `buffers_backend_fsync`. |
| `Stats_per_DB` | Node Performance | Standalone per-database rows: `name`, `active_connections`, `size_in_mb`, `rows_inserted`, `rows_updated`, `rows_deleted`, `rows_fetched`, `rows_returned`, `block_reads`, and `block_hits`. |
| `Node_Activity` | Transactions and Sessions | `name`, `status`, active/max connections, active/waiting queries, open/idle-in-transaction counts (`idle_in_txn_count`), locks, oldest transaction age, and uptime. |
| `Node_Transactions` | Transactions and Sessions | `name`, `status`, commits, rollbacks, conflicts, and session counters (session fields are zero before PostgreSQL 14). |
| `Transactions_Per_Database` | Transactions and Sessions | Per-database rows contain `name`, `commits`, `rollbacks`, and `conflicts`; PostgreSQL 14+ also reports sessions and session timing counters. The table name follows Site24x7’s documented attribute-name limit. |

Site24x7 documents limits of 10 tables, 15 columns per table, 25 rows per table, five string columns per table, 200 generic metrics, a 520-character `name` value, and 100 characters for other string values. Attribute names follow Site24x7’s 25-character limit; the renamed schema differs from the standalone PostgreSQL plugin for the affected attributes. See [Site24x7 plugin limitations](https://support.site24x7.com/portal/en/kb/articles/limiting-features-of-a-plugin) and the migration note below.

The `Stats_per_DB` and `Transactions_Per_Database` tables use Site24x7 child discovery and are collected from the active primary. Their columns and units follow the standalone PostgreSQL schema; session timing values are in milliseconds ([PostgreSQL statistics documentation](https://www.postgresql.org/docs/current/monitoring-stats.html)). Removed nodes may remain visible in Site24x7's historical child-table rows.

### Attribute-name compatibility note

Metric and table attribute names are kept within Site24x7’s documented 25-character limit. To comply, v4 changes three names from the standalone plugin: `Transactions Idle In Transaction` is now `Idle Transactions`, `Tranasctions_and_Session_per_Database` is now `Transactions_Per_Database`, and `session_idle_in_transaction_time` is now `idle_in_txn_time`. This is a breaking schema change. Existing thresholds, dashboards, reports, and integrations tied to the old names may need to be recreated or remapped when the new template version is registered. The cluster-specific labels were shortened as follows:

| Previous cluster metric label | Current Site24x7 label |
| --- | --- |
| `Connection Utilization Percent` | `Connection Usage Percent` |
| `Oldest Running Transaction Age` | `Oldest Running Txn Age` |
| `Logical Replication In Use` | `Logical Replication Used` |
| `Replication Slots Inactive` | `Inactive Slots Count` |
| `Seconds Since Last Failover` | `Failover Age Seconds` |

### Standalone PostgreSQL metric parity

The cluster collector reuses the standalone plugin's core SQL for shared metrics, with version-specific checkpoint queries. The cluster monitor reports numeric values for many metrics that the standalone plugin serializes as strings. `Locks Count` can differ because the standalone connection counts locks held by its own monitoring transaction. The cluster collector excludes null database-name rows explicitly; the standalone collector removes the first fetched row, so the two per-database transaction tables are not guaranteed to match row-for-row. Three output names differ from standalone to satisfy Site24x7's 25-character attribute-name limit; see the compatibility note above. On PostgreSQL 17 and newer, `Buffers Backend` and `Buffers Backend Fsync` are omitted because those counters are no longer available in the statistics view used by the standalone plugin.

Cluster-specific metrics include topology, node health, replication lag/slots, failover history, WAL/archive status, logical replication, and recovery-conflict information. Node child tables report metrics for reachable nodes; the flat standalone metrics are collected from the active primary.

## Cluster health and alerts

`Cluster Health` uses `0` for healthy, `1` for degraded, and `2` for critical. `status` is reserved by Site24x7 for monitor availability: the collector sets it to `1` when collection succeeds and `0` for configuration or execution failures. It is separate from cluster health; a node outage may make the cluster degraded while the plugin monitor remains available.

Health evaluation considers no primary, split brain, expected standbys not streaming, node outages, replication delay/backlog, slot-retained WAL risk, recent failover, and timeline mismatch. Multi-master and Citus topologies have special handling for multiple primaries.

Site24x7 creates a default threshold profile for plugin monitors, but does not set threshold values for the metrics. Configure a Plugin Integrations threshold profile after registration. Use static thresholds for explicit health flags and recovery objectives. Site24x7 also offers [Zia-based thresholds](https://www.site24x7.com/help/admin/configuration-profiles/threshold-and-availability/plugin-monitor.html) that learn normal behavior and flag abnormal spikes; consider them for continuous gauges such as replay delay/backlog and connection usage after collecting a representative baseline. Suggested static starting points (tune these to the topology and recovery objectives):

| Metric | Condition | Suggested severity |
| --- | --- | --- |
| `Cluster Health` | `>= 1` | Trouble |
| `Cluster Health` | `= 2` | Critical |
| `No Primary Flag` | `= 1` | Critical |
| `Split Brain Flag` | `= 1` | Critical |
| `Max Replay Delay` | `> 60` seconds | Trouble |
| `Max Replay Backlog` | `> 104857600` bytes | Trouble |
| `Inactive Slots Count` | `> 0` | Trouble |
| `Nodes Omitted` | `> 0` | Trouble |
| `Connection Usage Percent` | `> 80` percent | Trouble |

Child tables use at most five string columns, up to 15 total columns, and up to 25 rows; the reserved `name` value is capped at 520 characters and other strings at 100 characters. Collector health thresholds can be set in `postgres_cluster.cfg`: `replay_warn_seconds` (60 seconds), `replay_warn_bytes` (104857600 bytes), `failover_warn_seconds` (900 seconds), `slot_warn_bytes` (1073741824 bytes), and `slot_critical_bytes` (10737418240 bytes). Values must be integer bytes or seconds and cannot be negative. Setting `failover_warn_seconds` to `0` disables the recent-failover warning. Setting replay thresholds to `0` makes any positive delay/backlog degraded. Setting `slot_warn_bytes` to `0` means any positive inactive-slot retention meets the warning level; `slot_critical_bytes` cannot be `0` because it must be greater than the nonnegative warning threshold. Invalid ordering returns a configuration error. Site24x7 notification thresholds are configured separately in the web client.

PostgreSQL statistics such as commits, rows, and blocks are cumulative since the last statistics reset. Read changes over time; absolute values are not per-second rates. Avoid applying anomaly thresholds to a monotonically increasing counter without a rate or reset-aware interpretation: normal growth can look like a sustained spike.

## Updating the plugin

Increment `PLUGIN_VERSION` by one when the metric or table schema changes, including adding, removing, or renaming an attribute or changing tabs. Logic-only collection changes that keep metric names and template structure the same do not require a version bump. Site24x7 requires an integer version below 10000; this release uses version 4 for the v4 schema changes. Use a new plugin name only when an existing account/agent setup requires a separate monitor during migration; it is not a substitute for incrementing the version. Before release, check that the canonical script and mirror use the same version, confirm changed JSON attributes have a version increment, and review the Site24x7 limits and nested units.

## Tested cluster types

“Live” means the plugin was run against a real test cluster. Detection fixtures alone do not count as live validation.

| Cluster type | Integration evidence | Collector support |
| --- | --- | --- |
| Patroni | Live: three-node PostgreSQL 17.2 cluster; discovery and health are in the standard suite; failover, leader outage, and recovery to three nodes are checked only when `--failover` is enabled | Supported; tested |
| Plain streaming replication | Live: two-node cluster; topology depends on seed direction | Supported; list all nodes for complete coverage |
| repmgr | Live: PostgreSQL 17 primary, standbys, witness, and existing failover event history; the live check does not trigger a failover | Supported; tested |
| Stolon | Live: PostgreSQL 15; all keeper addresses listed | Supported; tested |
| pg_auto_failover | Live: monitor plus two data nodes; the testbed uses an unpinned `latest` image; list both data nodes | Supported; tested; PostgreSQL version not pinned |
| Citus | Live: coordinator and workers | Supported; tested; exact PostgreSQL version not recorded here |
| pgpool-II | Live: PostgreSQL 16 backends discovered from pgpool address | Supported; tested |
| Multi-Master (native logical) | Live: PostgreSQL 17 three-node active-active cluster | Supported; tested |
| CloudNativePG | Live: three instances in kind; the manifest does not pin a PostgreSQL image version, and the read-only service did not expose every instance | Supported; tested with discovery limitation; PostgreSQL version not pinned |
| Multi-Master (pglogical) | Detection fixture only; no live integration testbed | Supported by collector; integration behavior unverified |
| AWS Aurora, AWS RDS, Azure Database for PostgreSQL, GCP Cloud SQL | Detection fixtures only | Detected labels are not in the supported-type allowlist; collection currently returns an unsupported-type error |
| One-way logical replication, mixed/unknown evidence, standalone, split-brain streaming evidence | Detection fixtures only | Detection behavior only; not end-to-end cluster support claims |

See the testbeds in `testbeds/` and the live discovery runner in `tester/test_discovery_live.py` for the specific test setup. PostgreSQL releases, cluster-manager versions, and operating systems not shown as live-tested should be treated as unverified.

## Known limitations

- Every discovered address must be reachable and resolvable from the agent host.
- The PostgreSQL password remains stored in plaintext in the plugin configuration file. The Windows installer restricts that file to SYSTEM and Administrators; apply equivalent access controls on Linux and after manual edits.
- Some cluster managers do not expose a complete member list through PostgreSQL; list all nodes when required by the table above.
- Cloud provider-managed standbys may not be directly reachable. The plugin cannot discover provider-side topology that is not exposed through PostgreSQL or a supported manager API.
- Database-scoped metrics describe the database configured in `db`; per-database tables are limited to 25 rows.
- PostgreSQL 17 moved checkpoint counters. `Buffers Backend` and `Buffers Backend Fsync` are omitted on PostgreSQL 17 and newer because the statistics view used by the standalone plugin no longer provides them.
- Linux and Windows installer behavior has not been validated against a live Site24x7 agent in this v4 review. PostgreSQL versions shown in the test matrix have live collector test coverage; other versions should be validated in your environment before production use.
- Site24x7 may retain old child-table rows after a node is removed from the cluster.

## Create the monitoring user

Run once on the primary for a physical replication cluster:

```bash
psql -h <primary-host> -U postgres \
  -v mon_user=site24x7 -f prerequisites/create_user.sql
psql -h <primary-host> -U postgres \
  -v mon_user=site24x7 -c '\password :mon_user'
```

The provided SQL creates a least-privilege monitoring role and grants the PostgreSQL monitoring roles needed by the plugin. The second command uses psql's secure password prompt, avoiding a password in SQL files, command arguments, or shell history ([psql documentation](https://www.postgresql.org/docs/current/app-psql.html)). The bundled Linux helper runs both steps interactively. For multi-master or Citus, create the user on each node. Optional repmgr grants are included in the SQL file.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| No monitor appears | Run the manual JSON check; confirm the agent can run Python and import `psycopg2`; inspect the agent plugin registration log |
| Node is offline | Confirm PostgreSQL port reachability and DNS from the agent host; map container/NAT addresses with `address_map` |
| No primary detected | Check the listed/discovered nodes and verify failover has completed |
| WAL metrics missing | Confirm the monitoring role can read the relevant PostgreSQL functions/views; the plugin reports unavailable metrics in `msg` |
| Topology cache warning in `msg` | Confirm the agent can write to the plugin directory; live discovery and node polling continue without a successful cache refresh |
| Duplicate monitor appears | Match plugin folder, script, config, and section names |

## Developer notes

The canonical plugin source is `upstream_layout/postgres_cluster/`. The repository's `postgres_cluster/` directory is the working mirror for the collector script. The root-level `postgres_cluster/postgres_cluster.ps1` is a legacy wrapper and is not part of the supported installation; use the Python collector and configuration described above. Run `check-layout.ps1` after changing canonical plugin files; it compares collector, README, installer, user-setup helper, and config-template mirrors and checks collector-version parity. It does not detect schema changes that were made without incrementing `PLUGIN_VERSION`. Add a cluster manager to the supported list only after its live test passes; detection-only fixtures are not sufficient evidence of support.

When adding a cluster type, update evidence detection, member discovery, health handling, and a live testbed/runner entry together. Document whether discovery requires one seed or every node, then update the tested-cluster matrix above.
