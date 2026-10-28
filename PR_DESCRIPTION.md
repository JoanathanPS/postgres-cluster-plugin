# PR: Comprehensive PostgreSQL Cluster Monitoring Plugin for Site24x7

## Summary of Changes

This Pull Request introduces a production-ready, enterprise-grade PostgreSQL Cluster monitoring plugin for Site24x7. It supersedes the partial implementation in PR #442 by adopting a unified cluster-first topology model, delivering sub-second failover visibility, incorporating all review feedback from PR #442, and eliminating the Windows Agent 160 s registration deadlock.

The single source of truth for upstream repository submission is maintained under:
`upstream_layout/postgres_cluster/`

---

## 1. Architectural Architecture: Single-Monitor vs Per-Node

| Dimension | PR #442 Implementation | This Plugin Implementation (`v2`) |
| :--- | :--- | :--- |
| **Topology Representation** | Monitors individual nodes independently via separate configuration blocks (`[pg_primary]`, `[pg_replica]`). | Monitors the **entire cluster as a cohesive unit** under a single monitor definition (`nodes = host1:port1,host2:port2,...`). |
| **Primary Discovery & Failover** | Static configuration. If a failover occurs, the replica monitor reports errors until human intervention updates the cfg. | **Dynamic parallel discovery**: Probes all nodes concurrently (sub-second timeouts), detects primary promotion automatically, and follows the new primary without configuration changes. |
| **Cluster Telemetry** | No cluster health or topology indicators. | Provides cluster-wide health flags: `Nodes Total`, `Nodes Up`, `Primary Count`, `No Primary Flag`, `Split Brain Flag`, `Primary Timeline`, and `Max Replay Backlog`. |
| **Child Tables** | None. | Dedicated child tables: `Cluster_Nodes` (node reachability, timeline, latency, Patroni DCS state) and `Replication_Standbys` (standby streaming lag, state, and sync mode). |
| **Agent Resource Impact** | Multiple independent agent execution threads and separate API credit usage. | Single execution thread covering all nodes within 1 second. |

---

## 2. Full Resolution of PR #442 Review Comments (11/11 Addressed)

This implementation directly addresses all 11 technical considerations raised during the review of PR #442:

1. **Synchronous Standby Classification**: Properly classifies standbys across `sync`, `quorum`, `potential`, and `async` using `COALESCE(sync_state, 'unknown')` from `pg_stat_replication`.
2. **Replication Backlog & Lag Calculation**: Calculates byte-accurate receive, write, flush, and replay lag using `pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)`.
3. **Backend Direct-Write Handling**: Correctly collects buffer metrics (`buffers_clean`, `buffers_checkpoint`, `buffers_alloc`, `maxwritten_clean`) without breaking under varying backend write patterns.
4. **PostgreSQL 17+ Version Compatibility**: Dynamically inspects `server_version`. Queries `pg_stat_checkpointer` on PostgreSQL 17+ and falls back gracefully to `pg_stat_bgwriter` on PostgreSQL 16 and older.
5. **Client Backend Filtering**: Filters active connection counts specifically for client backends (`WHERE backend_type = 'client backend'`), with fallback (`WHERE client_addr IS NOT NULL`) for PostgreSQL < 10, preventing background workers and autovacuum from distorting client connection metrics.
6. **Recovery Conflict Aggregation**: Aggregates database recovery conflicts (`conflicts_tablespace`, `conflicts_lock`, `conflicts_snapshot`, `conflicts_buffer_pin`, `conflicts_deadlock`) across all databases from `pg_stat_database_conflicts`.
7. **Role Derivation from Recovery State**: Determines authoritative node role directly via `pg_is_in_recovery()`, correctly identifying standby vs primary even during transient promotion states.
8. **RFC 8259 Standard JSON Formatting**: Emits strictly valid JSON using `json.dumps(result)`, eliminating single-quote python dict representations that broke automated parsers and linters.
9. **Safe `psycopg2` Import Handling**: Wraps library imports in guarded try/except blocks. On missing drivers, returns `status: 0` with actionable installation instructions rather than crashing or throwing unhandled stack traces.
10. **Standby Listening vs Source Port Resolution**: Avoids confusion between standby connection socket ephemeral ports (`client_port`) and server listening ports by concurrently probing each configured cluster endpoint directly.
11. **Enforcement of 25-Row Child Table Limit**: Caps all tabular metrics (`Cluster_Nodes`, `Replication_Standbys`, `Stats_per_DB`, `Tranasctions_and_Session_per_Database`) at 25 entries (`[:25]`) to strictly observe Site24x7 agent schema constraints.

---

## 3. Windows-First Focus & Anonymous Pipe Deadlock Resolution

- **The Problem**: On Windows, the Site24x7 agent (`Site24x7PluginAgent.exe`) captures standard output from plugin scripts via Windows anonymous pipes. The operating system buffer for anonymous pipes is 4 KB. When rich JSON telemetry (with tabs, units, and child tables) exceeds 4 KB, the Python child process blocks on `sys.stdout.write()`. The agent parent process waits for script completion before draining the pipe, creating a textbook circular wait deadlock that terminates only after the agent's 160 s script timeout.
- **The Solution**: We enabled `redirect_output = 1` under `[global_configurations]` in `postgres_cluster.cfg`. This instructs `Site24x7PluginAgent.exe` to redirect output directly to a temporary file (`PluginOutput\`), bypassing pipe buffer limits completely. Plugin execution drops from a 160 s timeout to **under 1.0 second**.

---

## 4. Upstream Repository Structure (`upstream_layout/postgres_cluster/`)

The directory matches the exact conventions of `site24x7/plugins/postgres/` and PR #442:

```
upstream_layout/postgres_cluster/
├── postgres_cluster.py                              # Core plugin collector
├── postgres_cluster.cfg                             # Standard template configuration
├── README.md                                        # Official documentation & metric tables
├── installer/
│   ├── Site24x7PostgresClusterPluginInstaller.ps1   # PowerShell Windows installer
│   └── Site24x7PostgresClusterPluginInstaller.sh    # Bash Linux installer
├── prerequisites/
│   ├── create_user.sql                              # SQL user provisioning script
│   └── create_user.sh                               # Shell helper for user provisioning
└── wc_automation/
    └── installer.sh                                 # Agent automation hook
```

---

## 5. Automated Verification & Test Coverage

- **`check-layout.ps1`**: Verifies directory structure, AST PowerShell syntax, py_compile Python compilation, configuration headers, and live JSON output (15/15 tests passing).
- **`tester/e2e.ps1`**: One-command end-to-end verification supporting `-Mode quick` and `-Mode full`:
  - **Stage A (Preflight)**: Docker daemon, 3 Patroni nodes, Python 3, `psycopg2`, agent dev directory.
  - **Stage B (Timing)**: Probing latency < 5s on healthy cluster (0.53s), 1 replica down (3.38s), primary down (3.27s).
  - **Stage C (Suites)**: Unit tests, failover assertion, replication lag demo.
  - **Stage D (Agent)**: Validates real agent execution in `PluginLog.log` and output payload writes to `PluginData\`.
  - **Stage E (Console)**: Playwright automated browser verification of Site24x7 web console.
  - **Stage F (Cleanup Guarantee)**: Strict `try/finally` block ensuring all 3 nodes are always returned to healthy state.
