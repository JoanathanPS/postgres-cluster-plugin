Plugin for PostgreSQL Monitoring
=============================

PostgreSQL is an ORDBMS server whose primary function is to store data securely, and allows retrieval at the request of other software applications. Analyze and optimize your Postgres server by configuring our Postgres plugin and proactively monitor the availability and performance of business-critical Postgres database servers.

Version 2 of the plugin also monitors **PostgreSQL clusters** from the same single address. It finds every node of the cluster by itself, without a node list, and reports which node is primary, whether each standby is healthy and replicating, and every failover. It works for standalone servers, streaming replication, Patroni, repmgr, pgpool-II, Citus, pg_auto_failover and logical (multi-master) replication.

Learn more https://www.site24x7.com/plugins/postgres-monitoring.html

## Quick installation

If you're using Linux servers, use the postgres plugin installer that checks the prerequisites and installs the plugin with a bash script. You don't need to manually set up the plugin if you're using the installer.

Execute the command below in the terminal to run the installer and follow the instructions displayed on-screen:

```bash
wget https://raw.githubusercontent.com/site24x7/plugins/master/postgres/installer/Site24x7PostgresPluginInstaller.sh && sudo bash Site24x7PostgresPluginInstaller.sh
```

**Upgrading from version 1:** run the same command. The installer detects the installed plugin and replaces only `postgres.py` and this README. Your `postgres.cfg`, with every monitor and its encrypted credentials, is kept as it is.

### Prerequisites

- Download and install the latest version of the [Site24x7 agent](https://www.site24x7.com/app/client#/admin/inventory/add-monitor) in the server where you plan to run the plugin.
- Python version 3.6 or higher.
- The psycopg2 module:
  - **Linux:** nothing to install. The Site24x7 Linux agent runs the plugin with its own Python, which already includes psycopg2.
  - **Windows:** install it for the server's Python:

		pip3 install psycopg2-binary

- PostgreSQL 9.6 or higher.
- A user with the **pg_monitor** role. For a cluster, create it on every node with the same password. For example, create a user `site24x7` with password `site24x7` and grant it `pg_monitor`:

	```sql
	CREATE USER site24x7 WITH PASSWORD 'site24x7';
	GRANT pg_monitor TO site24x7;
	```

  Without `pg_monitor` the plugin still works. The few metrics the user can't read (for example WAL directory size) are left out, and the monitor message names them once, not on every poll.

### Plugin Installation

- Create a directory named `postgres`.

	```bash
	mkdir postgres
	cd postgres/
	```

- Download all the files and place them under the `postgres` directory.

	```bash
	wget https://raw.githubusercontent.com/site24x7/plugins/master/postgres/postgres.py
	wget https://raw.githubusercontent.com/site24x7/plugins/master/postgres/postgres.cfg
	```

- Execute the below command with appropriate arguments to check for the valid json output:

	```bash
	python3 postgres.py --host "localhost" --port "5432" --username "username" --password "password" --db "postgres"
	```

- Provide your Postgres DB configurations in the postgres.cfg file.

    ```ini
    [postgres]
    host="localhost"
    port="5432"
    username="None"
    password="None"
    db="postgres"
    plugin_version=2
    ```

  For a cluster, `host` can be any node, a VIP, a DNS name or an HAProxy write port; the other nodes are found automatically. Add one section per server or cluster to monitor more than one from the same agent. All optional settings are listed under [Configuration options](#configuration-options).

  #### Linux

- Move the directory `postgres` under the Site24x7 Linux Agent plugin directory:

	```bash
	mv postgres /opt/site24x7/monagent/plugins/
	```

  #### Windows

- Since it's a Python plugin, to run the plugin in a Windows server please follow the steps in [this link](https://support.site24x7.com/portal/en/kb/articles/run-python-plugin-scripts-in-windows-servers). The remaining configuration steps are the same.
- Set `use_agent_python=0` in the `[global_configurations]` section of postgres.cfg, so the plugin runs with the server's Python, where psycopg2 is installed.
- Move the folder `postgres` under the Site24x7 Windows Agent plugin directory:

	```bash
	C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins
	```

The agent will automatically execute the plugin within five minutes and the user can see the plugin monitor under Site24x7 > Plugins > Plugin Integrations.

## Monitoring a PostgreSQL cluster

Point the plugin at any one address of the cluster. It works out the cluster type and finds the other nodes itself:

| Cluster type | How the nodes are found | Point the plugin at |
| :--- | :--- | :--- |
| Standalone | — | The server |
| Streaming replication (also keepalived/VIP, CloudNativePG, Stolon, managed services) | `pg_stat_replication`, `pg_stat_wal_receiver` | The primary, any standby, or a VIP |
| Patroni | Patroni REST API `/cluster` | Any node, with `patroni_port` set |
| repmgr | `repmgr.nodes` | Any node |
| pgpool-II | `SHOW POOL_NODES` | The pgpool port |
| Citus | `pg_dist_node` | The coordinator |
| pg_auto_failover | `pgautofailover.node` | The monitor node |
| Logical / multi-master (native, pglogical, Spock, BDR/PGD) | Logical replication connections | Any node |

A node's role (primary or standby) always comes from PostgreSQL itself, never only from a cluster manager. If the two disagree, the plugin reports it.

**Two ways to deploy:**

- **One agent, one cluster address** (a VIP, DNS name or HAProxy write port): one monitor follows whichever node is primary. Recommended for new installs.
- **An agent on every database server** (`host="localhost"`): each monitor shows its own server in full, plus the same cluster view. This is how version 1 is usually installed, so upgraded monitors keep working this way.

## Configuration options

| Key | Default | Description |
| :--- | :--- | :--- |
| `host` | `localhost` | Server to monitor: a node, a VIP, a DNS name or a proxy port. |
| `port` | `5432` | PostgreSQL port. |
| `username`, `password` | — | The monitoring user (see Prerequisites). The agent encrypts the password. |
| `db` | `postgres` | Database to connect to. Per-table metrics and `Top_Queries` come from this database. |
| `sslmode` | libpq default | `disable`, `require`, `verify-ca` or `verify-full`. Optional: `sslrootcert`, `sslcert`, `sslkey`. |
| `timeout` | `10` | Connect timeout in seconds (1–30). |
| `plugin_version` | `2` | Leave as is. |
| `heartbeat` | `true` | Alert when the agent cannot post this plugin's data. |
| `patroni_port` | — | Patroni REST API port (usually `8008`). Patroni is used only when this is set. |
| `patroni_scheme` | `http` | `https` if the Patroni REST API uses TLS. |
| `patroni_verify` | `true` | `false` only for a self-signed Patroni certificate. |
| `patroni_cafile` | — | CA certificate to verify Patroni's HTTPS certificate against. Safer than `patroni_verify=false`. |
| `patroni_certfile`, `patroni_keyfile` | — | Client certificate and key, for Patroni with `verify_client: required`. |
| `patroni_username`, `patroni_password` | — | Basic auth, only for a proxy in front of the Patroni API. Patroni itself doesn't ask for a password on the read the plugin uses. |
| `address_map` | — | Only when the addresses the cluster reports aren't reachable from the agent (NAT, containers). Example: `10.0.0.5:5432=192.168.1.5:6432,pg-node2=192.168.1.6`. |
| `logs_enabled` | `false` | Write cluster events (failovers, nodes down or back) to `postgres_events.log` in the plugin folder and send it to Site24x7 AppLogs. |
| `log_type_name` | `PostgreSQL Cluster Events` | AppLogs log type. |
| `log_file_path` | `postgres_events.log` | File name only. The file always stays in the plugin folder and is rotated at 1 MB. |

The plugin can also monitor through a connection pooler such as PgBouncer.

## Health

The monitor is down only when the server itself can't be monitored: the driver is missing, the connection or login fails, or the PostgreSQL version is below 9.6. Problems elsewhere in a cluster keep the monitor up and are reported through these metrics:

| Health Code | Cluster Health | Meaning |
| :--- | :--- | :--- |
| 0 | 0 | Healthy |
| 1 | 1 | One or more nodes down, or a standby not streaming |
| 2 | 2 | No reachable primary |
| 3 | 2 | Split brain: more than one writable node in a single-primary cluster |
| 4 | 1 | A cluster manager and PostgreSQL disagree about a node's role |

Set Site24x7 thresholds on the metrics you care about, for example `Cluster Health`, `Max Standby Replay Lag`, `XID Wraparound Percent`, `Connection Utilization` and `Archiving Failing`.

## PostgreSQL Server Monitoring Plugin Metrics

Rates (`... Per Sec`) and per-poll counts (`New ...`) are measured between polls. On a monitor's very first poll the plugin measures them over 5 seconds, so every metric has a value from the start.

| **Metric Name** | **Unit** | **Description** |
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
| Total Sessions, Total Sessions Abandoned, Total Sessions Fatal, Total Sessions Killed | sessions | Session counts (PostgreSQL 14+) |
| Rollbacks Per Sec | transactions/s | Rollbacks per second |
| New Deadlocks, New Conflicts | count | Since the previous poll |
| **DB and IO stats** | | |
| Database Count, Table Count | count | Databases (excluding templates); tables in `db` |
| Total Rows Inserted / Updated / Deleted / Fetched / Returned | rows | Cumulative row activity |
| Rows Inserted / Updated / Deleted / Fetched / Returned Per Sec | rows/s | The same, per second |
| Total Block Reads, Total Block Hits | blocks | Blocks read from disk / found in shared buffers |
| Block Reads Per Sec | blocks/s | Disk block reads per second |
| Total Temp Files, Total Temp Data | files, MB | Temporary files written by queries |
| Temp Data Per Sec | MB/s | Temporary data written per second |
| Index Scans, Sequential Scans | scans | Index and sequential scans of user tables in `db` |
| Index Scans Per Sec, Sequential Scans Per Sec | scans/s | The same, per second |
| Index Hit Percent | % | User-index cache hit percentage in `db` |
| Total Database Size | MB | Size of all databases the user may connect to |
| Checksum Failures, New Checksum Failures | failures | Data checksum failures (PostgreSQL 12+) |
| **BG Writer** | | |
| Checkpoints Timed, Checkpoints Req | checkpoints | Scheduled and requested checkpoints |
| Checkpoint Write Time, Checkpoint Sync Time | ms | Time spent writing and syncing checkpoint files |
| Buffers Checkpoint, Buffers Clean, Buffers Alloc | buffers | Buffers written by checkpoints / by the background writer; buffers allocated |
| Maxwritten Clean | times | Background writer stopped for writing too many buffers |
| Buffers Backend, Buffers Backend Fsync | buffers, fsyncs | Written directly by backends (up to PostgreSQL 16) |
| New Requested Checkpoints | checkpoints | Requested checkpoints since the previous poll |
| **Vacuum and Wraparound** | | |
| Dead Tuples, Live Tuples | rows | In user tables of `db` |
| Tables Never Vacuumed | tables | Non-empty user tables never vacuumed |
| Oldest Table Vacuum Age | s | Time since the least recently vacuumed table was vacuumed |
| Max XID Age, Max Multixact Age | count | Oldest unfrozen transaction / multixact ID across databases |
| XID Wraparound Percent | % | Max XID Age relative to `autovacuum_freeze_max_age` |
| **WAL and Archiving** | | |
| WAL Written, WAL Generated Per Sec | MB, MB/s | WAL position and rate (primary) |
| WAL Buffers Full, New WAL Buffers Full | times | WAL buffer exhaustion (PostgreSQL 14+) |
| WAL Files, WAL Directory Size | files, MB | Contents of `pg_wal` |
| Archived Count, Archive Failed Count, New Archive Failures | files | Archiver results |
| Last Archive Age | s | Time since the last successful archive |
| Archiving Failing | flag | 1 if the last archive attempt failed |
| Archive Ready Files | files | WAL files waiting to be archived (PostgreSQL 12+) |
| **Replication** | | |
| WAL Receiver Connected | flag | Standby: 1 if streaming from its primary |
| Replay Lag | s | Standby: how far replay is behind (0 when caught up) |
| Replay Backlog | MB | Standby: WAL received but not yet replayed |
| Last WAL Message Age | s | Standby: time since the last message from its primary |
| Replication Slots, Inactive Replication Slots | slots | Slots on this node. Patroni keeps idle slots on standbys on purpose, so alert on inactive slots on the primary. |
| Max Slot Retained WAL | MB | Largest WAL volume held back by a slot |
| Subscriptions, Active Subscriptions | subscriptions | Logical subscriptions, and those with a running worker |
| Last Subscription Message Age | s | Time since the last message from a publisher |
| Subscription Apply Errors, Subscription Sync Errors | errors | Logical replication errors (PostgreSQL 15+) |
| Max Standby Replay Lag, Max Standby Backlog | s, MB | Worst standby in the cluster |
| **Cluster** | | |
| Timeline | timeline | Current timeline; increases at every promotion |
| Cluster Type | text | `standalone`, `streaming`, `patroni`, `repmgr`, `pg_auto_failover`, `citus`, `pgpool`, `logical`, `pglogical`, `spock`, `bdr` |
| Health Code, Health Reason | code, text | See Health |
| Primary Node | text | Current primary |
| Nodes Total, Nodes Down | nodes | Known nodes, and those down or not streaming |
| Standbys Streaming, Sync Standbys | nodes | Standbys streaming from the primary, and how many are synchronous |
| Last Failover Age, Failovers 24h | s, count | Time since the last failover this monitor saw; failovers in the last 24 hours |
| **Plugin** | | |
| Collection Time | ms | Time taken by this poll |
| Failed Queries | queries | Queries that failed this poll, for example on a timeout |
| Permission Gaps | queries | Queries this user isn't allowed to run (grant `pg_monitor` to include them) |

A few metrics have no value until their event first happens, for example Last Archive Age before the first archive. Until then they show a safe stand-in, so that every metric gets a chart from the first poll: 0 for "lower is better" ages, 100 % for Index Hit Percent with no reads, and the time since monitoring began for Last Failover Age.

## Transactions and Sessions per Database

Table `Transactions_and_Sessions_per_Database`, one row per database:

| **Column** | **Description** |
| :--- | :--- |
| commits, rollbacks | Transactions committed and rolled back |
| conflicts | Queries cancelled by recovery conflicts |
| sessions, sessions_abandoned, sessions_fatal, sessions_killed | Session counts (PostgreSQL 14+) |
| session_time, sessions_active_time, session_idle_in_transaction_time | Time spent in sessions (ms, PostgreSQL 14+) |

## Stats per Database

Table `Stats_per_DB`, one row per database:

| **Column** | **Description** |
| :--- | :--- |
| active_connections | Connections to the database |
| size_in_mb | Database size |
| rows_inserted, rows_updated, rows_deleted, rows_fetched, rows_returned | Row activity |
| block_reads, block_hits | Blocks read from disk / found in shared buffers |
| cache_hit_percent | Buffer cache hit percentage |
| deadlocks, temp_files | Deadlocks and temporary files |

## Other tables

| **Table** | **Rows** | **Columns** |
| :--- | :--- | :--- |
| `Wait_Events` | wait event | active sessions waiting on it |
| `Replication_Slots` | slots | type, active, retained WAL, WAL status; catalog_xmin age and spill size (PostgreSQL 14+) |
| `Top_Queries` | top 10 by total time | calls, total and mean time, rows, query text (only when `pg_stat_statements` is installed in `db`) |
| `Nodes` | cluster nodes | role, state, status, reachable, replay lag, backlog, timeline, connection %, uptime, longest query, last message age, last seen |
| `Replication_Links` | standbys / subscribers | state, sync state, address, sent/write/flush/replay lag |
| `Events` | last 25 cluster events | event (`promoted`, `demoted`, `down`, `recovered`, `joined`, `removed`), node, old and new role, age |

Every table holds at most 25 rows. In `Nodes`, down nodes are listed first.

## Changes from version 1

- Cluster monitoring, and the `Nodes`, `Replication_Links`, `Events`, `Wait_Events`, `Replication_Slots` and `Top_Queries` tables, are new.
- The required role is `pg_monitor` (version 1 used `pg_read_all_stats`).
- The table `Tranasctions_and_Session_per_Database` is renamed `Transactions_and_Sessions_per_Database`.
- Dropped, because newer metrics cover them: Cache Hit Ratio (use Buffer Cache Hit Percent), Heap Blocks Read/Hit (use Total Block Reads/Hits), Index Rows Read/Fetched (use Index Scans).
- Numbers are sent as numbers, not as text.
- `Active Queries` counts client sessions only; version 1 also counted background processes.
- `Locks Count` no longer counts the plugin's own locks.
- `template0` and `template1` are no longer listed as databases.
