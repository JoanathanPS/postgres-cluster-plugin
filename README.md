Plugin for PostgreSQL Cluster Monitoring
=========================================

PostgreSQL is a powerful, open-source object-relational database management system. When deployed in high-availability clusters (such as Patroni, streaming replication, or cloud architectures), continuous cluster-level observability across primary and standby nodes is critical. Analyze and optimize your PostgreSQL cluster by configuring our PostgreSQL Cluster plugin and proactively monitor availability, failover state, replication lag, and node health of your cluster.

Get to know how to configure the PostgreSQL Cluster plugin and the monitoring metrics for providing in-depth visibility into cluster topology, failover dynamics, replication delay, and node performance across 9 specialized dashboard tabs and a built-in Summary view.

Learn more: https://www.site24x7.com/plugins/postgres-monitoring.html

## Quick Installation

If you're using Linux servers, use the postgres cluster plugin installer that checks the prerequisites and installs the plugin with a bash script. You don't need to manually set up the plugin if you're using the installer.

```bash
wget https://raw.githubusercontent.com/site24x7/plugins/master/postgres_cluster/installer/Site24x7PostgresClusterPluginInstaller.sh && sudo bash Site24x7PostgresClusterPluginInstaller.sh
```

### Prerequisites

- Download and install the latest version of the [Site24x7 agent](https://www.site24x7.com/app/client#/admin/inventory/add-monitor) on the server where you plan to run the plugin.
- Python version 3 or higher.
- Install psycopg2 binary on your server:

	```bash
	pip3 install psycopg2-binary
	```

- Ensure **pg_read_all_stats** permission is provided to the monitoring user. For example, create a user `site24x7` with password `site24x7` and grant `pg_read_all_stats`:
  
	```sql
	CREATE USER site24x7 WITH PASSWORD 'site24x7';
	GRANT pg_read_all_stats TO site24x7;
	```

### Plugin Installation

- Create a directory named `postgres_cluster`.

	```bash
	mkdir postgres_cluster
	cd postgres_cluster/
	```

- Download all the files and place them under the `postgres_cluster` directory:

	```bash
	wget https://raw.githubusercontent.com/site24x7/plugins/master/postgres_cluster/postgres_cluster.py
	wget https://raw.githubusercontent.com/site24x7/plugins/master/postgres_cluster/postgres_cluster.cfg
	```

- Execute the below command with appropriate arguments to check for valid JSON output:

	```bash
	python3 postgres_cluster.py --cluster_host "127.0.0.1" --postgres_port 5432 --username "site24x7" --password "site24x7" --db "postgres"
	```

- Provide your PostgreSQL Cluster configuration in `postgres_cluster.cfg`:

    ```ini
    [global_configurations]
    use_agent_python=0
    redirect_output=1

    [postgres_cluster]
    cluster_host="127.0.0.1"
    postgres_port=5432
    patroni_port=8008
    username="site24x7"
    password="site24x7"
    db="postgres"
    monitor_mode="auto"
    compat_official=1
    ```

#### Linux

- Follow the steps in [this article](https://support.site24x7.com/portal/en/kb/articles/updating-python-path-in-a-plugin-script-for-linux-servers) to update the Python path in the postgres_cluster.py script.
- Move the directory `postgres_cluster` under the Site24x7 Linux Agent plugin directory:
	```bash
	mv postgres_cluster /opt/site24x7/monagent/plugins/
 	```

#### Windows

- Since it's a Python plugin, to run the plugin in a Windows server please follow the steps in [this link](https://support.site24x7.com/portal/en/kb/articles/run-python-plugin-scripts-in-windows-servers).
- Move the folder `postgres_cluster` under Site24x7 Windows Agent plugin directory:
	```cmd
	C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins
 	```

The agent will automatically execute the plugin within five minutes and the user can see the plugin monitor under Site24x7 > Plugins > Plugin Integrations.

---

## PostgreSQL Cluster Summary Metrics

The following metrics are displayed on the default built-in **Summary** dashboard tab to provide an immediate operational health and availability overview:

| **Metric Name** | **Description** |
|-----------------|-----------------|
| Cluster_Health | Cluster health severity: 0 = HEALTHY, 1 = DEGRADED, 2 = CRITICAL. |
| Nodes_Up | Total number of currently reachable cluster nodes. |
| Standbys_Streaming | Number of standby nodes actively streaming WAL from the primary. |
| Max_Replay_Lag_s | Maximum replication replay lag observed across all active standbys in seconds. |

---

## Cluster Overview & Topology (Tab 1: Cluster)

| **Metric Name** | **Description** |
|-----------------|-----------------|
| Health_Code | Stable numeric health condition code (0 to 19) for deterministic alerting. |
| Cluster_Role | Observed role of target entry point (primary, standby, or offline). |
| Topology_Type | Detected cluster architecture: Patroni (1), repmgr (2), native streaming (3), multi-master (4), etc. |
| Nodes_Total | Total count of active and historical nodes tracked in the cluster. |
| Nodes_Down | Number of currently unreachable or offline nodes in the cluster. |
| Nodes_Omitted | Number of discovered nodes omitted beyond the 25-row tabular limit. |
| Primary_Timeline | Current WAL timeline ID of the primary database engine. |
| Timeline_Spread | Difference between the highest and lowest timelines observed across cluster nodes. |
| Failover_Age_s | Elapsed time in seconds since the last detected cluster failover event. |
| Failover_Count_24h | Total count of failover transitions detected within the rolling 24-hour window. |
| Health_Reason | Human-readable explanation of current cluster health state. |
| First_Attention_Node | Specific cluster node requiring immediate administrative attention. |
| First_Attention_Issue | Concise operational summary of the issue affecting the attention node. |

### Topology (Child Table)

| **Column Name** | **Description** |
|-----------------|-----------------|
| name | Unique row identifier for the cluster topology summary. |
| cluster_type | Detected cluster management engine (e.g., Patroni, Native Physical, repmgr). |
| cluster_name | Configured or discovered cluster identifier. |
| manager | High-availability orchestrator or consensus layer in use. |
| primary | Current active primary / leader node name. |
| timeline | Primary WAL timeline identifier. |
| total_nodes | Total number of nodes configured or discovered in the cluster. |
| healthy_nodes | Total number of nodes reporting healthy operational state. |
| election_age_s | Time elapsed in seconds since the current primary was elected or promoted. |
| status | Operational status of the topology record (1 = UP, 0 = DOWN). |

---

## Cluster Nodes & Standby States (Tab 2: Nodes)

| **Metric Name** | **Description** |
|-----------------|-----------------|
| Standbys_Expected | Number of standbys expected to stream WAL from the primary. |
| Standby_Disconnect_Flag | Dynamic indicator: 1 if any expected standby is disconnected, 0 otherwise. |
| Sync_Standby_Count | Count of standbys configured for synchronous or quorum replication. |
| Cascading_Standby_Count | Count of cascading standbys streaming from an intermediate replica. |
| Delayed_Standby_Count | Count of standbys configured with deliberate replay lag. |
| Slowest_Node | Name of the standby node currently exhibiting the highest replay delay. |
| Max_Replay_Backlog | Maximum bytes of unreplayed WAL pending on any active standby. |

### Cluster_Nodes (Child Table)

| **Column Name** | **Description** |
|-----------------|-----------------|
| name | Cluster node name or host identifier. |
| role | Observed node role: primary, standby, standby_leader, offline, or unknown. |
| status | Reachability status of the node (1 = UP, 0 = DOWN). |
| timeline | WAL timeline ID currently running on this node. |
| connections | Active client connections connected to this node. |
| replay_lag_b | WAL replay lag in bytes relative to primary write position. |
| replay_lag_s | Replication replay delay in seconds. |
| sync_state | Standby synchronization mode: async, sync, or quorum. |
| state | Node operational state from cluster manager (e.g. running, streaming, stopped). |

### Node_Snapshot (Child Table)

| **Column Name** | **Description** |
|-----------------|-----------------|
| name | Cluster node identifier. |
| role | Current node role (primary, standby). |
| status | Node availability indicator (1 = UP, 0 = DOWN). |
| timeline | Observed node timeline ID. |
| conn_pct | Connection pool utilization percentage on this node. |
| wal_rate_mb | Estimated WAL generation or receive rate in MB/s. |
| read_iops | Estimated database read operations per second. |
| write_iops | Estimated database write/DML operations per second. |
| cache_hit | Buffer cache hit ratio observed on this node. |

---

## Primary Node Write Performance (Tab 3: Primary)

| **Metric Name** | **Description** |
|-----------------|-----------------|
| Primary_Up | Availability status of the active primary node (1 = UP, 0 = DOWN). |
| Primary_Data_Age_s | Age of the latest write transaction on primary in seconds. |
| Primary_Data_Stale | Flag indicating primary telemetry is stale or delayed. |
| Primary_Connections | Total active client connections to the primary instance. |
| Primary_Connection_Pct | Primary connection slot utilization percentage. |
| Primary_Commits_s | Transaction commits per second on the primary. |
| Primary_Rollbacks_s | Transaction rollbacks per second on the primary. |
| Primary_Tup_Inserted_s | Rows inserted per second on the primary. |
| Primary_Tup_Updated_s | Rows updated per second on the primary. |
| Primary_Tup_Deleted_s | Rows deleted per second on the primary. |
| Primary_Cache_Hit_Ratio | Primary buffer cache hit ratio percentage. |
| Primary_Blks_Read_s | Disk blocks read per second on the primary. |
| Primary_Blocked_Locks | Number of queries currently blocked waiting for table/row locks. |
| Primary_Longest_Txn_s | Elapsed duration of the longest currently active transaction in seconds. |
| Primary_Idle_In_Txn | Number of client sessions idling within an uncommitted transaction. |

---

## Replication Links & Slots (Tab 4: Replication)

| **Metric Name** | **Description** |
|-----------------|-----------------|
| Inactive_Slots_Count | Count of replication slots currently inactive (risking disk saturation). |
| Max_Slot_Retained_MB | Maximum WAL volume retained by any single replication slot in MB. |
| Slot_Risk | Risk severity code for replication slot WAL retention. |
| Logical_Replication_Used | Flag indicating active logical replication subscriptions or slots. |
| Subscription_Count | Count of configured pg_stat_subscription workers. |
| Subscription_Errors | Count of subscription workers reporting apply or connection errors. |

### Replication_Links (Child Table)

| **Column Name** | **Description** |
|-----------------|-----------------|
| name | Client identifier or application name of the streaming standby. |
| client_addr | IP address of the connected standby. |
| state | WAL sender state (e.g. streaming, catchup, backup). |
| sync_state | Sync state assigned by primary (async, sync, potential, quorum). |
| sent_lsn | Most recent WAL LSN sent by the primary. |
| replay_lsn | Most recent WAL LSN replayed and flushed by the standby. |
| replay_lag_b | WAL bytes remaining to be replayed by this standby. |
| replay_lag_s | Replication replay lag in seconds. |
| status | Health status of the replication link (1 = UP, 0 = DOWN). |

### Replication_Slots (Child Table)

| **Column Name** | **Description** |
|-----------------|-----------------|
| name | Replication slot name. |
| plugin | Logical decoding output plugin (e.g. pgoutput), or physical. |
| slot_type | Slot type: physical or logical. |
| active | Boolean flag indicating whether a consumer is actively streaming. |
| retained_bytes | Volume of WAL bytes retained on disk exclusively for this slot. |
| status | Health status of the slot (1 = Active, 0 = Inactive/Risk). |

---

## Cluster Performance & Buffers (Tab 5: Performance)

| **Metric Name** | **Description** |
|-----------------|-----------------|
| Cache_Hit_Ratio | Overall cluster buffer cache hit ratio percentage. |
| Blks_Read_s | Total disk blocks read per second across cluster. |
| Blks_Hit_s | Buffer cache block hits per second. |
| Seq_Scans_s | Sequential table scans executed per second. |
| Idx_Scans_s | Index scans executed per second. |
| Total Rows Inserted | Aggregate rows inserted into database since statistics reset. |
| Total Rows Updated | Aggregate rows updated in database since statistics reset. |
| Total Rows Deleted | Aggregate rows deleted from database since statistics reset. |
| Buffers Checkpoint | Number of shared memory buffers written during checkpoints. |
| Buffers Clean | Number of buffers written by the background writer clean scan. |
| Maxwritten Clean | Times the background writer stopped a clean scan due to writing limit. |
| Buffers Backend | Number of buffers written directly by backend client processes. |
| Buffers Backend Fsync | Number of backend fsync calls executed directly to disk. |

---

## Sessions & Lock Contention (Tab 6: Sessions)

| **Metric Name** | **Description** |
|-----------------|-----------------|
| Active_Sessions | Total active database worker processes currently executing statements. |
| Blocked_Sessions | Sessions currently waiting on heavy locks held by other transactions. |
| Long_Running_Queries | Queries executing longer than the configured long-query threshold. |
| Idle Transactions | Total sessions idling inside open transactions. |
| Total Conflicts | Recovery conflicts encountered on standby replicas. |
| Total Sessions Abandoned | Client sessions abandoned unexpectedly by clients. |
| Total Sessions Fatal | Client sessions terminated by fatal database backend errors. |
| Locks Count | Total lock objects held across databases. |
| Max Connections | Maximum allowed simultaneous database connections configured. |

### Wait_Events (Child Table)

| **Column Name** | **Description** |
|-----------------|-----------------|
| name | Unique wait event row key. |
| wait_event_type | Class of wait event (e.g. Lock, IO, IPC, Client). |
| wait_event | Specific wait event name (e.g. relation, DataFileRead, ClientRead). |
| waiting_sessions | Number of concurrent database sessions currently blocked on this event. |
| status | Operational status of wait event sample (1 = Normal). |

---

## Capacity & WAL Telemetry (Tab 7: Capacity & WAL)

| **Metric Name** | **Description** |
|-----------------|-----------------|
| WAL_Rate_MBs | Rate of Write-Ahead Log generation in megabytes per second. |
| Primary_WAL_Rate_MBs | WAL generation rate measured exclusively on the primary engine. |
| Archive_Mode | Configuration status of database WAL archiving (0 = off, 1 = on). |
| Archive_Failed_Count | Cumulative count of failed WAL file archive executions. |
| Archive_Ready_Count | Number of completed WAL segment files currently queued for archiving. |
| Last_Archived_WAL | Filename of the most recently successfully archived WAL segment. |
| State_Age_s | Age of the persistent local cluster state in seconds. |
| State_IO_Errors | Count of disk I/O errors encountered while saving cluster tracking state. |

---

## Database Discovery & Stats (Tab 8: Databases)

| **Metric Name** | **Description** |
|-----------------|-----------------|
| Database Count | Total count of distinct databases discovered on the primary cluster. |
| Table Count | Total number of user tables present in monitored database. |
| Max_Temp_MB | Maximum temporary disk space consumed by queries in megabytes. |
| XID_Wraparound_Pct | Transaction ID consumption percentage toward forced autovacuum wraparound. |
| Dead_Tuples_Total | Total dead tuples awaiting autovacuum cleanup across tables. |

### Database_Stats (Child Table)

| **Column Name** | **Description** |
|-----------------|-----------------|
| name | Name of discovered database. |
| active_connections | Number of active connections established to this database. |
| size_in_mb | Total storage footprint of this database in megabytes. |
| rows_inserted | Total rows inserted into this database. |
| rows_updated | Total rows updated in this database. |
| rows_deleted | Total rows deleted from this database. |
| rows_fetched | Total rows fetched from this database via queries. |
| rows_returned | Total rows returned by queries. |
| block_reads | Number of disk block reads executed. |
| block_hits | Number of buffer pool cache block hits. |

---

## Plugin Health & Diagnostics (Tab 9: Plugin)

| **Metric Name** | **Description** |
|-----------------|-----------------|
| Plugin_Version | Version identifier of the installed plugin script. |
| Collect_Duration_ms | Total execution duration of collection cycle in milliseconds. |
| Queries_Executed | Total number of diagnostic SQL queries executed during the cycle. |
| Collect_Warnings | Count of non-fatal warnings logged during collection. |
| Auth_Failure_Flag | Flag indicating authentication failure on one or more cluster nodes. |
| Budget_Exceeded | Flag indicating collection cycle exceeded its maximum execution deadline. |

---

## Recommended Thresholds

To prevent false alerts on dynamically sized clusters (2-node, 3-node, 5-node+) and eliminate redundant notifications, configure the following rules in **Admin > Configuration Profiles > Threshold and Availability Profile**:

| **Metric Name** | **Condition** | **Threshold Value** | **Duration** | **Resulting State** | **Operational Description** |
|---|---|---|---|---|---|
| `Cluster_Health` | `>=` | `1` | 1 poll (immediate) | **Trouble** | Cluster degraded: Standby node down, replication lag high (>60s), unconfirmed failover recovery, or timeline divergence. |
| `Cluster_Health` | `>=` | `2` | 1 poll (immediate) | **Critical** | Cluster outage: No primary reachable, split-brain detected, zero standbys streaming, or sync standby quorum deficit. |
| `Max_Replay_Lag_s` | `>` | `60` | 2 consecutive polls | **Trouble** | Standby replication replay lag exceeds 60s (early warning filter for transient batch load spikes). |

---

## Screenshots
<img width="1642" height="807" alt="ss1" src="https://github.com/user-attachments/assets/f4be21e7-659f-415f-9e54-4d38fad29d93" />
<img width="1645" height="751" alt="ss2" src="https://github.com/user-attachments/assets/1f71f19b-4701-4685-9ba1-dd97b98e40a4" />

