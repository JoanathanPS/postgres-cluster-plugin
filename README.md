# Site24x7 PostgreSQL Cluster Plugin

A single Site24x7 plugin monitor for a whole PostgreSQL cluster: primary and standbys, health, replication, and every standalone `postgres` parameter per node.

The plugin itself is in [`postgres_cluster/`](postgres_cluster/). Start with its [README](postgres_cluster/README.md) for tabs, metrics, health rules, installation, thresholds, tested clusters and limitations.

## Repository layout

| Path | What it is |
| :--- | :--- |
| `postgres_cluster/` | The Site24x7 PostgreSQL cluster monitoring plugin (engine, config, installer, prerequisites). |
| `docs/` | Architecture guides, specifications, and PR draft (`docs/PR_DESCRIPTION.md`). |
| `docs/audit/` | Audit reports, gap analyses, fix prompts, and structure diffs. |
| `docs/images/` | Dashboard screenshots and architecture diagrams (`ss1.png`, `ss2.png`). |
| `scripts/` | Helper scripts for deployment (`deploy-dev.ps1`), failover tests, and validation (`check-layout.ps1`). |
| `tests/` | Complete test suites: unit tests (`test_summary.py`, `test_contract.py`), harness (`tests/harness/`), and validation tester (`tests/tester/`). |
| `environments/` | Multi-node test clusters & testbeds: Patroni (`environments/patroni/`), Streaming Replication (`environments/streaming/`), Multi-master, and community testbeds (`environments/testbeds/`). |
| `reference/` | Parity references: upstream Site24x7 postgres plugin (`reference/postgres/`) and Datadog (`reference/datadog/`). |
| `evidence/` | Collected test evidence, DOM inspection dumps, and agent payload outputs. |
| `research/` | Deep-dive research notes, metric catalogues, and failure matrices. |

## Branches

| Branch | Purpose |
| :--- | :--- |
| `main` | The finished production plugin (Site24x7 official layout). |
| `v5` | Full development repository with environments, test harnesses, and research. |
| `upstream-layout` | Working branch for the upstream layout. |
| `v4` | Work in progress: finding all nodes from one address, and more cluster types. |
| `v1` | The previous implementation (PR #442), kept unmodified for comparison. |
| tag `old-main` | The previous state of `main`, before it was replaced. |

## Quick checks

```powershell
# Run the full test suite, including the Site24x7 payload-contract checks
python -m pytest tests -q

# Run layout compliance check
powershell scripts\check-layout.ps1
```
