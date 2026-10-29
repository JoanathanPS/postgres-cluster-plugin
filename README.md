Plugin for PostgreSQL Cluster Monitoring
=======================================

PostgreSQL is an ORDBMS server whose primary function is to store data securely, and allows retrieval at the request of other software applications. Analyze and optimize your PostgreSQL high-availability cluster by configuring our PostgreSQL Cluster plugin and proactively monitor the availability, replication health, and performance of business-critical PostgreSQL cluster nodes.

Get to know how to configure the PostgreSQL Cluster plugin and the monitoring metrics for providing in-depth visibility into cluster topology, primary failover, replication lag, WAL generation, background writer, and database performance.

Learn more https://www.site24x7.com/plugins/postgres-monitoring.html

## Quick installation

If you're using Linux servers, use the postgres cluster plugin installer that checks the prerequisites and installs the plugin with a bash script. You don't need to manually set up the plugin if you're using the installer.

Execute the command below in the terminal to run the installer and follow the instructions displayed on-screen:

```bash
wget https://raw.githubusercontent.com/site24x7/plugins/master/postgres_cluster/installer/Site24x7PostgresClusterPluginInstaller.sh && sudo bash Site24x7PostgresClusterPluginInstaller.sh
```

If you're using Windows servers, run the PowerShell installer in an elevated PowerShell prompt:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; iex ((New-Object System.Net.WebClient).DownloadString('https://raw.githubusercontent.com/site24x7/plugins/master/postgres_cluster/installer/Site24x7PostgresClusterPluginInstaller.ps1'))
```

### Prerequisites

- Download and install the latest version of the [Site24x7 agent](https://www.site24x7.com/app/client#/admin/inventory/add-monitor) in the server where you plan to run the plugin.
- Python version 3 or higher.
- Execute the following command in your server to install psycopg2: 

		pip3 install psycopg2-binary

### Plugin Installation  

- Create a directory named `postgres_cluster`.

	```bash
	mkdir postgres_cluster
	cd postgres_cluster/
	```
  
- Download all the files and place it under the `postgres_cluster` directory.

	```bash
	wget https://raw.githubusercontent.com/site24x7/plugins/master/postgres_cluster/postgres_cluster.py
	wget https://raw.githubusercontent.com/site24x7/plugins/master/postgres_cluster/postgres_cluster.cfg
	```
 
- Execute the following command in your server to install psycopg2: 

	```bash
	pip3 install psycopg2-binary
	```
 
- Ensure **pg_monitor** or **pg_read_all_stats** permission is provided to the user. For example, create a user `site24x7` with password `site24x7` and provide `pg_monitor` permission to the `site24x7` user created. You can also run the helper script in `prerequisites/create_user.sh` or `prerequisites/create_user.sql`.
  
- Execute the below command with appropriate arguments to check for the valid json output:

	```bash
	python3 postgres_cluster.py --nodes "127.0.0.1:5441:8001,127.0.0.1:5442:8002,127.0.0.1:5443:8003" --username "site24x7" --password "password" --db "postgres"
	```
 
- Provide your PostgreSQL cluster configurations in postgres_cluster.cfg file.

    ```ini
    [global_configurations]
    use_agent_python=0
    redirect_output=1

    [postgres_cluster]
    nodes="127.0.0.1:5441:8001,127.0.0.1:5442:8002,127.0.0.1:5443:8003"
    username="site24x7"
    password="password"
    db="postgres"
    patroni_port="8008"
    ```
    
  #### Linux

- Follow the steps in [this article](https://support.site24x7.com/portal/en/kb/articles/updating-python-path-in-a-plugin-script-for-linux-servers) to update the Python path in the postgres_cluster.py script.
- Move the directory `postgres_cluster` under the Site24x7 Linux Agent plugin directory: 
	```bash
	mv postgres_cluster /opt/site24x7/monagent/plugins/
 	```
 
  #### Windows 

- Since it's a Python plugin, to run the plugin in a Windows server please follow the steps in [this link](https://support.site24x7.com/portal/en/kb/articles/run-python-plugin-scripts-in-windows-servers). The remaining configuration steps are the same.


- Move the folder `postgres_cluster` under Site24x7 Windows Agent plugin directory: 
	```bash
	C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins
 	```

The agent will automatically execute the plugin within five minutes and user can see the plugin monitor under Site24x7 > Plugins > Plugin Integrations.

## PostgreSQL Cluster Monitoring Plugin Metrics

| **Metric Name**                    | **Description**                                                                        |
|-------------------------------------|----------------------------------------------------------------------------------------|
| Nodes Total                         | The total count of configured cluster nodes.                                           |
| Nodes Up                            | The number of cluster nodes currently reachable and responding to probes.              |
| Primary Count                       | The number of reachable nodes operating in read-write primary mode.                     |
| No Primary Flag                     | Alert flag indicating zero primary nodes are reachable (1 if no primary, 0 otherwise). |
| Split Brain Flag                    | Critical alert flag indicating multiple nodes report primary status simultaneously.    |
| Primary Timeline                    | The active WAL timeline ID; increments automatically upon failover or promotion.       |
| Max Replay Backlog                  | The worst-case replication replay backlog across connected standbys (bytes).           |
| Replication Slots Total             | The total count of replication slots configured on the primary node.                   |
| Replication Slots Active            | The count of replication slots actively streaming data to standbys.                    |
| Replication Slots Inactive          | The count of replication slots currently inactive or disconnected.                     |
| Physical Slots                      | The count of physical replication slots on the primary node.                           |
| Logical Slots                       | The count of logical replication slots on the primary node.                            |
| Max Slot Lag Bytes                  | The maximum retained WAL lag in bytes across all replication slots.                    |
| Cache Hit Ratio                     | The percentage of disk blocks read from shared buffer cache versus disk reads.         |
| Dead Tuples                         | The total count of dead rows/tuples awaiting autovacuum cleanup across databases.      |
| Oldest Transaction ID Age           | The number of transactions since the oldest unvacuumed transaction ID (xid freeze risk).|
| Total Commits                       | The total number of commits executed across all databases.                             |
| Total Rollbacks                     | The total number of rollbacks executed across all databases.                           |
| Total Conflicts                     | The number of conflicts that occurred during database operations.                      |
| Checkpoints Timed                   | The total number of scheduled checkpoints performed by checkpoint_timeout.             |
| Checkpoints Req                     | The total number of requested checkpoints triggered by WAL size or explicit commands.  |
| Checkpoint Write Time               | The total time spent writing during checkpoints in milliseconds.                       |
| Checkpoint Sync Time                | The total time spent syncing checkpoint files to disk in milliseconds.                 |
| Buffers Checkpoint                  | The number of buffers written during checkpoint processes.                             |
| Buffers Clean                       | The number of buffers written by the background writer process.                        |
| Maxwritten Clean                    | The number of times the background writer stopped because write limits were reached.   |
| Buffers Backend                     | The number of buffers written directly by the backend.                                 |
| Buffers Backend Fsync               | The number of times backend processes executed their own fsync calls.                  |
| Buffers Alloc                       | The total number of shared memory buffer allocations.                                  |
| Total Rows Inserted                 | The total number of rows inserted into tables across all databases.                    |
| Total Rows Updated                  | The total number of rows updated in tables across all databases.                       |
| Total Rows Deleted                  | The total number of rows deleted from tables across all databases.                     |
| Total Rows Fetched                  | The total number of rows fetched by queries across all databases.                      |
| Total Rows Returned                 | The total number of rows returned to client queries across all databases.              |
| Total Block Reads                   | The total number of blocks read from storage into memory.                              |
| Total Block Hits                    | The total number of block hits found in shared buffer cache.                           |
| Total Sessions                      | The cumulative number of client sessions established.                                  |
| Total Sessions Abandoned            | The number of client sessions terminated unexpectedly by client disconnect.            |
| Total Sessions Fatal                | The number of client sessions terminated due to fatal internal errors.                 |
| Total Sessions Killed               | The number of client sessions cancelled or terminated by administrator action.         |
| Transactions Open                   | The number of active transactions currently in progress.                               |
| Transactions Idle In Transaction    | The number of connections currently idle inside an uncommitted transaction.            |
| WAL Write Position                  | The current write position in Write Ahead Logging (MB).                                |
| WAL Insert Position                 | The current insert position in Write Ahead Logging (MB).                               |
| WAL Flush Position                  | The current flush position in Write Ahead Logging (MB).                                |
| WAL Files Count                     | The number of WAL segment files present in the WAL directory.                          |
| WAL Total Size                      | The total disk space consumed by WAL segment files (MB).                               |
| Archive Status Success              | The total count of successfully archived WAL segments (when archiving is enabled).     |
| Archive Status Failed               | The total count of failed WAL archiving attempts (when archiving is enabled).          |
| Archive Ready Files Count           | The number of WAL segment files waiting to be archived.                                |
| Recovery Conflicts Total            | The cumulative count of standby queries cancelled due to conflict with WAL recovery.  |
| Conflicts Tablespace                | Standby queries cancelled due to dropped tablespaces.                                  |
| Conflicts Lock                      | Standby queries cancelled due to table lock conflicts during WAL recovery.             |
| Conflicts Snapshot                  | Standby queries cancelled due to expired snapshot conflicts.                           |
| Conflicts Buffer Pin                | Standby queries cancelled due to pinned buffer contention during WAL recovery.         |
| Conflicts Deadlock                  | Standby queries cancelled due to deadlock during WAL recovery.                         |
| Oldest Running Transaction Age      | The elapsed time of the oldest currently running active transaction (seconds).         |
| Available Connections               | The number of remaining connection slots available before reaching max_connections.   |
| Connection Utilization Percent      | The percentage of total configured connection capacity currently consumed.             |

## Transactions and Session Metrics per Database

| **Metric Name**                    | **Description**                                                                        |
|-------------------------------------|----------------------------------------------------------------------------------------|
| Commits                            | The total number of commits executed in the specific database.                         |
| Rollbacks                          | The total number of rollbacks executed in the specific database.                       |
| Conflicts                          | The number of conflicts that occurred in the specific database.                        |
| Sessions                           | The total number of active sessions in the specific database.                          |
| Sessions Abandoned                 | The number of sessions abandoned by users in the specific database.                    |
| Sessions Fatal                     | The number of sessions that ended with a fatal error in the specific database.         |
| Sessions Killed                    | The number of sessions that were killed in the specific database.                      |
| Session Time                       | The total session time for all sessions in the specific database.                      |
| Sessions Active Time               | The total active time spent by sessions in the specific database.                      |
| Session Idle In Transaction Time   | The total idle time within transactions in the specific database.                      |

## Stats per Database

| **Metric Name**                    | **Description**                                                                        |
|-------------------------------------|----------------------------------------------------------------------------------------|
| Active Connections                  | The number of active connections in the specific database.                             |
| Size in MB                          | The size of the specific database in megabytes.                                        |
| Rows Inserted                       | The total number of rows inserted into the specific database.                          |
| Rows Updated                        | The total number of rows updated in the specific database.                             |
| Rows Deleted                        | The total number of rows deleted from the specific database.                           |
| Rows Fetched                        | The total number of rows fetched from the specific database.                           |
| Rows Returned                       | The total number of rows returned by queries in the specific database.                 |
| Block Reads                         | The total number of blocks read from disk in the specific database.                    |
| Block Hits                          | The total number of block hits (cache hits) in memory in the specific database.        |

## Cluster Nodes Details

| **Column Name**                    | **Description**                                                                        |
|-------------------------------------|----------------------------------------------------------------------------------------|
| name                                | Hostname, alias, or IP address of the node.                                            |
| host                                | Hostname or network IP address of the node.                                            |
| port                                | PostgreSQL listening port.                                                             |
| role                                | Cluster role of the node (primary, standby, or offline).                               |
| timeline                            | WAL timeline ID reported by the node.                                                  |
| up                                  | Reachability status of the node (1 if reachable, 0 otherwise).                         |
| is_primary                          | Flag indicating if the node is operating in read-write primary mode (1/0).             |
| response_time_ms                    | Health probe round-trip response time in milliseconds.                                 |
| patroni_state                       | DCS node state reported by Patroni REST API (running, streaming, demoted, or N/A).      |

## Replication Standbys Details

| **Column Name**                    | **Description**                                                                        |
|-------------------------------------|----------------------------------------------------------------------------------------|
| name                                | Application name or standby client identifier.                                         |
| client_addr                         | IP address of the streaming standby.                                                   |
| state                               | WAL streaming state (e.g. streaming, catchup, backup).                                 |
| sync_state                          | Synchronous replication state (sync, async, quorum, potential).                        |
| is_sync                             | Flag indicating if standby is in synchronous mode (1 if sync, 0 otherwise).            |
| replay_lag_bytes                    | Replay lag behind primary WAL write position in bytes.                                 |
| write_lag_bytes                     | Write lag behind primary WAL write position in bytes.                                  |
| flush_lag_bytes                     | Flush lag behind primary WAL write position in bytes.                                  |
