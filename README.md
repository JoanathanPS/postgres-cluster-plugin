# Site24x7 PostgreSQL plugin, version 2

The replacement for the official Site24x7 `postgres` plugin. It monitors a PostgreSQL server and, when that server is part of a cluster, every node of the cluster from that one address.

Start here:
- **Plugin documentation** (install, configuration, metrics, health codes): [`postgres/README.md`](postgres/README.md)
- **Current state, test kit and open issues:** [`HANDOFF.md`](HANDOFF.md)

## Layout

| Path | What it is |
| :--- | :--- |
| `postgres/` | The plugin: `postgres.py`, `postgres.cfg`, `README.md`. This folder is what ships. |
| `tests/` | Unit tests. Run with `python -m pytest tests -q`. |
| `scripts/api_check.py` | Read-only check of every `postgres` monitor through the Site24x7 REST API. Needs the `S247_*` keys in `.env`. |
| `scripts/agent_payloads.sh` | Captures exactly what the local Site24x7 agent sends at its next poll. |
| `scripts/run_in_network.sh`, `scripts/runner/` | Run the plugin inside a test bed's Docker network. |
| `docker-compose.yml` | Streaming-replication test bed (primary and standby). Credentials come from `.env` (see `.env.example`). |
| `environments/` | Other test beds: `patroni/`, `streaming/` (init scripts), `docker/multimaster/` (logical), and `testbeds/` (repmgr, pgpool, Citus, pg_auto_failover, CloudNativePG, Stolon, standalone). |
| `reference/postgres/` | The official version 1 plugin, kept for backward-compatibility checks. |
| `.agents/skills/pluginaudit/` | The site24x7/plugins review rubric, to check against before a PR. |

Older work (the v6 `postgres_cluster` plugin, research, audit notes, console evidence) is on branch `v6`.
