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

## 6. Register in Site24x7 (needs your Site24x7 account – not done by this repo)

A plugin that prints valid JSON locally is **not** the same as a monitor registered in the
Site24x7 web console. Registration only happens when a Site24x7 agent runs the plugin and posts the data.

### Option A – Site24x7 Windows agent on your PC (closest to your setup)

The postgres plugin README says Python plugins can run on the Windows agent once Python is on the
system PATH. Site24x7's generic plugin page lists only Batch/PowerShell/VB/DLL for Windows, so treat
this as **supported by the plugin README, but not verified here**.

```powershell
# Run in an elevated (Administrator) PowerShell
py -m pip install psycopg2-binary            # system-wide install, so the agent (LocalSystem) can import it

Copy-Item postgres\postgres.cfg.example postgres\postgres.cfg
notepad postgres\postgres.cfg                # set password= to MONITOR_PASSWORD (both sections)

Copy-Item -Recurse postgres "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres"

# Optional: run the plugin as SYSTEM, like the agent does (PsExec from your Task 1 folder)
.\ScheduledTask\PSTools\PsExec64.exe -accepteula -s py "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres\postgres.py" --host localhost --port 5432 --username site24x7 --password <MONITOR_PASSWORD> --db appdb
```

According to the plugin README, the agent picks up the plugin within about 5 minutes. Check
**Site24x7 → Plugins → Plugin Integrations** for two monitors (`postgres.py-pg_primary`, `postgres.py-pg_replica`).
After its first run, the agent encrypts the `password` field in `postgres.cfg`.

### Option B – Site24x7 Linux agent

Use this if your mentor expects Linux, e.g. a Linux VM or server. Copy the `postgres` folder to
`/opt/site24x7/monagent/plugins/postgres` and set `host=` in `postgres.cfg` to an address that reaches the
Docker host's published ports. Plugin logs are in `/opt/site24x7/monagent/logs/details/plugins.txt`.

### Not used – `site24x7/docker-agent` container

Site24x7 does publish an official Docker agent image that runs plugins from `/opt/site24x7/monagent/plugins/`.
However, its full `docker run` command is generated only in the Site24x7 console
(Server → Docker → Docker Host). On Docker Desktop it would also monitor the WSL2 VM rather than your PC.
So it is deliberately not added to this compose file.

---

## 7. How monitoring works across the cluster

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
