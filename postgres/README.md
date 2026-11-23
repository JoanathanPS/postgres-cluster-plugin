# PostgreSQL Plugin

Monitors a PostgreSQL server and, when it is part of a cluster, every node of that cluster from a single address.

Version 2 replaces version 1. The configuration keys are unchanged, and every metric and child table that version 1 reported is still reported under the same name.

## What it monitors

**This node:** the server at `host:port`. That is its activity, transactions, I/O, background writer, vacuum and XID wraparound, WAL and archiving, replication slots and standby replay.

**The cluster:** the plugin finds the other nodes by itself, starting from that one address. It reports a row per node that answers "is this node OK?", plus replication links, a health code and a history of failovers.

| Cluster type | How the nodes are found | Notes |
| :--- | :--- | :--- |
| Standalone | — | One node. Same as version 1. |
| Streaming replication | `pg_stat_replication`, `pg_stat_wal_receiver` | Also covers keepalived/VIP, CloudNativePG, Stolon and managed services. Works from the primary or from any standby. |
| Patroni | REST API `/cluster` | Set `patroni_port`. Lists stopped members too. |
| repmgr | `repmgr.nodes` (database `repmgr`) | Includes witness nodes. |
| pg_auto_failover | `pgautofailover.node` | Point the plugin at the monitor node. A data node is handled as streaming replication. |
| Citus | `pg_dist_node` | Point the plugin at the coordinator. |
| pgpool-II | `SHOW POOL_NODES` | Point the plugin at the pgpool port. |
| Logical / multi-master | logical walsenders, subscriptions | Native logical replication, pglogical, Spock, BDR/PGD. Every node is a writer. |

A node's role is always taken from PostgreSQL (`pg_is_in_recovery()`), never only from a cluster manager. If the two disagree, that is reported as Health Code 4.

**One address, two ways to deploy:**

- **Agent on each database server** (`host="localhost"`): each monitor reports its own server in full, plus the shared cluster view. This is how version 1 is usually installed.
- **One agent, one cluster address** (a VIP, DNS name or HAProxy write port): one monitor follows whichever node is primary. This is recommended for new installs.

## Prerequisites

- Site24x7 Linux or Windows server agent.
- Python 3.6 or later.
- The `psycopg2` module, installed for the Python the agent uses:

  ```bash
  pip3 install psycopg2-binary
  ```

- PostgreSQL 9.6 or later. Older servers are reported as unsupported.
- A monitoring user that exists on every node with the same password and has the `pg_monitor` role:

  ```sql
  CREATE USER site24x7 WITH PASSWORD '<password>';
  GRANT pg_monitor TO site24x7;
  ```

  Without `pg_monitor` the plugin still runs. Metrics the user cannot read, for example WAL directory size, are left out instead of shown as 0, and `msg` names the permission that is missing.

## Plugin installation

1. Create a folder named `postgres` and download `postgres.py` and `postgres.cfg` into it:

   ```bash
   mkdir postgres && cd postgres
   wget https://raw.githubusercontent.com/site24x7/plugins/master/postgres/postgres.py
   wget https://raw.githubusercontent.com/site24x7/plugins/master/postgres/postgres.cfg
   ```

2. Check the output by running the plugin by hand:

   ```bash
   python3 postgres.py --host localhost --port 5432 --username site24x7 --password <password> --db postgres
   ```

3. Fill in `postgres.cfg` (see below).
4. Move the folder into the agent's plugin directory:
   - Linux: `/opt/site24x7/monagent/plugins/`
   - Windows: `C:\Program Files (x86)\Site24x7\WinAgent\monitoring\plugins\`

The agent encrypts `password` on its first run.

## Configuration

```ini
[global_configurations]
use_agent_python=1

[postgres]
host="localhost"
port="5432"
username="site24x7"
password="<password>"
db="postgres"
plugin_version=2
heartbeat="true"
```

Each section is one monitor. Add more sections (`[postgres-db2]`) to monitor more servers from one agent.

| Key | Default | Description |
| :--- | :--- | :--- |
| `host` | `localhost` | Server to monitor. A node, a VIP, a DNS name or a proxy port. |
| `port` | `5432` | PostgreSQL port. |
| `username`, `password` | — | Monitoring user (see Prerequisites). |
| `db` | `postgres` | Database to connect to. Per-table metrics and `Top_Queries` come from this database. |
| `sslmode` | libpq default | `disable`, `require`, `verify-ca` or `verify-full`. Optional: `sslrootcert`, `sslcert`, `sslkey`. |
| `timeout` | `10` | Connect timeout in seconds (1–30). Other nodes are always probed with a 3 s timeout. |
| `patroni_port` | — | Patroni REST API port (usually `8008`). Patroni is used only when this is set. |
| `address_map` | — | Only needed when the addresses the cluster reports are not reachable from the agent (NAT, containers). Example: `10.0.0.5:5432=192.168.1.5:6432,pg-node2=192.168.1.6`. |
| `logs_enabled` | `false` | Write cluster events (failovers, nodes down and recovered) to a log file in the plugin folder and send it to Site24x7 AppLogs. |
| `log_type_name` | `PostgreSQL Cluster Events` | AppLogs log type. |
| `log_file_path` | `postgres_events.log` | File name only. The file is always kept in the plugin folder and rotated at 1 MB, keeping three old files. |

## Health

`status` is 0 (monitor down) only when the server itself cannot be monitored. That covers a missing driver, a connection or authentication failure, or an unsupported version. Problems elsewhere in the cluster are reported through these metrics and keep the monitor up:

| Health Code | Cluster Health | Meaning |
| :--- | :--- | :--- |
| 0 | 0 | Healthy |
| 1 | 1 | One or more nodes down, or a standby not streaming |
| 2 | 2 | No reachable primary |
| 3 | 2 | Split brain: more than one writable node in a single-primary cluster |
| 4 | 1 | A cluster manager and PostgreSQL disagree about a node's role |

Lag, wraparound, connection saturation, slots and archiving are reported as numbers. Set Site24x7 threshold profiles on the ones you care about, for example `Max Standby Replay Lag`, `XID Wraparound Percent`, `Connection Utilization`, `Inactive Replication Slots` and `Archiving Failing`.

A node that disappears stays in the `Nodes` table as down or not streaming for 24 hours, and is still probed. That is how a former primary coming back writable is caught as a split brain.

## Child tables

| Table | Rows | Columns |
| :--- | :--- | :--- |
| `Stats_per_DB` | databases | connections, size, rows inserted/updated/deleted/fetched/returned, block reads and hits, cache hit %, deadlocks, temp files |
| `Tranasctions_and_Session_per_Database` | databases | commits, rollbacks, conflicts; session counts and times on PostgreSQL 14+. The name is kept from version 1. |
| `Wait_Events` | wait event | active sessions waiting on it |
| `Replication_Slots` | slots | type, active, retained WAL, WAL status; catalog_xmin age and spill size on 14+ |
| `Top_Queries` | top 10 by total time | calls, total and mean time, rows, query text (only when `pg_stat_statements` is installed in `db`) |
| `Nodes` | cluster nodes | role, state, status, reachable, replay lag, backlog, timeline, connection %, uptime, longest query, last WAL message age, last seen |
| `Replication_Links` | standbys / subscribers | state, sync state, address, sent/write/flush/replay lag in MB and seconds |
| `Events` | last 25 cluster events | event (`promoted`, `demoted`, `down`, `recovered`, `joined`, `removed`), node, old and new role, age |

Every table is capped at 25 rows. In `Nodes`, down nodes are listed first so a failure is never cut off.

## Supported metrics

Rates (`... Per Sec`) and per-poll deltas (`New ...`) need two polls of the same server process, so they appear from the second poll onward. A metric that cannot be read on a given server is left out, never reported as 0.

| Metric | Unit | Description |
| :--- | :--- | :--- |
| **Summary** | | |
| Uptime | s | Time since the server started |
| Active Connections | connections | Backends connected to databases |
| Transactions Per Sec | transactions/s | Commits per second |
| Connection Utilization | % | Active Connections as a percentage of Max Connections |
| Buffer Cache Hit Percent | % | Share of block reads served from shared buffers, all databases |
| Cluster Health | status | 0 healthy, 1 warning, 2 critical (see Health) |
| Nodes Up | nodes | Cluster nodes that are up |
| **Activity** | | |
| Server Version | text | PostgreSQL version |
| Max Connections | connections | `max_connections` |
| Active Queries | queries | Client sessions running a query |
| Active Waiting Queries | queries | Active client sessions waiting on an event |
| Idle Connections | connections | Idle client sessions |
| Longest Transaction | s | Age of the oldest open transaction |
| Long Running Queries | queries | Queries running for more than 5 minutes |
| Blocked Sessions | sessions | Sessions blocked by another session's lock |
| Locks Count | locks | Locks held or awaited by other sessions |
| Waiting Locks | locks | Lock requests not yet granted |
| Node Role | text | `primary` or `standby` |
| **Transactions and Sessions** | | |
| Transactions Idle In Transaction | transactions | Sessions idle inside an open transaction |
| Transactions Open | transactions | Sessions with an open transaction |
| Total Commits, Total Rollbacks | transactions | Cumulative since statistics reset |
| Total Conflicts | conflicts | Queries cancelled by recovery conflicts (standbys) |
| Total Deadlocks | deadlocks | Cumulative deadlocks |
| Total Sessions, … Abandoned, … Fatal, … Killed | sessions | Session counts (14+) |
| Rollbacks Per Sec | transactions/s | Rollbacks per second |
| New Deadlocks, New Conflicts | count | Since the previous poll |
| **DB and IO stats** | | |
| Database Count, Table Count | count | Databases (excluding templates); tables in `db` |
| Total Rows Inserted / Updated / Deleted / Fetched / Returned | rows | Cumulative row activity |
| Rows … Per Sec | rows/s | The same, per second |
| Total Block Reads, Total Block Hits | blocks | Blocks read from disk / found in shared buffers |
| Block Reads Per Sec | blocks/s | Disk block reads per second |
| Total Temp Files, Total Temp Data | files, MB | Temporary files written by queries |
| Temp Data Per Sec | MB/s | Temporary data written per second |
| Index Scans, Index Rows Read, Index Rows Fetched | count | User-index activity in `db` |
| Sequential Scans | scans | Sequential scans of user tables in `db` |
| Index Scans Per Sec, Sequential Scans Per Sec | scans/s | The same, per second |
| Heap Blocks Read, Heap Blocks Hit | blocks | User-table block I/O in `db` |
| Cache Hit Ratio | ratio | User-table cache hit ratio in `db`, 0–1 (as in version 1) |
| Index Hit Percent | % | User-index cache hit percentage in `db` |
| Total Database Size | MB | Size of all databases the user may connect to |
| Checksum Failures, New Checksum Failures | failures | Data checksum failures (12+) |
| **BG Writer** | | |
| Checkpoints Timed, Checkpoints Req | checkpoints | Scheduled and requested checkpoints |
| Checkpoint Write Time, Checkpoint Sync Time | ms | Time spent writing and syncing checkpoint files |
| Buffers Checkpoint, Buffers Clean, Buffers Alloc | buffers | Buffers written by checkpoints / by the background writer; buffers allocated |
| Maxwritten Clean | times | Background writer stopped for writing too many buffers |
| Buffers Backend, Buffers Backend Fsync | buffers, fsyncs | Written directly by backends (up to 16; removed in 17) |
| New Requested Checkpoints | checkpoints | Requested checkpoints since the previous poll |
| **Vacuum and Wraparound** | | |
| Dead Tuples, Live Tuples | rows | In user tables of `db` |
| Tables Never Vacuumed | tables | Non-empty user tables never vacuumed |
| Oldest Table Vacuum Age | s | Time since the least recently vacuumed table was vacuumed |
| Max XID Age, Max Multixact Age | count | Oldest unfrozen transaction / multixact ID across databases |
| XID Wraparound Percent | % | Max XID Age relative to `autovacuum_freeze_max_age` |
| **WAL and Archiving** | | |
| WAL Written, WAL Generated Per Sec | MB, MB/s | WAL position and rate (primary) |
| WAL Buffers Full, New WAL Buffers Full | times | WAL buffer exhaustion (14+) |
| WAL Files, WAL Directory Size | files, MB | Contents of `pg_wal` |
| Archived Count, Archive Failed Count, New Archive Failures | files | Archiver results (when `archive_mode` is on) |
| Last Archive Age | s | Time since the last successful archive |
| Archiving Failing | flag | 1 if the last archive attempt failed |
| Archive Ready Files | files | WAL files waiting to be archived (12+) |
| **Replication** | | |
| WAL Receiver Connected | flag | Standby: 1 if streaming from its upstream |
| Replay Lag | s | Standby: how far replay is behind (0 when fully caught up) |
| Replay Backlog | MB | Standby: WAL received but not yet replayed |
| Last WAL Message Age | s | Standby: time since the last message from the upstream |
| Replication Slots, Inactive Replication Slots | slots | Primary only (HA managers keep idle slots on standbys on purpose) |
| Max Slot Retained WAL | MB | Largest WAL volume held back by a slot (primary) |
| Subscriptions, Active Subscriptions | subscriptions | Logical subscriptions and those with a running worker |
| Last Subscription Message Age | s | Time since the last message from a publisher |
| Subscription Apply Errors, Subscription Sync Errors | errors | Logical replication errors (15+) |
| Max Standby Replay Lag, Max Standby Backlog | s, MB | Worst standby across the cluster |
| **Cluster** | | |
| Timeline | timeline | Current timeline; increases at every promotion |
| Cluster Type | text | `standalone`, `streaming`, `patroni`, `repmgr`, `pg_auto_failover`, `citus`, `pgpool`, `logical`, `pglogical`, `spock`, `bdr` |
| Health Code, Health Reason | code, text | See Health |
| Primary Node | text | Current primary |
| Nodes Total, Nodes Down | nodes | Known nodes, and those down or not streaming |
| Standbys Streaming, Sync Standbys | nodes | From the primary's view (`quorum` counts as synchronous) |
| Last Failover Age, Failovers 24h | s, count | From promotions this monitor has observed |
| **Plugin** | | |
| Collection Time | ms | Time taken by this poll |
| Failed Queries | queries | Queries that failed this poll (their metrics are left out) |

## Changes from version 1

- Numbers are reported as numbers, not strings.
- When there are no user tables, metrics are left out instead of reported as the text `None` or a false `0`.
- `Active Queries` counts client sessions only. Version 1 also counted background processes.
- `Locks Count` excludes the plugin's own session. Version 1 counted the locks of its own open transaction.
- `template0` and `template1` are no longer listed as databases.
- Cluster support, the metrics listed above, and the `Nodes`, `Replication_Links`, `Events`, `Wait_Events`, `Replication_Slots` and `Top_Queries` tables are new.
