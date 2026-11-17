# Site24x7 Review Rubric: Empirical Findings & Bar (PR 442 Baseline)

## Real-World Context: Why the Bar is High

Site24x7 custom plugins are reviewed against strict criteria. In pull requests like PR 442 (*PostgreSQL Cluster Monitoring Plugin*), automated and human reviewers flagged 11 key issues (8 High, 3 Medium).

Crucially, **8 of 11 findings were NOT crashes or syntax errors**—they were "the number is wrong but looks plausible." A green dashboard displaying inaccurate data is the primary failure mode targeted by this audit.

## The 11 PR 442 Findings Verbatim in Substance

| # | Sev | Finding | Class of Bug | Correct Behavior / Fix |
|---|---|---|---|---|
| 1 | High | `sync_state='quorum'` reported as Async; an `ANY ...` cluster is misclassified | Wrong enum mapping | Map `quorum` to `Sync` or explicit quorum status, not default Async |
| 2 | High | `latest_end_time` used as apply lag; it is the sender's WAL end, not standby's replay progress | Wrong quantity, plausible name | Use `pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn())` |
| 3 | High | `Buffers Backend Direct Writes` hardcoded `0`, no query ever fills it | Metric that can never be non-zero | Derive from `pg_stat_bgwriter` or omit if unqueryable |
| 4 | High | `pg_stat_checkpointer` is 17+ only; on <=16 the query fails and five counters stay `0` | Unversioned SQL | Gate queries by server version (`SHOW server_version_num`) |
| 5 | High | `pg_stat_activity` count includes autovacuum/parallel/WAL-sender backends, inflating connection utilisation | Wrong denominator | Filter `backend_type = 'client backend'` or `backend_type IS NULL` (older PG) |
| 6 | High | Conflicts sum only 5 types, missing `confl_active_logicalslot`; use aggregate `conflicts` | Partial sum presented as total | Use aggregate `conflicts` from `pg_stat_database` |
| 7 | High | `inet_server_addr()` identifies connected server, so standby is listed as active primary | Identity from wrong source | Local node identity must derive from `pg_is_in_recovery()`, not connection host |
| 8 | High | Standalone entry point prints a Python dict (`'key': True`) — invalid JSON | Output contract violation | Must print valid JSON via `json.dumps()` |
| 9 | Med | Module-level `import psycopg2` raises before `main()`'s ImportError handler can run | Unreachable error path | Place third-party imports inside protected try/except |
| 10 | Med | `pg_stat_replication.client_port` is standby's ephemeral source port, not listening port | Column semantics | Do not display ephemeral socket ports as node ports |
| 11 | Med | 1 local row + 25 replicas = 26 rows > the 25-row limit | Platform limit violation | Total rows in table must be capped at <= 25 rows strictly after adding local node |

## Strict Audit Rules

1. **Non-negotiable evidence**:
   - Every defect must cite `file:line`, quote the code/SQL, and give the exact replacement.
   - Zero speculation. If unverified against server, label `UNVERIFIED AGAINST SERVER`.
   - No praise or fluff.
   - Nits separated at the bottom.
2. **Scoring Breakdown (100 Points Total)**:
   - Registration & Output Contract: 30 pts
   - Metric Correctness: 30 pts
   - Cluster & Failover Semantics: 20 pts
   - Security: 10 pts
   - Repo Conformance: 10 pts
   - Thresholds:
     - `PASS`: >= 80 pts, 0 blocking issues.
     - `CONDITIONAL`: 60–79 pts, 0 blocking issues.
     - `FAIL`: < 60 pts or >= 1 blocking issue.
