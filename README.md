# Task 2 – PostgreSQL Cluster + Site24x7 PostgreSQL Plugin

A 2-node PostgreSQL 16 **streaming-replication cluster** (primary + hot standby) running in
Docker Desktop. It is monitored by the **official, unmodified** Site24x7 `postgres` plugin
([site24x7/plugins/postgres](https://github.com/site24x7/plugins/tree/master/postgres)),
with a test container that runs the plugin against both nodes and validates its output.

```
                 Docker Desktop (WSL2)                          Windows host
 ┌──────────────────────────────────────────────────────┐
 │  pg-primary  (read/write)  ── WAL stream ──►  pg-replica (hot standby, read-only)
 │   5432 ◄── slot replica1_slot ─────────────────┘   5432 │
 │      ▲                                              ▲   │
 │      └──── plugin-test: python postgres.py ─────────┘   │   (docker compose run)
 └──────┼──────────────────────────────────────────────┼───┘
   127.0.0.1:5432                                 127.0.0.1:5433  ◄── Site24x7 Windows agent
                                                                      postgres.cfg: [pg_primary] [pg_replica]
```

| Item | Value |
|---|---|
| Plugin source | `postgres/postgres.py`, copied unmodified from site24x7/plugins commit `3c88f92` (23 Oct 2026), SHA-256 `e9f6d5ba…c2d0` |
| Plugin dependencies | Python 3 + `psycopg2-binary` (from the plugin README) |
| Monitoring account | `site24x7`: LOGIN + `pg_read_all_stats` only, read-only by default, 5-connection limit |
| One monitor per node | Each `[section]` in `postgres.cfg` becomes a separate Site24x7 plugin monitor |

---

## 1. Files

| Path | Purpose |
|---|---|
| `docker-compose.yml` | Primary, replica, healthchecks, volumes, and the `plugin-test` service (profile `test`) |
| `.env.example` | Template for credentials and ports → copy to `.env` (git-ignored) |
| `initdb/primary/01-init-cluster.sh` | First start only: replication role + slot, monitoring role, `pg_hba` replication rule |
| `initdb/primary/02-demo-appdb.sql` | First start only: small `appdb` database so table/index metrics have data |
| `replica/replica-entrypoint.sh` | Clones the primary with `pg_basebackup -R -S`, then starts the official entrypoint |
| `postgres/postgres.py` | Official Site24x7 plugin (unchanged) |
| `postgres/postgres.cfg.example` | Plugin config with one section per node → copy to `postgres.cfg` (git-ignored) |
| `tester/Dockerfile`, `tester/requirements.txt` | Minimal Python 3.12 + psycopg2-binary runner (a stand-in for the Linux agent's Python) |
| `tester/test_plugin.py` | Runs the plugin per node, validates the JSON against Site24x7 rules, checks replication |
| `.gitignore`, `.gitattributes` | Keep secrets out of git; keep `*.sh` as LF line endings on Windows |

`ScheduledTask/` (Task 1) is not touched.

---

## 2. Prerequisites (Windows)

- Docker Desktop running with **Linux containers** (WSL 2 backend).
- Ports 5432 and 5433 free on the host. If you have a local PostgreSQL, change
  `PRIMARY_HOST_PORT` / `REPLICA_HOST_PORT` in `.env`.
- Optional, for testing from Windows or for the Windows agent: Python 3 from python.org,
  installed **for all users** with **Add to PATH** ticked.

---

## 3. Setup and start (PowerShell)

```powershell
cd "D:\College\Year 3\Internship\Zoho\Task 2 - PostgreSQL Cluster Plugin"

# 1. Credentials (edit the three CHANGE_ME passwords; avoid " ' $ # and spaces)
Copy-Item .env.example .env
notepad .env

# 2. Validate the compose file (prints nothing on success)
docker compose config --quiet

# 3. Start the cluster and wait until both nodes are healthy
docker compose up -d --wait
docker compose ps
```

Expected: `pg-primary` and `pg-replica` are both `Up … (healthy)`. The first start takes
about 10–20 s (primary initdb → init scripts → replica base backup).

---

## 4. Verify the cluster

```powershell
# Primary sees one streaming replica
docker compose exec pg-primary psql -U postgres -c "SELECT client_addr, state, sync_state, replay_lag FROM pg_stat_replication;"

# Replica is in recovery (standby) and streaming from the slot
docker compose exec pg-replica psql -U postgres -c "SELECT pg_is_in_recovery(), status, slot_name FROM pg_stat_wal_receiver;"

# Write on the primary, read it back on the replica
docker compose exec pg-primary psql -U postgres -d appdb -c "INSERT INTO orders(customer, amount) VALUES ('replication_check', 1.23);"
docker compose exec pg-replica psql -U postgres -d appdb -c "SELECT * FROM orders WHERE customer = 'replication_check';"

# Writes on the replica are rejected
docker compose exec pg-replica psql -U postgres -d appdb -c "INSERT INTO orders(customer, amount) VALUES ('x', 1);"
#   ERROR:  cannot execute INSERT in a read-only transaction
```

(If you changed `POSTGRES_USER` in `.env`, use that name instead of `postgres`.)

---

## 5. Test the plugin

### 5a. In Docker (no Python needed on Windows)

```powershell
docker compose run --rm --build plugin-test
```

For each node this runs `python postgres.py --host … --port … --username site24x7 --password … --db appdb`,
the way the plugin README documents (and the 50 s default agent timeout applies). It then checks:

- exit code, valid JSON, `plugin_version` (whole number), `heartbeat_required`, no `status: 0`
- all metrics documented in the plugin README for this PostgreSQL version are present and numeric
- Site24x7 limits: ≤ 200 metrics, ≤ 10 tables, ≤ 15 columns and ≤ 25 rows per table, a `name` key in every row
- `units` and `s247config.childdiscovery` are consistent
- a wrong password yields `status: 0` plus an error `msg` (how Site24x7 shows the monitor as down)
- cluster role: exactly one primary; replica WAL receiver `streaming`; replay lag in bytes

The last line must read `RESULT: 0 failure(s), …`. The exit code is 0 on success.
The full JSON for each node is saved in `test-output\pg_primary.json` and `test-output\pg_replica.json`.

### 5b. From Windows itself (the same path the Windows agent uses: `localhost:5432/5433`)

```powershell
py -m pip install psycopg2-binary
$env:MONITOR_PASSWORD = "<MONITOR_PASSWORD from .env>"
py tester\test_plugin.py --plugin-dir postgres --node pg_primary=localhost:5432 --node pg_replica=localhost:5433

# or just the raw plugin output:
py postgres\postgres.py --host localhost --port 5432 --username site24x7 --password $env:MONITOR_PASSWORD --db appdb
```

---

## 6. PostgreSQL Cluster Plugin (`postgres_cluster`) & Agent Setup

The `postgres_cluster` plugin monitors a high-availability PostgreSQL cluster (Patroni + etcd + HAProxy or standard streaming replication), detecting roles, primary timelines, replication backlog, replication slot health, and collecting database performance metrics against the active primary node.

### 6.1 Root Cause Analysis: Windows Agent Pipe Deadlock & The Fix

#### The Bug in Native Python Plugins under WinAgent
When executing native Python plugins (`.py`), the Site24x7 Windows Agent (`Site24x7PluginAgent.exe`) starts the child process via `ProcessStartInfo` with redirected standard streams and calls `process.WaitForExit(timeout)`. It only begins draining `process.StandardOutput.ReadToEnd()` **after** the process has exited.

In Windows, anonymous pipes have a fixed 4096-byte (4 KB) kernel buffer. When the PostgreSQL cluster plugin finishes execution and flushes its rich ~9 KB JSON payload (including cluster metrics, 4 child discovery tables, tabs, and units), the Python process blocks in `WriteFile` waiting for the buffer to be drained. Meanwhile, the agent is blocked in `WaitForExit` waiting for Python to terminate. This creates a classic **bidirectional deadlock**. Exactly at 160 seconds, the agent times out and kills the Python process, writing:
```text
PythonScript RunPlugin timeout for ...\postgres_cluster.py
{"msg":"Timeout while executing Plugin postgres_cluster.py","type":"postgres_cluster","availability":"0"}
```

#### The Architecture Fix: PowerShell Plugin Wrapper
PowerShell plugins (`.ps1`) in Site24x7 do not use anonymous pipes for output capture. Instead, the agent executes them with shell file redirection:
```cmd
cmd.exe /c powershell.exe -File "...\postgres_cluster.ps1" ... > "_output.txt" 2> "_error.txt"
```
Because output is redirected directly to a disk file, there is no kernel pipe buffer limit. The process writes the entire ~9 KB JSON payload in milliseconds, exits immediately, and the agent reads the output cleanly from `_output.txt`.

To implement this fix:
1. **`postgres_cluster.ps1`**: Deployed as the single registered plugin entry in `C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster\`. It receives the configuration parameters from the agent, detects the 64-bit Python executable, and runs the collector.
2. **`postgres_cluster_impl.py`**: The Python collector logic placed in the same folder. Because its base name does not match the folder name `postgres_cluster`, the agent ignores it during plugin discovery and registers only the `.ps1` entry.
3. **`postgres_cluster.cfg`**: Configured with unencrypted credentials. After the first successful execution, the agent automatically encrypts the fields with AES (`encrypted.nodes=...`, `encrypted.password=...`).

### 6.2 Speed Optimizations: Parallel Probing (< 1s execution)
1. **Parallel ThreadPoolExecutor**: Nodes are probed concurrently using `concurrent.futures.ThreadPoolExecutor(max_workers=8)`. All 3 nodes are checked simultaneously in ~50 ms rather than sequentially in ~6 s.
2. **IPv4 Loopback Normalization**: Connecting to `localhost` on Windows causes `getaddrinfo` to query IPv6 `::1` first, incurring a 2000 ms timeout per node before falling back to IPv4 `127.0.0.1`. Normalizing loopback addresses to `127.0.0.1` reduced per-node connection latency from **2055 ms to 23 ms** (a 90x speedup).
3. **Fast Dead-Host Detection**: `CONNECT_TIMEOUT` is set to 2 seconds, and fallback database queries are bypassed on network/socket errors, ensuring a cluster with dead nodes still finishes in under **3.5 seconds**.

---

## 7. Deployment and Verification Walkthrough

### 7.1 Deploying on the Windows Real Agent
1. **Run PowerShell as Administrator**:
   ```powershell
   cd "D:\College\Year 3\Internship\Zoho\Task 2 - PostgreSQL Cluster Plugin"
   .\postgres_cluster\Site24x7PostgresClusterPluginInstaller.ps1 -Nodes "127.0.0.1:5441,127.0.0.1:5442,127.0.0.1:5443" -Username "site24x7" -Password "site24x7" -NonInteractive
   ```
2. **Check Agent Registration Log** (discovery happens within 50 s):
   ```powershell
   Get-Content -Path "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\logs\Details\PluginRegisterLog.log" -Tail 25
   ```
   *Expected output*: `DataCollection RegisterPlugin output for 1 -- True` and `Successfully written to ...\PluginRegister\postgres_cluster.txt`.
3. **Check Periodic Data Collection** (runs every 5 minutes):
   ```powershell
   Get-Content -Path "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\logs\Details\PluginLog.log" -Tail 25
   ```
   *Expected output*:
   ```text
   Run plugin in powershell version less than 5 ...\postgres_cluster.ps1
   Powershell :: output from file instanceName :: postgres_cluster ...
   Util writeToFile Successfully written to ...\PluginData\Plugin_...txt
   ```

### 7.2 Deploying on the Linux Agent (WSL / Dedicated VM)
1. In Linux/WSL, execute the bash installer:
   ```bash
   cd postgres_cluster/
   chmod +x Site24x7PostgresClusterPluginInstaller.sh
   sudo ./Site24x7PostgresClusterPluginInstaller.sh
   ```
2. The script deploys `postgres_cluster.py` and `postgres_cluster.cfg` to `/opt/site24x7/monagent/plugins/postgres_cluster/` and installs `psycopg2-binary` into the agent's Python environment.
3. Monitor logs in `/opt/site24x7/monagent/logs/details/plugins.txt`.

### 7.3 Windows Agent Execution, Pipe Deadlock, and the `redirect_output` Fix
#### Root Cause of the Windows Timeout Issue
When the Site24x7 Windows Agent executes plugins on Windows (`Site24x7PluginAgent.exe`), it creates a child process with redirected standard output and calls `Process.WaitForExit(timeout)` **before** reading stdout via `StandardOutput.ReadToEnd()`. 

On Windows, anonymous pipes have a fixed 4096-byte (4 KB) kernel buffer. Because the PostgreSQL cluster plugin returns a rich JSON payload (~6 KB to ~11 KB) including cluster metrics, custom tabs, units, and child table discoveries (`Cluster_Nodes`, `Replication_Standbys`, `Stats_per_DB`, `Tranasctions_and_Session_per_Database`), the process blocks when attempting to flush stdout past 4 KB. Concurrently, the agent waits indefinitely for the process to exit, resulting in a classic deadlock. After 160 s during registration (or 50 s during periodic data collection), the agent times out and terminates the process, causing the error:
`"No attributes to monitor. Plugin output is empty or not in Json format \n"`.

#### The Native Agent Solution (`redirect_output=1`)
Site24x7 agent's internal configuration parser checks for `redirect_output=1` inside the `[global_configurations]` section of `postgres_cluster.cfg`. When enabled, the agent configures the process runner to redirect stdout directly to a temporary file (`cmd.exe /c ... > "_output.txt" 2> "_error.txt"`), completely bypassing Windows anonymous pipe buffer limits.
```ini
[global_configurations]
use_agent_python=0
redirect_output=1

[pg_cluster]
nodes="127.0.0.1:5441,127.0.0.1:5442,127.0.0.1:5443"
username="site24x7"
password="CHANGE_ME"
db="postgres"
patroni_port="8008"
```
Under this configuration, native Python execution takes **under 1 second** (verified in `PluginRegisterLog.log` and `PluginLog.log`), reporting full availability (`availability: 1`) and writing all telemetry without pipe deadlocks.

> **Linux vs Windows Compatibility Note**: On Linux hosts, the kernel anonymous pipe buffer is 64 KB (16x larger than Windows), so payloads under 64 KB do not deadlock. Setting `redirect_output=1` under `[global_configurations]` is supported by newer agents. In environments where `redirect_output` behavior in the Linux `monagent` is unverified, standard output redirection or native pipes remain fully operational for payloads under 64 KB.

### 7.4 The `plugin_version` Rule and Schema Updates
Site24x7's cloud backend permanently registers and binds a plugin monitor's attribute schema during its **initial registration**:
1. **Schema Immutability**: If a plugin is registered with `plugin_version: 1`, the Site24x7 web console locks in the metrics reported in that first payload. Any new metrics, tabs, or child tables added later will **not** appear on existing monitors unless the version is incremented.
2. **Version Bump Rule**: Whenever new metrics, tabs, or child tables are added to `postgres_cluster.py`, always increment `PLUGIN_VERSION` (e.g. from `2` to `3`). When the agent detects an incremented version, it submits a fresh registration payload and the cloud updates the metric schema.
3. **Removing Stale Monitors in the Console**:
   If an older test monitor exists (e.g. from early debugging when only `Nodes Up` was monitored), remove it to avoid confusion:
   - Navigate to **Plugins** $\to$ **Plugin Integrations**.
   - Hover over or click on the stale monitor (e.g. `postgres_cluster-cluster-<Hostname>`).
   - Click the hamburger/kebab menu icon $(\vdots)$ and select **Delete**.
   - The agent will register a clean monitor with full tabs on its next check cycle (~50s).

### 7.5 Comparative Gap Analysis against PR #442
A detailed comparison against upstream [PR #442](https://github.com/site24x7/plugins/pull/442) is documented in [GAP_ANALYSIS.md](file:///D:/College/Year%203/Internship/Zoho/Task%202%20-%20PostgreSQL%20Cluster%20Plugin%20-%20v2/GAP_ANALYSIS.md). Key enhancements incorporated from PR #442 into this plugin include:
1. **Replication Slots Segregation**: `Physical Slots` and `Logical Slots` tracked alongside total, active, and inactive counts.
2. **Write-Ahead Log (WAL) Observability**: `Current WAL LSN`, `WAL Insert LSN`, `WAL Flush LSN`, and file retention counts (`WAL Files Count`, `WAL Total Size`).
3. **Archiving Reliability**: `Archive Status Success`, `Archive Status Failed`, `Last Archived WAL File`, and `Archive Ready Files Count`.
4. **Recovery Conflicts**: Granular standby conflict breakdown (`Conflicts Tablespace`, `Conflicts Lock`, `Conflicts Snapshot`, `Conflicts Buffer Pin`, `Conflicts Deadlock`, and `Recovery Conflicts Total`).
5. **Connection Saturation & Transaction Age**: `Available Connections`, `Connection Utilization Percent`, and `Oldest Running Transaction Age`.
6. **Cross-Version SQL Safety**: While PR #442 hardcoded `pg_stat_checkpointer` (crashing on PostgreSQL < 17), our plugin dynamically inspects `server_version` and adapts between `pg_stat_checkpointer` (PG 17+) and `pg_stat_bgwriter` (PG < 17).

### 7.6 Verifying the Live Agent in Site24x7 Web Console
1. **Navigation**: In the Site24x7 Web Console, go to **Plugins** $\to$ **Plugin Integrations**.
2. **Monitors Displayed**:
   - `postgres_cluster-pg_cluster-<Hostname>`: Active production monitor.
   - `postgres_cluster_dev-pg_cluster_dev-<Hostname>`: Dev instance (deployed via `deploy-dev.ps1`).
3. **Check the 6 Dashboard Tabs**:
   - **Tab 1: Cluster (Order 1)**:
     - `Nodes Total`: 3, `Nodes Up`: 3
     - `Primary Count`: 1, `Primary Timeline`: Current timeline (e.g. 8 or 9)
     - `No Primary Flag`: 0, `Split Brain Flag`: 0
     - `Max Replay Backlog`: 0 bytes
     - `Replication Slots Total`: 2, `Active`: 2, `Inactive`: 0, `Physical`: 2, `Logical`: 0
     - `Max Slot Lag Bytes`: 0 bytes
   - **Tab 2: DB and IO stats**: Per-DB table, rows inserted/updated/deleted/fetched/returned, block reads and hits.
   - **Tab 3: BG Writer**: Checkpoints timed & requested, checkpoint write & sync time, buffers checkpoint/clean/alloc.
   - **Tab 4: Transactions and Sessions**: Commits, rollbacks, conflicts, active sessions, abandoned/fatal/killed counts.
   - **Tab 5: Write Ahead Log**: Current/Insert/Flush WAL LSNs (MB), WAL file counts, archive success/failure counts.
   - **Tab 6: Recovery Conflicts**: Tablespace, lock, snapshot, buffer pin, deadlock conflicts, and oldest transaction age.
4. **Verify Child Tables**:
   - **`Cluster_Nodes`**: Shows all cluster nodes (`127.0.0.1:5441`, `5442`, `5443`), roles (`primary`/`standby`), health `status` (`up`/`down`), timeline, and response times.
   - **`Replication_Standbys`**: Lists connected streaming standbys with byte lags and sync states.
   - **`Stats_per_DB`** and **`Tranasctions_and_Session_per_Database`**: Per-database breakdown on the active primary.

### 7.7 Swapping the Dev Version to Production Agent Folder
To promote the verified v2 plugin to the production agent folder `postgres_cluster`:
```powershell
# Stop services before copying
Stop-Service -Name "Site24x7 Plugin Agent" -Force -ErrorAction SilentlyContinue

# Target production directory
$prodDir = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster"

# Copy python script and configuration
Copy-Item "D:\College\Year 3\Internship\Zoho\Task 2 - PostgreSQL Cluster Plugin - v2\postgres_cluster\postgres_cluster.py" `
          -Destination (Join-Path $prodDir "postgres_cluster.py") -Force

Copy-Item "D:\College\Year 3\Internship\Zoho\Task 2 - PostgreSQL Cluster Plugin - v2\postgres_cluster\postgres_cluster.cfg" `
          -Destination (Join-Path $prodDir "postgres_cluster.cfg") -Force

# Start services
Start-Service -Name "Site24x7 Plugin Agent"
```

---

## 8. Automated Testing Suite

All tests can be executed locally on Windows:
```powershell
# 1. Core Plugin Schema and Error Resilience Suite (4 tests)
py tester/test_cluster_plugin.py

# 2. Automated Failover Test (stops leader, asserts timeline advance & new primary, restarts node)
.\failover-test.ps1

# 3. Replication Lag Demonstration (simulates stall, generates 1500 tx via pgbench, verifies backlog > 0 then catchup to 0)
py tester/lag_demo.py
```

---

## 9. How monitoring works across the cluster

- **One monitor per node.** `postgres.cfg` has `[pg_primary]` and `[pg_replica]`, and the agent creates a separate
  monitor for each. Every metric (connections, commits, locks, checkpoints, cache hit ratio, per-DB tables) is
  therefore per node.
- **Works on the standby.** All of the plugin's queries are read-only, so they run on a hot standby as well (tested).
- **What the official plugin does NOT report:** node role (primary/standby), replication state, or replication lag.
  `tester/test_plugin.py` checks these with the same least-privilege account (`pg_stat_replication`,
  `pg_stat_wal_receiver`). To get them into Site24x7, the official
  [`postgres_custom_query`](https://github.com/site24x7/plugins/tree/master/postgres_custom_query) plugin could run e.g.
  `SELECT pg_is_in_recovery()::int AS is_standby` – not implemented here (ask your mentor).
- **Why `db=appdb`.** The table/index metrics (Index Scans, Heap Blocks Read/Hit, Cache Hit Ratio, …) only cover the
  database the plugin connects to. With `db=postgres` (no user tables) the plugin reports them as the string `"None"`.
  Cluster-wide metrics are the same whichever database is used.
- **Why `pg_read_all_stats`.** Without it, `pg_stat_activity` hides other sessions' state, which makes the
  Active Queries / Idle In Transaction counts wrong, and `pg_stat_replication` hides replication state (both verified).

---

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `required variable … is missing a value` | `.env` missing or incomplete → `Copy-Item .env.example .env` and fill it in |
| `Bind for 127.0.0.1:5432 failed: port is already allocated` | Local PostgreSQL uses 5432 → change `PRIMARY_HOST_PORT` in `.env` (and `port=` in `postgres.cfg`) |
| Roles `site24x7`/`replicator` don't exist, replica fails with `no pg_hba.conf entry` | Init scripts only run on an **empty** volume. If the first start failed, the volume is no longer empty, so init is skipped. Fix: `docker compose down -v` then `docker compose up -d --wait` (**deletes this cluster's data**) |
| `bash\r: No such file` / `$'\r': command not found` | Scripts got CRLF endings (git autocrlf). `.gitattributes` prevents this; re-checkout, or convert to LF in your editor |
| `pg-replica` keeps restarting | `docker compose logs pg-replica`. Usually a wrong `REPLICATION_PASSWORD` (changed after first start) → `down -v` and start again |
| Plugin: `password authentication failed for user "site24x7"` | Password in `postgres.cfg`/`MONITOR_PASSWORD` ≠ the one used at first start (`.env` is read only when the volume is created) |
| Plugin: `psycopg2 Module Not Installed` | Install `psycopg2-binary` for the **same** Python the agent runs (system-wide for the Windows agent) |
| Metrics show `"None"` | `db=` points at a database without user tables → use `appdb` (or your application DB) |
| Test container: `could not save full output` | Folder permissions on `test-output`; delete the folder and rerun |
| Logs | `docker compose logs -f pg-primary pg-replica` |

The `FATAL: password authentication failed for user "site24x7"` line in the primary's log after a test run is
expected: it comes from the negative (wrong-password) test.

---

## 9. Stop and clean up

```powershell
docker compose stop                          # stop, keep data
docker compose --profile test down           # remove containers + network, keep data volumes
docker compose --profile test down -v        # ALSO delete this project's two data volumes (all cluster data)
docker image rm pg-cluster-site24x7-plugin-test   # remove the test image
Remove-Item -Recurse test-output             # remove saved plugin JSON
```

`down -v` only removes the volumes `pg-cluster-site24x7_primary-data` and `pg-cluster-site24x7_replica-data`.

---

## 10. Security notes

- No secrets in tracked files: `.env` and `postgres/postgres.cfg` are git-ignored, and only `*.example` files are committed.
- Ports are published on `127.0.0.1` only, not on your LAN.
- Replication uses a dedicated `REPLICATION` role over SCRAM-SHA-256. `pg_basebackup -R` stores that role's password in
  the replica volume's `postgresql.auto.conf` (normal for this setup).
- The monitoring role cannot write or replicate. This was tested: `CREATE TABLE` → read-only / `permission denied for schema public`,
  `SELECT` on app tables → `permission denied`, and replication connections are refused.
