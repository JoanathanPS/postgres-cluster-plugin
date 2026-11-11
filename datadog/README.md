# Datadog PostgreSQL Integration & Comparative Analysis

This directory contains the complete source code, configuration templates, dashboards, monitors, and setup tooling from the official **Datadog PostgreSQL Integration (v23.14.0)**, extracted directly from the local Datadog Agent installation on this machine (`C:\Program Files\Datadog\Datadog Agent`).

It serves as a benchmark and architectural reference to compare and improve our **Site24x7 PostgreSQL Cluster Monitoring Plugin**.

---

## Directory Structure

```text
datadog/
├── check/                                # Complete Python implementation of Datadog's PostgreSQL check
│   ├── postgres.py                      # Main check orchestrator (connect, health, collect, tag)
│   ├── util.py                          # SQL queries, version-specific catalog selectors, relations
│   ├── statements.py                    # Query performance metrics & pg_stat_statements parser
│   ├── statements_v2.py                 # Modern statement tracking pipeline
│   ├── statement_samples.py             # Query plan & execution sampling logic
│   ├── connection_pool.py               # LRU connection pool manager & health checks
│   ├── cursor.py                        # Resilient cursor wrapper with statement timeout
│   ├── discovery.py                     # Automatic database discovery logic
│   ├── diagnose.py                      # Diagnostic report generation & connectivity testing
│   ├── relationsmanager.py              # Per-table / per-index metrics & relation cache
│   ├── metadata.py                      # Engine version & system identifier collection
│   ├── metrics_cache.py                 # In-memory caching for query metrics & schema stats
│   ├── version_utils.py                 # PostgreSQL version parsing (9.x, 10-17+)
│   └── config_models/                   # Pydantic-like YAML configuration models & validators
├── dashboards/                          # Official Datadog JSON dashboards
│   ├── postgresql_dashboard.json        # Timeboard dashboard (metrics, activity, disk, memory)
│   └── postgresql_screenboard_dashboard.json # Screenboard layout (Activity, Locks, Buffers, Rows)
├── monitors/                            # Datadog alert templates
│   ├── percent_usage_connections.json   # Connection limit warning alert
│   └── replication_delay.json           # Replication lag alert threshold
├── setup/                               # Setup & launcher tools for Windows
│   ├── postgres_datadog_setup.sql       # SQL script to create 'datadog' user & grant pg_monitor
│   ├── conf.yaml                        # Ready-to-use Datadog postgres check configuration
│   ├── install_postgres_conf.ps1        # Admin script to deploy conf.yaml and restart agent
│   └── launch_datadog_gui.ps1           # Script to launch the Datadog Agent Manager GUI window
├── conf.yaml.example                    # Datadog's exhaustive 1,000+ line config reference
├── metadata.csv                         # 200+ Datadog PostgreSQL metrics with types, units & descriptions
└── README.md                            # This comprehensive guide & comparative analysis
```

---

## How to See Datadog's Window (3 Viewing Options)

Datadog provides three different "windows" to observe its metrics, checks, and dashboards:

### Option 1: Datadog Agent Manager (Local Windows Desktop GUI)

The Datadog Agent installed on your Windows machine includes a local desktop/web GUI called **Datadog Agent Manager**.

1. **Launch it via PowerShell helper**:
   ```powershell
   .\datadog\setup\launch_datadog_gui.ps1
   ```
   *Or launch it via the Start Menu:* Search for **"Datadog Agent Manager"**.
   *Or launch directly via command:*
   ```powershell
   & "C:\Program Files\Datadog\Datadog Agent\bin\agent\ddtray.exe" --launch-gui
   ```

2. **What you will see in this window**:
   - **Agent Status**: Shows the agent state, uptime, version, and running collectors.
   - **Checks -> postgres**: Shows whether the PostgreSQL check is actively running, execution duration (ms), metrics emitted count, and any SQL errors or warnings.
   - **Settings / Configuration Editor**: Allows you to view and edit `conf.yaml` directly without dealing with file permission prompts.
   - **Logs**: Displays real-time agent and check execution logs.

---

### Option 2: Live Terminal Check Window (Instant CLI Output)

To see the exact raw stream of metrics, tags, gauges, and rates that Datadog extracts from PostgreSQL:

1. Open **PowerShell as Administrator** (required to read Datadog's auth token in `C:\ProgramData\Datadog`).
2. Run:
   ```powershell
   & "C:\Program Files\Datadog\Datadog Agent\bin\agent.exe" check postgres
   ```
3. **What you will see**:
   - Every single metric emitted with its type, value, and tags:
     ```text
     === Check: postgres ===
       - postgresql.connections: 12 [tags: db:postgres, cluster:pg-cluster, role:primary]
       - postgresql.max_connections: 100 [tags: db:postgres]
       - postgresql.percent_usage_connections: 0.12 [tags: db:postgres]
       - postgresql.commits: 1450 [tags: db:postgres]
       - postgresql.replication_delay: 0 [tags: db:postgres, role:primary]
       - postgresql.buffer_hit: 0.998 [tags: db:postgres]
     ```
   - This provides an immediate, 1:1 comparison against the JSON payload output by our Site24x7 plugin script.

---

### Option 3: Datadog Cloud Web App (Dashboards & Database Monitoring)

If your Datadog Agent is connected to your Datadog account via an API key:

1. Log into [Datadog Web Console](https://app.datadoghq.com/) (or your regional URL, e.g., `https://us5.datadoghq.com/` or `https://app.datadoghq.eu/`).
2. **Navigate to the PostgreSQL Dashboard**:
   - Click **Dashboards** in the left sidebar.
   - Search for **"PostgreSQL - Overview"** or **"PostgreSQL - Metrics"**.
   - You will see graphs for:
     - **Current Activity**: Active Connections vs Max Connections, Commits/Rollbacks per sec.
     - **Database Resource Utilization**: Cache Hit Ratio, Disk Blocks Read vs Buffer Hits.
     - **Replication**: Replication Lag (seconds & bytes) for standby nodes.
     - **Locks & Deadlocks**: Exclusive locks and deadlocks count.
3. **Navigate to Database Monitoring (DBM)**:
   - Click **Database Monitoring -> Databases**.
   - You will see:
     - Real-time active queries and waiting queries.
     - Normalized query execution times (`pg_stat_statements`).
     - Query explain plans and CPU/wait-time hotspots.

---

## Quick Setup Steps (Connect Datadog to Your PostgreSQL)

To enable Datadog to pull metrics from your local PostgreSQL or Patroni cluster:

### Step 1: Provision the `datadog` User in PostgreSQL
Run the provided SQL script against your PostgreSQL instance using `psql`:
```powershell
psql -h 127.0.0.1 -p 5432 -U postgres -f .\datadog\setup\postgres_datadog_setup.sql
```
*(If running Patroni, run this on port 5441 or your primary port).*

### Step 2: Deploy `conf.yaml` into Datadog Agent
Run the deployment script in an **Administrator PowerShell**:
```powershell
powershell -ExecutionPolicy Bypass -File .\datadog\setup\install_postgres_conf.ps1
```
This copies `datadog\setup\conf.yaml` to `C:\ProgramData\Datadog\conf.d\postgres.d\conf.yaml` and restarts the Datadog service.

### Step 3: Verify the Check
Run the check verification:
```powershell
& "C:\Program Files\Datadog\Datadog Agent\bin\agent.exe" check postgres
```

---

## Architectural Comparison: Datadog vs. Site24x7 Cluster Plugin

| Feature | Datadog PostgreSQL Integration | Our Site24x7 Cluster Plugin | Improvement for v5 |
| :--- | :--- | :--- | :--- |
| **Connection Pooling** | Custom `LRUConnectionPoolManager` (`connection_pool.py`) maintaining persistent open handles per database. | Dynamic connection per collection turn with explicit `close()`. | Adopt keep-alive connection reuse or fast connect timeouts (3s) to prevent blocking during network partitions. |
| **Active Connections** | Reports both raw active connections (`postgresql.connections`), max (`postgresql.max_connections`), and percentage usage (`postgresql.percent_usage_connections`). | Reports `Active Connections` (`sum(numbackends)`) and `Connection Usage Percent`. | Maintain 100% parity with Datadog's calculation: `(sum(numbackends) / max_connections) * 100`. |
| **Active Queries vs Connections** | Separates connection count from queries actively executing (`postgresql.active_queries` where `state = 'active'`). | Historically grouped under connections. | Distinguish `Active Connections` (allocated client sockets) from `Active Queries` (threads currently running SQL). |
| **Replication Lag Tracking** | Measures both **lag in seconds** (`wal_replay_lag`) and **lag in bytes** (`replay_lsn_delay`), plus slot lag. | Measures lag in bytes (`pg_wal_lsn_diff`) and seconds (`extract(epoch from replay_lag)`). | Excellent parity; we also support Patroni DCS replication lag. |
| **Failover / Cluster Role** | Individual agent runs per instance; tags metrics with `role: primary` or `role: replica`. No cross-node cluster awareness. | **Full cluster awareness**: queries cluster topology via Patroni REST / repmgr / native, elects leader, aggregates all nodes in one plugin monitor. | **Our plugin is superior for clusters!** Datadog requires an agent per node; our plugin monitors the entire cluster topology holistically from a single seed. |
| **Transaction & Idle Ages** | Collects `postgresql.activity.xact_start_age` and backend xmin age to catch long-running transactions. | Collects `Idle Transactions`, `Longest Transaction Duration`, `idle_in_txn_time`. | Add transaction age thresholds to flag uncommitted transactions blocking vacuum. |
| **Deadlock & Lock Telemetry** | Collects deadlocks from `pg_stat_database.deadlocks` and lock modes from `pg_locks`. | Collects `Deadlocks` and `Conflicts`. | Include lock wait counts in cluster summaries. |
