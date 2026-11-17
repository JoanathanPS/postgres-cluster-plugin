---
name: pluginaudit
description: >-
  Audits a Site24x7 custom plugin repository or PR for contract compliance, metric correctness,
  cluster/failover semantics, security, and repo layout against the official Site24x7 Copilot instructions.
  Use whenever the user runs /pluginaudit or asks to audit, review, or verify a Site24x7 plugin.
---

# Site24x7 Plugin Audit (`/pluginaudit`)

This skill performs a rigorous, read-only audit of a Site24x7 custom plugin integration (Python, Shell, PowerShell, Batch) before submission to `site24x7/plugins`.

It applies a review rubric derived from the official Site24x7 repository instructions, plugin documentation, and observed pull-request reviews. It is an independent audit framework, not a claim to reproduce Site24x7's internal Copilot configuration.

---

## Non-Negotiable Evidence Rules

- **Citations Required**: Every finding must cite `file:line`, quote the offending code or SQL, and provide the **exact drop-in replacement**.
- **Execution Path Required**: Every finding must identify the exact source location and explain the execution path that produces the defect.
- **Defects vs Risks**: Distinguish confirmed defects from potential risks and unverified assumptions. If the source code does not establish a finding conclusively, downgrade it to an unverified risk or omit it.
- **No Speculation**: Only report defects provable from the code in front of you. If behavior cannot be proven from code or depends on an untested real server version, label it in an `UNVERIFIED AGAINST SERVER` section—never mix it with confirmed findings.
- **No Inventions**: Do not invent runtime output, test results, PostgreSQL behaviour, or Site24x7 agent behaviour.
- **Proposed Fixes**: A suggested replacement is a proposed fix, not proof that the fix works.
- **Version Specificity**: If a finding depends on PostgreSQL version, identify the version and relevant catalog/API behaviour.
- **No Duplicate Headings**: Do not report the same root cause multiple times under different headings.
- **No Style in Defects**: Style, formatting, or naming preferences are not defects. They belong exclusively in a single `Nits` list at the very end (one line each).
- **No Praise / No Fluff**: Do not summarize what the code does well beyond one neutral sentence.
- **Read-Only**: Do not modify files or attempt code fixes during the audit. Report defects only.

---

## Audit Execution Workflow

When `/pluginaudit` is invoked (or when auditing a Site24x7 plugin):

### Step 1: Discover and Read Plugin Artifacts
Locate and inspect all files in the target plugin directory:
1. Main script: `<plugin_name>/<plugin_name>.py` (or `.ps1`, `.sh`, `.bat`)
2. Configuration: `<plugin_name>/<plugin_name>.cfg`
3. Documentation: `<plugin_name>/README.md`
4. Installer (if present): `<plugin_name>/installer/Site24x7<Name>PluginInstaller.sh`

Read the reference standards if needed:
- [Copilot Instructions](./references/copilot-instructions.md)
- [PR 442 Review Rubric](./references/pr-442-rubric.md)

---

### Step 2: Audit Against the 5 Evaluation Sections

#### Section 1 — Blocking Contract Violations (Weight: 30 pts)
*Any violation in this section is a blocking defect.*

1. **Stdout Cleanliness**: Script outputs **exactly one** valid JSON object on stdout and nothing else. No debug prints, warnings, tracebacks, `pprint`, or dict string reprs (`{'key': True}`).
2. **`plugin_version`**: Must be a positive integer. Must be incremented whenever metric keys, units, or tables change.
3. **`heartbeat_required`**: Present as a boolean (`true`/`false`).
4. **Status and Failure Classification**:
   Classify failures before determining monitor status:
   - **Fatal failures**: connection failure, authentication failure, missing mandatory dependency, essential initialization failure, or inability to produce valid output. These must result in `status: 0` and a useful `msg`.
   - **Partial collection failures**: optional metric queries fail while the database remains reachable. Do not automatically mark the entire monitor DOWN. Explicitly represent unavailable metrics and report the partial failure.
   - **Not-applicable metrics**: metrics that do not apply to the detected topology or PostgreSQL version must not be fabricated as zero.
   - **Successful queries returning zero** are valid zero values.
   Verify that `status` reflects actual monitor health, not merely whether every optional query succeeded.
5. **`msg` on Failures**: `msg` must be present whenever `status` is `0`, clearly explaining the error without leaking passwords, tokens, or conninfo strings.
6. **`units` Alignment**:
   - Every key in `units` must exist in top-level metrics or tables.
   - For child tables, units must be nested: `"units": {"<TableName>": {"<col>": "<unit>"}}`.
7. **No Compound Units**: Units must be atomic (`%`, `MB`, `ms`, `count`, `bytes`). Never use compound rate units like `txns/s`, `MB/s`, `rows/s`—the rate must live in the metric/column name.
8. **No Units for Strings**: No unit declared for string metrics or string table columns.
9. **Tab Names**: Tab names must contain only letters, digits, spaces, `_`, and `-`. Never use `&` or special characters.
10. **Hard Table Limits**: Tables <= 10; columns <= 15; rows <= 25 **after** adding the local row; string columns <= 5 including `name`; `name` length <= 520 chars, other strings <= 100 chars. Total top-level metrics <= 200.
11. **Top-Level Attribute Requirement**: If tabular data is present, at least one top-level integer attribute must be present in the JSON root.
12. **Protected Imports**: Third-party modules (e.g. `psycopg2`, `requests`) must be imported inside a try/except block so missing modules emit `status: 0` and clear install instructions rather than crashing with an unhandled `ImportError`.
13. **Timeouts & Clean Exit**: Every network/DB call must have an explicit timeout bounded well below the 50 s agent script budget. Script must exit cleanly.

---

#### Section 2 — Metric Correctness & Semantics (Weight: 30 pts)
*Targeting the failure mode: "The number is wrong but looks plausible on a green dashboard."*

1. **PostgreSQL / Software Version Scope**:
   - Queries must be gated by version (e.g., `pg_stat_checkpointer` is 17+; `pg_stat_io` is 16+; `pg_control_system()` is 10+; `confl_active_logicalslot` is 16+).
   - Ungated SQL that fails silently and produces `0` is a defect.
2. **Semantic Accuracy**:
   - **Replication Lag**: `latest_end_time` is the sender's WAL end, not standby replay progress. Apply lag is `pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn())`.
   - **Port**: `pg_stat_replication.client_port` is the ephemeral source port, NOT the standby's listening port.
   - **Node Identity**: `inet_server_addr()` identifies the connected socket host, not necessarily the primary. The local node's role must derive from `pg_is_in_recovery()`. On a standby, upstream primary is discovered via `pg_stat_wal_receiver`.
   - **Connection Utilization**: `pg_stat_activity` includes autovacuum, parallel workers, and WAL senders. Active connection calculations must filter for client backends (`backend_type = 'client backend'`).
   - **Conflicts**: Summing hand-picked `confl_*` columns misses slot conflicts. Use aggregate `conflicts` from `pg_stat_database`.
3. **Enum Mapping Completeness**:
   - `sync_state` must handle `async`, `potential`, `sync`, and **`quorum`** (PR 442 bug).
   - `state` must handle `startup`, `catchup`, `streaming`, `backup`, `stopping`.
   - Cluster manager roles (e.g. Patroni `leader`, `standby_leader`, `replica`, `master`) and states must be fully handled without unmapped values becoming `0` or `UNKNOWN`.
4. **Never-Populated Metrics**: Any metric initialized to `0` that is never updated from a query result.
5. **Partial Sums as Totals**: Metrics named `Total*` must come from an aggregate engine query, not hand-picked partial sums.
6. **Counters vs Rates**: Cumulative counters must not be reported as rates without persisted previous samples. Emit no rate on cold start (no artificial spikes).
7. **Zero vs Unavailable**: Distinguish "no rows" from "query failed or permission denied". A failed query must not silently emit `0`.
8. **Denominator Honesty**: Capacity calculations, percentages, and expected node counts must come from configuration or discovery, never inferred from the same query that may have returned empty results.
9. **Metric Definition and Measurement Accuracy**:
   - Verify that the implementation measures what the metric name and documentation claim.
   - Distinguish WAL write, flush, receive, and replay positions.
   - Distinguish received-but-not-replayed WAL backlog from time-based replication delay.
   - Do not treat a mathematically valid query as proof that its metric has the correct operational meaning.
   - Verify counter reset behaviour, NULL handling, units, and PostgreSQL version compatibility.
   - Flag ambiguous metric names or undocumented measurement definitions.

---

#### Section 3 — Cluster & Failover Semantics (Weight: 20 pts)
*Specific to clustering, replication, and high-availability plugins (Patroni, repmgr, native streaming, etc.).*

1. **Evidential Cluster Detection**: Cluster manager detection must be evidential and resilient, not assuming a single JSON key.
2. **Split-Brain Detection**: Split brain is flagged only for >1 writable primary in topologies that are not multi-master, and the flag must actually reach health evaluation.
3. **Node Presence vs Down**: A dead/unreachable node keeps its row in the topology table with `last_seen` or `state: down`; dropping the row entirely corrupts cluster history.
4. **Decoupled Failover Sensing**: Failover detection must not depend solely on a single HTTP endpoint remaining reachable.
5. **Read-Only Cluster REST Calls**: All manager interactions (e.g. Patroni REST API) must strictly use GET requests. Never trigger mutations or failovers.
6. **Standalone Instance Handling**:
   The plugin must be tested against a PostgreSQL instance that is not part of a replication cluster.
   Verify:
   - A healthy standalone writable instance is not marked DOWN because no cluster manager or replica exists.
   - A healthy standalone read-only instance is not automatically marked DOWN because no primary is configured.
   - Absence of Patroni, repmgr, Stolon, Citus, CNPG, or replication peers is not by itself proof of a failure.
   - `pg_is_in_recovery()` alone does not establish whether a node belongs to a cluster.
   - Cluster discovery and database health are evaluated independently.
   - Cluster-specific metrics are marked unavailable or not applicable when appropriate.
   - Failed discovery does not fabricate a one-node cluster unless that topology is explicitly established.
   - Explicit standalone and cluster configuration modes, if supported, behave consistently.
7. **Configuration and Detection Ambiguity**:
   Verify behaviour when:
   - `nodes=` is missing.
   - Only one host is configured.
   - A configured host is a standalone primary.
   - A configured host is a standalone standby.
   - A cluster has temporarily lost its primary.
   - Cluster-manager APIs are unreachable but PostgreSQL itself is accessible.
   - Cluster membership cannot be conclusively determined.
   Do not confuse an unknown topology with a confirmed standalone instance or a confirmed cluster failure.

---

#### Section 4 — Security Checklist (Weight: 10 pts)

1. **No Hardcoded Secrets**: Zero plaintext passwords, API keys, tokens, or private hostnames in scripts, `.cfg`, or README files.
2. **No Unsafe Execution**: No `eval()`, `exec()`, or `shell=True` with dynamic strings.
3. **Parameterized SQL**: All dynamic SQL parameters must be parameterized; queries must be read-only.
4. **TLS & Certificate Validation**: TLS verification must not be silently disabled (`verify=False` only if explicit user flag).
5. **Sanitized Error Messages**: `msg` and stdout/stderr must never contain connection strings with passwords or authentication headers.
6. **Least Privilege**: Documentation must explicitly list minimal required database privileges (`pg_monitor` or specific `GRANT SELECT` statements).
7. **Input Validation**: Bound and validate all user-supplied ports, paths, and URLs; reject path traversal in file paths.

---

#### Section 5 — Repo & Documentation Conformance (Weight: 10 pts)

1. **Folder & Script Naming**: Folder name == script name == `.cfg` name (`<name>/<name>.py`, `<name>/<name>.cfg`).
2. **README Structure**: Follows 7-part template:
   1. Title & purpose
   2. Installer one-liner (using `raw.githubusercontent.com/site24x7/plugins/master/...`)
   3. Prerequisites (agent, runtime, modules, privileges)
   4. Manual installation instructions
   5. Configuration table / `.cfg` example
   6. Supported metrics table (metric, description, unit)
   7. Sample output / dashboard image
3. **Configuration Match**: `.cfg` keys map 1:1 to script `argparse` arguments, containing only placeholder values (`"None"`, `<password>`).
4. **Repository Hygiene**: No `__pycache__`, IDE folders (`.vscode`, `.idea`), `.DS_Store`, or binaries.

---

### Step 3 — Verify Behaviour and Test Coverage

For every significant finding, identify its evidence level:
1. **Static analysis**: directly demonstrated by source code.
2. **Unit test**: reproduced using mocked dependencies.
3. **Integration test**: reproduced against a real PostgreSQL instance or cluster.
4. **Site24x7 agent test**: actual agent registration and metric ingestion verified.

Never describe a mocked test as a live integration test.

For PostgreSQL plugins, check the following test scenarios where applicable:
- Standalone writable PostgreSQL.
- Standalone read-only PostgreSQL.
- Single-node cluster.
- Multi-node streaming replication.
- Cluster manager unavailable.
- Primary unavailable.
- Authentication failure.
- Restricted database permissions.
- Unsupported PostgreSQL version.
- Optional metric query failure.
- Empty query result.
- Timeout and interrupted collection.

If the environment does not permit a test, identify it as unverified. Do not award integration-test credit based on static inspection.

---

## Scoring System (Total: 100 Points)

| Dimension | Points |
|---|---|
| Section 1: Output Contract & Registration | 30 |
| Section 2: Metric Correctness & Semantics | 30 |
| Section 3: Cluster & Failover Semantics | 20 |
| Section 4: Security | 10 |
| Section 5: Repo & Documentation Conformance | 10 |

### Verdict Criteria
- **PASS**: Score >= 80, with **zero** blocking issues.
  - Requires:
    - Zero blocking contract violations.
    - No unresolved high-severity correctness defects.
    - Standalone handling verified when the plugin claims to support standalone monitoring.
    - No fabricated metrics or misleading healthy status on failed essential collection.
    - All required tests either executed successfully or explicitly identified as unverified.
- **CONDITIONAL**: Score 60–79, with **zero** blocking issues.
- **FAIL**: Score < 60 OR **>= 1 blocking issue**.

> [!IMPORTANT]
> A static-only audit must never claim that production registration, real PostgreSQL compatibility, or live cluster behaviour has been verified.
> The score is an audit assessment, not an official Site24x7 approval or acceptance score.

---

## Mandatory Output Format

Generate the audit report using this exact template:

```markdown
### 🔴 Blocking / 🟡 Changes recommended / 🔵 Needs a closer look

<one sentence: what class of defect dominates, phrased as consequence, not criticism>

<details open><summary><strong>N open issues</strong></summary>
- [High severity] <imperative title> · New
- [Medium severity] <imperative title> · New
</details>

<details><summary><strong>What changed / Audit Scope</strong></summary>
<one paragraph describing files inspected + file table>
</details>

<sub>Audit effort: Balanced</sub>

---

### Audit Findings

#### [<Severity: High | Medium | Blocking>] <imperative title>
file:line — `<offending code or SQL>`

**What it does:** <concise explanation of current code behavior>
**Why it is wrong:** <explanation citing PostgreSQL / Site24x7 platform specifications>
**Evidence Level:** <Static analysis | Unit test | Integration test | Site24x7 agent test>
**Reproduction:** <scenario, query, or config trigger>
**Fix:** 
```<lang>
<exact replacement code or SQL>
```

---

### Category Checklist & Scorecard

| Dimension | Max Points | Awarded | Status |
|---|---|---|---|
| Section 1: Registration & Output Contract | 30 | X | PASS / FAIL |
| Section 2: Metric Correctness & Semantics | 30 | Y | PASS / FAIL |
| Section 3: Cluster & Failover Semantics | 20 | Z | PASS / FAIL |
| Section 4: Security | 10 | A | PASS / FAIL |
| Section 5: Repo Conformance | 10 | B | PASS / FAIL |
| **Total Score** | **100** | **Total** | **VERDICT: PASS / CONDITIONAL / FAIL** |

---

### Test Coverage & Evidence Verification
*(List scenarios tested or marked unverified: standalone writable/read-only, replication, failover, timeouts, etc.)*

---

### Unverified Against Server
*(List metrics where query correctness depends on specific PG version catalogs not verified in real tests)*

---

### Nits
*(One-line non-blocking style/docs suggestions, or empty if none)*
```
