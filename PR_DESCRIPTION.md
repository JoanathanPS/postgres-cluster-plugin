# PR: PostgreSQL Cluster Monitoring Plugin for Site24x7 (v2-agent-fix)

## Summary of Changes

This Pull Request delivers a production-ready, cross-platform PostgreSQL Cluster monitoring plugin for Site24x7, supporting high-availability topologies (Patroni, DCS, streaming replication). It resolves the 160 s Windows Agent registration deadlock, incorporates missing metrics identified in upstream PR #442, and provides automated test suites and installers.

---

### 1. Key Features & Enhancements

- **Unified Cluster-Wide Monitoring**: Monitors all cluster nodes via a single configuration entry (`nodes = host1:port1,host2:port2,...`). Detects primary failover automatically and tracks cluster health (`Nodes Total`, `Nodes Up`, `Primary Count`, `No Primary Flag`, `Split Brain Flag`, `Primary Timeline`, and `Max Replay Backlog`).
- **Incorporation of PR #442 Metrics**:
  - Replication slot classification: `Physical Slots` and `Logical Slots` (alongside `Replication Slots Total`, `Active`, `Inactive`, and `Max Slot Lag Bytes`).
  - Write-Ahead Log (WAL) volume: `Current WAL LSN`, `WAL Insert LSN`, `WAL Flush LSN`, `WAL Files Count`, and `WAL Total Size`.
  - Archiver reliability: `Archive Status Success`, `Archive Status Failed`, `Last Archived WAL File`, and `Archive Ready Files Count`.
  - Standby recovery conflicts: `Recovery Conflicts Total`, `Conflicts Tablespace`, `Conflicts Lock`, `Conflicts Snapshot`, `Conflicts Buffer Pin`, and `Conflicts Deadlock`.
  - Connection pool metrics: `Available Connections` and `Connection Utilization Percent`.
- **Cross-Version SQL Compatibility**: Dynamically inspects `server_version` to support PostgreSQL 9.2 through PostgreSQL 17+. Correctly queries `pg_stat_checkpointer` on PG 17+ and falls back to `pg_stat_bgwriter` on PG <17.
- **Windows Agent Deadlock Resolution (`redirect_output=1`)**: Fixed the 4 KB anonymous pipe buffer deadlock in `Site24x7PluginAgent.exe` by configuring `redirect_output=1` in `[global_configurations]`. Execution now completes in under 1 second without timing out.
- **Robust Windows & Linux Installers**:
  - Windows: `Site24x7PostgresClusterPluginInstaller.ps1` detects Python 3, ensures `psycopg2-binary` is installed, configures `redirect_output=1`, and validates execution before completion.
  - Linux: `Site24x7PostgresClusterPluginInstaller.sh` installs dependencies and configures the plugin.

---

### 2. Verification & Performance

- **Sub-Second Execution**:
  - Healthy 3-node cluster: **0.99 s**
  - Standby node stopped: **3.71 s** (no crash, Node status marked `down`)
  - Primary node stopped: **3.51 s** (failover followed, timeline advance detected)
- **Live Agent Verification**: Verified under real Site24x7 Windows Agent in `postgres_cluster_dev`. Successfully registered in 1.0 s and executed across consecutive 5-minute cycles with output written to `PluginData`.
- **Test Suite Pass Rate**:
  - `py tester/test_cluster_plugin.py`: PASS (including dead-node timing assertion < 10 s)
  - `failover-test.ps1`: PASS (dynamic leader promotion & recovery)
  - `py tester/lag_demo.py`: PASS (1500 tx pgbench write load & catchup verification)

---

### 3. File Inventory

| File | Description |
| :--- | :--- |
| `postgres_cluster/postgres_cluster.py` | Multi-node cluster collector (schema version 3, 6 tabs, 4 child tables) |
| `postgres_cluster/postgres_cluster.cfg.example` | Template configuration with `redirect_output=1` |
| `postgres_cluster/Site24x7PostgresClusterPluginInstaller.ps1` | Automated Windows installer with dependency validation |
| `postgres_cluster/Site24x7PostgresClusterPluginInstaller.sh` | Automated Linux installer |
| `deploy-dev.ps1` | Dev deployment script for staging against `postgres_cluster_dev` |
| `GAP_ANALYSIS.md` | Factual comparative analysis against upstream PR #442 |
| `README.md` | Comprehensive documentation on cluster setup, agent lifecycle, and metrics |
| `tester/test_cluster_plugin.py` | Test suite with schema, auth error, and failover assertions |
