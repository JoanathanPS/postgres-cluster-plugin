# Site24x7 PostgreSQL Cluster Plugin

A single Site24x7 plugin monitor for a whole PostgreSQL cluster: primary and standbys, health, replication, and every standalone `postgres` parameter per node.

The plugin itself is in [`upstream_layout/postgres_cluster/`](upstream_layout/postgres_cluster/). Start with its [README](upstream_layout/postgres_cluster/README.md) for tabs, metrics, health rules, installation, thresholds, tested clusters and limitations.

## Repository layout

| Path | What it is |
| :--- | :--- |
| `upstream_layout/postgres_cluster/` | The plugin, in the upstream `site24x7/plugins` folder layout. Edit this one. |
| `postgres_cluster/` | A mirror of the plugin file, kept identical by `check-layout.ps1`. |
| `postgres/` | The standalone `postgres.py` plugin used as the parity reference. |
| `tester/` | Unit tests, OG parity test, e2e script, console checker. |
| `patroni-cluster/`, `docker/`, `docker-compose.yml`, `replica/`, `initdb/` | Docker test clusters (Patroni, plain streaming). |
| `failover-test.ps1`, `lag-demo.sh`, `deploy-dev.ps1`, `check-layout.ps1` | Test and deploy helpers. |
| `STRUCTURE_DIFF.md` | Console structure of the standalone monitor compared with the cluster monitor. |
| `PR_DESCRIPTION.md` | Draft pull request description for `site24x7/plugins`. |
| `docs/archive/` | Older design notes, kept for history only. |

## Branches

| Branch | Purpose |
| :--- | :--- |
| `main` | The finished plugin (same content as `upstream-layout`). |
| `upstream-layout` | Working branch for the upstream layout. |
| `v4` | Work in progress: finding all nodes from one address, and more cluster types. |
| `v1` | The previous implementation (PR #442), kept unmodified for comparison. |
| tag `old-main` | The previous state of `main`, before it was replaced. |

## Quick checks

```powershell
.\check-layout.ps1
python tester\test_cluster_plugin.py
.\tester\e2e.ps1 -Mode quick -SkipConsole
```
