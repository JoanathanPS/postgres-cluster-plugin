Fix negative replication replay backlog calculations and replace raw sanitized node identifiers with human-readable node names in the PostgreSQL Cluster monitoring plugin for production deployment in Site24x7.

Working directory: d:\College\Year 3\Internship\Zoho\Task 2 - PostgreSQL Cluster Plugin
Integrity mode: development

## Requirements

### R1. Fix Replication Replay Backlog Calculation
Resolve the negative replay backlog issue (e.g. reported as -9,709,784 bytes) in the cluster monitoring plugin. Fix the WAL position comparison logic to correctly account for timeline transitions and LSN differences so that replay backlog is never calculated as negative bytes, clamping any calculated lag to 0 bytes if a negative value would otherwise result.

### R2. Human-Readable Node Identifiers in Child Tables
Replace raw sanitized host-port strings (such as `D1270015441`) with readable node names in plugin child tables (including `Cluster_Nodes` and `Replication_Standbys`). Auto-discover member names via the Patroni REST API (e.g., `pg-node1`, `pg-node2`, `pg-node3`) or database hostnames, falling back to clean sanitized labels if unreachable, while preserving explicit `name=host:port` configuration if supplied.

### R3. Plugin Code and Deployment Synchronization
Apply and verify fixes in both the workspace repository plugin (`postgres_cluster/postgres_cluster.py`) and the deployed dev plugin (`C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster_dev\postgres_cluster_dev.py`).

## Acceptance Criteria

### Metric Calculation
- [ ] In the plugin JSON output, `Max Replay Backlog` is always non-negative (>= 0) under normal replication, lag, or timeline transitions.
- [ ] Each record in `Replication_Standbys` reports `replay_lag_bytes` >= 0, write_lag_bytes >= 0, and flush_lag_bytes >= 0.

### Node Identification
- [ ] `Cluster_Nodes` rows display readable node identifiers (such as Patroni member names `pg-node1`, `pg-node2`, `pg-node3`) instead of raw sanitized host-port strings like `D1270015441`.
- [ ] `Replication_Standbys` rows identify standbys using readable names rather than raw IP/port strings where available.

### Plugin Execution & Verification
- [ ] Executing `postgres_cluster/postgres_cluster.py` directly against the running local cluster (`127.0.0.1:5441`, `127.0.0.1:5442`, `127.0.0.1:5443` with Patroni REST ports `8001`, `8002`, `8003`) returns valid JSON with `"status": 1` and all required cluster metrics and child tables.
- [ ] Executing `C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster_dev\postgres_cluster_dev.py` returns identical valid JSON with `"status": 1` matching the updated logic.
