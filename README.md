# Site24x7 PostgreSQL Cluster Plugin

A single Site24x7 plugin monitor for a whole PostgreSQL cluster: primary and standbys, health, replication, and every standalone `postgres` parameter per node.

The plugin itself is in [`postgres_cluster/`](postgres_cluster/). Start with its [README](postgres_cluster/README.md) for tabs, metrics, health rules, installation, thresholds, tested clusters and limitations.

## Repository layout

| Path | What it is |
| :--- | :--- |
| `postgres_cluster/` | The Site24x7 PostgreSQL cluster monitoring plugin. |
| `postgres/` | The official Site24x7 standalone PostgreSQL plugin used for parity reference. |
| `demo/` | Self-contained Docker cluster showcases (e.g. Patroni network showcase). |
| `tester/` | Unit tests, OG parity test, e2e script, console checker. |
| `patroni-cluster/`, `testbeds/` | Docker test clusters (Patroni, repmgr, Citus, pg_auto_failover, Stolon, etc.). |
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
