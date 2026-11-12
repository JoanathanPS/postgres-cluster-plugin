# Site24x7 PostgreSQL Cluster Monitoring Plugin (v5 Engine)

Production-grade, single-file Site24x7 Server Monitoring plugin for PostgreSQL clusters (Patroni, repmgr, Stolon, CloudNativePG, physical streaming replication, and multi-master) as well as standalone instances.

> [!NOTE]
> **Supported PostgreSQL Versions:** PostgreSQL 10 through PostgreSQL 17. PostgreSQL 10 is the minimum supported version (the setup SQL uses monitoring roles `pg_read_all_stats` / `pg_monitor` and `psql \if` conditionals introduced in PostgreSQL 10).

---

## 1. Quick 3-Step Installation

### Step 1: Create Monitoring Role on Primary
Run the following SQL on your primary PostgreSQL instance (it will automatically replicate to all standbys):

```sql
-- Create non-superuser monitoring role
CREATE ROLE site24x7 WITH LOGIN PASSWORD 'your_secure_password';

-- PostgreSQL 10+ standard monitoring roles
GRANT pg_monitor TO site24x7;
GRANT pg_read_all_stats TO site24x7;
GRANT pg_read_all_settings TO site24x7;

-- Optional: If pg_stat_statements is installed, allow execution
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') THEN
        GRANT EXECUTE ON FUNCTION pg_stat_statements_reset() TO site24x7;
    END IF;
END $$;
```

### Step 2: Deploy Plugin Directory
Copy `postgres_cluster.py` and `postgres_cluster.cfg` into the Site24x7 agent plugin folder:

| Operating System | Target Directory |
| :--- | :--- |
| **Linux** | `/opt/site24x7/monagent/plugins/postgres_cluster/` |
| **Windows** | `C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster\` |

Ensure `psycopg2` or `psycopg2-binary` is installed in the agent's Python environment:
```bash
# Linux
sudo /opt/site24x7/monagent/venv/bin/pip install psycopg2-binary
# Or system python:
sudo pip3 install psycopg2-binary
```

### Step 3: Configure & Verify
Edit `postgres_cluster.cfg` with your cluster host and monitoring password, then execute a dry run:
```bash
python3 postgres_cluster.py
```
A valid, complete JSON document will print to stdout with `"status": 1` and 0 errors.

---

## 2. Configuration Reference (`postgres_cluster.cfg`)

```ini
[global_configurations]
use_agent_python=0
redirect_output=1

[postgres_cluster]
# Monitoring mode: auto | standalone | cluster (default: auto)
# - auto: automatically detects whether target is a standalone instance or a cluster
# - standalone: monitors database independently without requiring primary/replica topology
# - cluster: enforces cluster-specific discovery, topology, and failover checks
monitor_mode="auto"

# Seed host: IP address or hostname of any cluster node (or standalone host)
cluster_host="127.0.0.1"

# Target PostgreSQL server port (default 5432)
postgres_port=5432

# Patroni REST API port (default 8008; 0 to disable REST discovery)
patroni_port=8008

# Monitoring credentials
username="site24x7"
password="your_secure_password"

# Database for initial connection (default postgres)
db="postgres"

# Optional cluster name override
cluster_name="production-cluster"

# Address translation map (for Docker / NAT / Kubernetes / port-forwarding)
# address_map="pg-node1:5432=10.0.0.1:5432,pg-node1:8008=10.0.0.1:8008"

# Explicit durable state directory override
# state_dir="/var/lib/site24x7/postgres_cluster"

# TLS / SSL connection parameters
sslmode="prefer"
# sslrootcert="/etc/ssl/certs/pg_ca.crt"
```

### Multi-Instance Monitoring
To monitor multiple PostgreSQL clusters from the same agent host, create separate plugin directories named uniquely (e.g. `postgres_prod/` and `postgres_analytics/`), each containing `postgres_cluster.py` and `postgres_cluster.cfg`. The state store automatically isolates instances using a per-directory SHA-256 instance hash to prevent state collisions.

---

## 3. Monitoring Modes: Standalone vs Cluster

The plugin natively supports three monitoring modes configured via `monitor_mode`:

| Mode | Behavior & Detection | Target Environments |
| :--- | :--- | :--- |
| **`auto`** *(default)* | Safely detects whether the target is a standalone instance or a cluster. Distinguishes standalone instances from clusters by evaluating configured node specs, Patroni REST API discovery, cluster manager extensions (repmgr, Citus, CNPG, Stolon), and streaming replication connections. | Default out-of-the-box configuration for any PostgreSQL installation. |
| **`standalone`** | Disables cluster manager probes and bypasses all primary/replica topology requirements. Evaluates database-level health (connectivity, auth, version, connections, transaction age) and reports `UP` (`1`) for healthy standalone primaries and read replicas without reporting missing primary errors. | Standalone PostgreSQL servers, RDS/Cloud SQL single instances, or isolated read replicas. |
| **`cluster`** | Enforces cluster topology discovery and health evaluation. Requires at least one reachable primary; missing or unreachable primaries produce `CRITICAL c1: no primary reachable` and report `DOWN` (`0`). | Production HA clusters (Patroni, repmgr, CloudNativePG, physical streaming replication). |

### Standalone Read-Only Replica Monitoring
When pointed at a read-only PostgreSQL instance (such as a read replica or standby):
- Evaluates `SELECT pg_is_in_recovery()`.
- Uses recovery-safe WAL LSN tracking (`pg_last_wal_replay_lsn()` instead of `pg_current_wal_lsn()`), avoiding `ERROR: recovery is in progress`.
- Reports monitor `status: 1` (UP) as long as database queries succeed and authentication is valid.
- Cluster-only metrics (`Standbys_Expected`, `Standbys_Streaming`, `Sync_Standby_Count`) are reported as `0` or N/A without triggering cluster alerts.
- Offline node retention from previous cluster monitoring runs is suppressed so `Nodes_Total = 1` and `Nodes_Up = 1`.

### Minimum Privileges for Standalone Monitoring
The monitoring user requires `CONNECT` permission on the target database, plus read access to PostgreSQL stats views:
```sql
GRANT pg_read_all_stats TO site24x7;
GRANT pg_read_all_settings TO site24x7;
```
For PostgreSQL versions prior to 10, grant `SELECT` on `pg_stat_database`, `pg_stat_activity`, and `pg_stat_bgwriter`. Missing privileges on optional views (e.g. `pg_replication_slots`) are treated as non-fatal warnings in standalone mode.

---

## 4. Comprehensive Enum Reference Sheets

### 3.1 Node Roles (`Cluster_Role` & `role` column)
| Integer | Role Name | Description |
| :--- | :--- | :--- |
| `0` | `unknown` | Node status or role could not be resolved |
| `1` | `primary` | Read-write cluster leader (not in recovery) |
| `2` | `standby` | Read-only physical streaming replica |
| `3` | `witness` | Non-data quorum witness / arbiter |
| `4` | `offline` | Previously observed node that is uncontactable |
| `5` | `cascading` | Standby streaming from another standby |
| `6` | `delayed` | Standby with intentional `recovery_min_apply_delay` |
| `7` | `standby_leader` | Standby cluster leader (in Patroni multi-cluster) |

### 3.2 Cluster Health Severities (`Cluster_Health`)
| Integer | Severity | Site24x7 Plugin Status | Meaning |
| :--- | :--- | :--- | :--- |
| `0` | `OK` | `1` (UP) | Cluster is fully healthy and within all thresholds |
| `1` | `WARN` | `1` (UP) | Degraded redundancy, lag, or maintenance condition |
| `2` | `CRITICAL` | `0` (DOWN) | Outage, split brain, primary down, or data danger |

### 3.3 Health Condition Codes (`Health_Code`)
| Code | Severity | Description | Default Action Hint |
| :--- | :--- | :--- | :--- |
| `0` | `OK` | Normal cluster operation | none |
| `1` | `CRITICAL` | No primary reachable across any node | patronictl list; failover --candidate |
| `2` | `CRITICAL` | Split-brain (multiple active primaries) | fence rogue primary immediately |
| `3` | `CRITICAL` | No standbys streaming (zero redundancy) | check wal_sender limits and replication slots |
| `4` | `CRITICAL` | Synchronous standby deficit below quorum | review synchronous_standby_names |
| `5` | `CRITICAL` | Replication slot retained WAL >= 10 GB | verify standby or drop abandoned slot |
| `6` | `CRITICAL` | XID wraparound emergency (age >= 1.8B) | run VACUUM FREEZE immediately |
| `7` | `CRITICAL` | Standbys present but none eligible for failover | enable replication slots on standbys |
| `10` | `WARN` | One or more standby nodes down/unreachable | restart postgresql service on node |
| `11` | `WARN` | Standby replay lag exceeds threshold (> 60s) | check standby I/O saturation and network |
| `12` | `WARN` | Inactive replication slot accumulating WAL | verify slot consumer is running |
| `13` | `WARN` | Standby on older timeline than primary | pg_rewind or resync standby from primary |
| `14` | `WARN` | Cluster failover occurred within warning window | verify previous primary re-joined as standby |
| `15` | `WARN` | XID wraparound warning (age >= 1.0B) | schedule autovacuum freeze on older tables |
| `16` | `WARN` | Connection pool saturation (>= 85%) | tune max_connections or deploy PgBouncer |
| `17` | `WARN` | WAL archive command failing | check archiver disk space and permissions |
| `18` | `WARN` | Stale statistics detected on major tables | run ANALYZE on active tables |

### 3.4 Standby Sync State (`sync` column)
| Integer | Mode | Description |
| :--- | :--- | :--- |
| `0` | `async` | Asynchronous replication (potential lag during failover) |
| `1` | `sync` | Synchronous replication (`FIRST / ANY` primary sync node) |
| `2` | `quorum` | Quorum-based synchronous commit group |

### 3.5 Patroni States (`patroni_state` column)
| Integer | State Name | Meaning |
| :--- | :--- | :--- |
| `0` | `unknown` | State string not recognized |
| `1` | `running` | Node is running normally under Patroni |
| `2` | `stopped` | Node process has stopped |
| `3` | `starting` | Node is starting or recovering |
| `4` | `stopping` | Node is gracefully shutting down |
| `5` | `restart_failed` | Patroni failed to restart the PostgreSQL process |
| `6` | `crashed` | Node experienced abnormal termination |
| `7` | `standby_leader`| Standby cluster leader |
| `8` | `na` | Native PostgreSQL or non-Patroni cluster |

---

## 4. Child Tables Reference (Site24x7 Enforced Constraints)

The plugin exposes exactly 7 child tables. Every table satisfies Site24x7 hard constraints: $\le 15$ columns, $\le 5$ string columns, and $\le 25$ rows.

1. **`Cluster_Nodes`**: Cluster roster detailing node names, roles, health status, timelines, lag, response times, and connection percentages.
2. **`Node_Snapshot`**: Per-node diagnostic view detailing uptime, active query count, idle-in-transaction count, and longest query duration.
3. **`Replication_Links`**: Active streaming replication links from `pg_stat_replication` showing state, sync state, and byte/second replay lag.
4. **`Replication_Slots`**: Replication slots from `pg_replication_slots` showing active status, retained WAL bytes, and slot type.
5. **`Database_Stats`**: Top databases ranked by disk size with connection counts and cache hit ratios.
6. **`Wait_Events`**: Aggregated active wait events from `pg_stat_activity` identifying current bottlenecks.
7. **`Topology`**: High-level cluster summary showing leader node, cluster manager, total nodes, and current timeline.

---

## 5. Threshold Reference

| Metric | Warn Threshold | Critical Threshold | Rationale |
| :--- | :--- | :--- | :--- |
| `Max_Replay_Lag_s` | $> 60.0\text{ s}$ | $> 600.0\text{ s}$ | Replay lag delays failovers and risks RPO |
| `Max_Slot_Retained_MB` | $> 1,024\text{ MB}$ | $> 10,240\text{ MB}$ | Retained WAL risks disk exhaustion on primary |
| `Primary_Connection_Pct`| $\ge 85\%$ | $\ge 95\%$ | Prevents connection starvation for applications |
| `Primary_XID_Wraparound_Pct`| $\ge 50\%$ | $\ge 90\%$ | Critical risk of PostgreSQL entering read-only mode |
| `Failover_Age_s` | $\le 900\text{ s}$ | — | Alert operator to review cluster after recent failovers |
| `Primary_Archive_Failed` | $\ge 1$ | — | Failing archiver causes WAL directory accumulation |

---

## 6. Operational Runbooks for Health Codes

### Code 1: `CRITICAL c1: no primary reachable`
- **Root Cause**: The primary node crashed, network partition occurred, or an automatic failover is hung.
- **Runbook**:
  1. Inspect cluster status:
     ```bash
     patronictl -c /etc/patroni/patroni.yml list
     ```
  2. If a leader election failed, manually initiate failover to the healthiest standby:
     ```bash
     patronictl -c /etc/patroni/patroni.yml failover --candidate <standby_node>
     ```
  3. Verify PostgreSQL logs on the old primary for OOM kill or hardware failure.

### Code 2: `CRITICAL c2: split brain detected: multiple concurrent primaries`
- **Root Cause**: Multiple nodes report `pg_is_in_recovery() = false`, often due to DCS partition or broken fencing.
- **Runbook**:
  1. Immediately identify which node has the higher timeline:
     ```sql
     SELECT timeline_id FROM pg_control_checkpoint();
     ```
  2. Stop the rogue primary immediately:
     ```bash
     pg_ctl -D /var/lib/postgresql/data stop -m immediate
     ```
  3. Rewind or re-clone the rogue node from the true primary using `pg_rewind` or Patroni reinit:
     ```bash
     patronictl -c /etc/patroni/patroni.yml reinit <cluster_name> <rogue_node>
     ```

### Code 5: `CRITICAL c5: replication slot retained WAL exceeds 10 GB`
- **Root Cause**: An inactive or disconnected replication slot is holding WAL segments on the primary, risking disk exhaustion.
- **Runbook**:
  1. Identify the offending slot:
     ```sql
     SELECT slot_name, slot_type, active, pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) / (1024*1024) AS retained_mb
     FROM pg_replication_slots
     ORDER BY retained_mb DESC;
     ```
  2. If the slot consumer is permanently decommissioned, drop it:
     ```sql
     SELECT pg_drop_replication_slot('offending_slot_name');
     ```

### Code 6: `CRITICAL c6: transaction ID wraparound critical (>= 1.8B)`
- **Root Cause**: Autovacuum is falling behind or blocked by long-running transactions, prepared transactions, or abandoned slots.
- **Runbook**:
  1. Identify oldest transactions and relations:
     ```sql
     SELECT datname, age(datfrozenxid) FROM pg_database ORDER BY age(datfrozenxid) DESC;
     ```
  2. Terminate long-running queries or idle-in-transaction connections holding back `xmin`:
     ```sql
     SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state LIKE 'idle in transaction%' AND age(backend_xmin) > 100000000;
     ```
  3. Run aggressive manual vacuum freeze on the oldest tables:
     ```sql
     VACUUM FREEZE ANALYZE VERBOSE <table_name>;
     ```
