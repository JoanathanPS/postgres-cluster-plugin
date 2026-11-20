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

## 3. Network Architecture & Single-Endpoint Discovery

The plugin eliminates the requirement to manually configure individual backend PostgreSQL node IP addresses or rely on static node lists.

### Architecture Overview

```
                      +-----------------------------------+
                      |   Site24x7 Agent Host             |
                      |   (postgres_cluster plugin)       |
                      +-----------------+-----------------+
                                        | Single cluster entry point:
                                        | cluster_host="cluster-lb.corp"
                                        v
         +-------------------------------------------------------------+
         |     Cluster Entry Point / Load Balancer (HAProxy / VIP)     |
         |  - Port 5500: Write pool (routes to active primary)         |
         |  - Port 5501: Read pool (load balances active standbys)     |
         |  - Port 7000: HAProxy stats interface (/stats;csv)         |
         +------+----------------------+-------------------------+-----+
                |                      |                         |
                v                      v                         v
       +-----------------+    +-----------------+       +-----------------+
       | pg-node1 (5441) |    | pg-node2 (5442) |       | pg-node3 (5443) |
       | Patroni (8001)  |    | Patroni (8002)  |       | Patroni (8003)  |
       +-----------------+    +-----------------+       +-----------------+
```

### Discovery & Port Resolution Engine

The plugin needs **one reachable address**. It tries each source below in order and
stops at the first that answers, so the sources are ordered by how authoritative
they are, not by how exotic the setup is.

**Only step 1 requires an HA manager, and only the optional naming lookup in step 2
touches a proxy. A plain two-node streaming pair with neither is fully supported.**

1. **Patroni REST API** (`patroni_port`, `patroni_ports`) — authoritative when present.
   Probes candidate REST ports on `cluster_host` (e.g. `8008`, or `8001-8003` for a
   port-forwarded lab) and reads `/cluster` for exact node names, roles, states,
   timelines and lag, plus `/history` for failover age and 24-hour failover count.
   This is the only source that can give a true failover history, so it is tried first.

2. **SQL topology discovery** — the general case; needs nothing but PostgreSQL.
   Connects to the seed endpoint and reads the cluster out of the catalogs:
   - `pg_is_in_recovery()` to tell a primary from a standby.
   - If the seed is a **standby**, `pg_stat_wal_receiver` is followed upstream to the
     primary and discovery is retried once — so you may point the plugin at *any*
     node, not just the leader.
   - `pg_stat_replication` on the primary for every attached standby, with sync state
     and byte lag.
   - `inet_server_addr()`, `current_setting('port')` and `cluster_name` for identity.

   Candidate ports: an explicitly configured `write_port` first, then the plain
   PostgreSQL port (`postgres_port`, default 5432). Only ports the operator actually
   configured are dialled — the plugin never guesses conventional proxy ports, because
   that would mean offering the monitor's credentials to whatever else is listening.
   This covers a direct node, a VIP, a floating IP, HAProxy and pgpool-II identically,
   because to PostgreSQL they are all just a connection.

   A proxy stats endpoint (`discovery_port`), when reachable, is used
   **only to put a friendly backend name on the primary**. Without it the primary is
   named from `address_map`, then `cluster_name`, then its own `host:port`. Losing the
   stats endpoint costs you a nicer label and nothing else.

3. **Explicit node list** (`nodes`) — whatever you configured, used as-is. Setting
   `nodes` disables automatic discovery entirely, which is the escape hatch for
   topologies the catalogs cannot express (see "Cluster Support Levels").

4. **Single node** — the configured `cluster_host` on its own, for a standalone
   instance or when nothing above answered.

Nodes found by any source are then merged with any expected members declared in
`address_map`, in the proxy stats backend list, or in `nodes`, so a node that is
currently **stopped** still appears as a row rather than silently vanishing.

#### Mapped Port Resolution (`node_ports`, `address_map`)

Discovery returns addresses as the *cluster* sees them (container IPs, internal
hostnames). `address_map` and `node_ports` translate those to addresses the agent can
actually reach:

- `address_map="pg-node1:5432=127.0.0.1:5441"` — explicit `host:port` pair.
- `address_map="pg-node1=5441"` — port-only shorthand, resolved against `cluster_host`.
- `node_ports="5441-5443"` — automatic indexing by the trailing digit in the node name
  (`pg-node2` → the 2nd port). The node name is stripped of any `:port` suffix and
  skipped if it is a bare IPv4 address, so an address is never mistaken for an index.

#### Zero-Reconfiguration Failover

When the primary is lost, the HA manager promotes a replica. On the next collection
cycle the plugin re-runs discovery from the same single address and finds the new
leader — no configuration change. Rate metrics (`*_s`) are suppressed for one cycle
after a leader change, because differencing counters across two different servers
would report a meaningless spike. Stopped nodes are reported as `offline` with their
last known role, while the cluster stays `UP` (`1`) as long as a primary is serving;
replication degradation is reported through `Cluster_Health` and `Health_Reason`
instead of through availability.

### Docker Desktop (Windows Host) Network Mapping Reference

In Docker Desktop on Windows with WSL2, internal bridge subnets (e.g. `172.18.0.0/16`) are encapsulated inside the WSL2 Linux VM and are not directly routable from Windows. Communication occurs through published port forwards on the Windows loopback interface (`127.0.0.1`):

| Service | Internal Docker Target | Windows Host Port / Endpoint | Protocol / Interface |
| :--- | :--- | :--- | :--- |
| **HAProxy Stats** | `patroni-haproxy:7000` | `http://127.0.0.1:7000/;csv` | HTTP Stats (CSV & HTML) |
| **HAProxy Write Pool** | `patroni-haproxy:5000` | `127.0.0.1:5500` | PostgreSQL TCP (Leader) |
| **HAProxy Read Pool** | `patroni-haproxy:5001` | `127.0.0.1:5501` | PostgreSQL TCP (Replicas) |
| **PostgreSQL Node 1** | `pg-node1:5432` | `127.0.0.1:5441` | PostgreSQL TCP (Direct) |
| **PostgreSQL Node 2** | `pg-node2:5432` | `127.0.0.1:5442` | PostgreSQL TCP (Direct) |
| **PostgreSQL Node 3** | `pg-node3:5432` | `127.0.0.1:5443` | PostgreSQL TCP (Direct) |
| **Patroni API Node 1** | `pg-node1:8008` | `http://127.0.0.1:8001/patroni` | Patroni REST (HTTP) |
| **Patroni API Node 2** | `pg-node2:8008` | `http://127.0.0.1:8002/patroni` | Patroni REST (HTTP) |
| **Patroni API Node 3** | `pg-node3:8008` | `http://127.0.0.1:8003/patroni` | Patroni REST (HTTP) |
| **etcd DCS** | `etcd:2379` | `127.0.0.1:2379` | etcd Client API |

Inside the Docker bridge network, containers communicate directly using stable Docker DNS service names (`pg-node1`, `pg-node2`, `pg-node3`, `etcd`), ensuring internal routing and health checks are independent of external port bindings.

---

## 4. Monitoring Modes: Standalone vs Cluster

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
