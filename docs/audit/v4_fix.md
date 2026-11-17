# V4 Fixes and Improvement Proposal

## Purpose

This document tracks a v4 cleanup and improvement pass for the Site24x7 PostgreSQL Cluster Plugin. This document records the review findings and work applied on the `v4` branch. Items marked implemented describe current changes; remaining acceptance checks are called out explicitly. No other branch is in scope.

The canonical plugin source is `upstream_layout/postgres_cluster/`. `postgres_cluster/` is a mirror and should be synchronized with `check-layout.ps1` after source changes.

## Current design understood

The plugin polls configured PostgreSQL endpoints, discovers peers where the cluster manager exposes topology, identifies node roles, and emits cluster health, replication, WAL, database, transaction, and per-node statistics. It reports through Site24x7 JSON metrics, five dashboard tabs, and up to ten child tables. The repository contains installers, test harnesses, and Docker/Kubernetes testbeds for multiple PostgreSQL cluster managers.

## Priority 0 — Correctness and maintainability

### 1. Make the cluster README follow the official PostgreSQL plugin README style

I have now compared the local `postgres/postgres.py` standalone collector with the cluster collector and checked Site24x7's published PostgreSQL plugin README. The official README is install-first: short overview, quick installation, prerequisites, installation/configuration steps, a metric reference, per-database table references, and a screenshot. The current cluster README instead opens with a long architecture and design mapping, and mixes end-user installation guidance with implementation details.

**Implemented on `v4`:** Restructured both cluster README copies to follow the official PostgreSQL README's install-first flow and tone, while retaining cluster-specific instructions:

1. Short plugin overview and what the user can monitor.
2. Quick install, prerequisites, and monitoring-role permissions.
3. Linux/Windows installation and a manual JSON smoke-check command.
4. Configuration example and explanation of node discovery/address mapping.
5. A flat metric-by-metric reference for all 97 declared output attributes, followed by child-table and per-database metric references, modeled on the standalone README's metric tables. A static comparison confirms all 97 collector attributes appear exactly once, every displayed unit matches the collector's unit map (text metrics are labeled as text), and no listed name exceeds 25 characters.
6. Health/threshold guidance, tested-cluster matrix, and known limitations/troubleshooting.

Developer-oriented architecture and discovery internals were condensed into a clearly labeled developer section. There are no cluster-monitor screenshot assets in the repository, so the README does not include a screenshot; add one after capturing the current Site24x7 dashboard if you want exact visual parity with the OG README. Keep examples and metric/table names aligned with the active collector output.

The official README currently follows this structure: [Site24x7 PostgreSQL plugin README](https://raw.githubusercontent.com/site24x7/plugins/master/postgres/README.md).

### 2. Establish one accurate documentation baseline

The repository had documents describing different collector generations. On `v4`, the cluster README copies follow the current five-tab/ten-table collector, the test-suite header and PR/structure notes were aligned, and old gap-analysis/plugin-description documents were marked historical. The existing layout checker, e2e helper, lag demo, console checker, and coverage map were updated to the current `Replication_Links` schema. The coverage map also records the v4 rename of the per-database idle-time column.

**Implemented on `v4`:** Corrected the PR description, structure comparison, test-suite header, and marked the gap analysis/plugin description as historical. The collector remains the source of truth. Historical output names remain where appropriate in the standalone plugin, the standalone-to-cluster coverage map, and the v4 migration note; no active cluster collector output uses the old cluster names.

**Acceptance:** The two README copies are install-first and describe the current tabs, tables, discovery behavior, table fields, tested coverage, and the schema migration from the standalone plugin. Core current-facing documents are aligned; historical names in standalone references are clearly distinguished from current cluster output.

### 3. Document OG PostgreSQL parity accurately

The cluster collector's `get_standalone_queries()` was originally documented as matching the local standalone collector's SQL; its docstring now correctly describes shared queries adapted for cluster output. Most baseline query formulas are copied, with PostgreSQL-version-specific checkpoint queries split in the cluster collector. The v4 attribute-limit migration also changes the per-database idle-time SQL alias to `idle_in_txn_time`, so the query is not byte-for-byte identical to standalone. Static comparison found that the cluster collector emitted fabricated zero values for PostgreSQL 17+ `Buffers Backend` and `Buffers Backend Fsync`, while the standalone collector omits those metrics. This has been corrected on `v4`: the cluster collector now omits those flat metrics on PostgreSQL 17+ as well. The cluster implementation intentionally emits numeric values where the standalone implementation often stringifies flat values. `Locks Count` can differ because the standalone connection counts locks held by its own monitoring transaction. Per-database transaction rows differ in handling the standalone's dropped first row versus the cluster collector's explicit `datname IS NOT NULL` filter.

**Implemented on `v4`, with one parity issue found in review:** Added a “Standalone PostgreSQL metric parity” section to the metric reference and corrected the PostgreSQL 17+ fabricated-zero behavior. The section distinguishes shared metric meaning, representation differences, known exceptions, and cluster-only metrics. The flat `Total Conflicts` and `Recovery Conflicts Total` values are queried from the active primary, but PostgreSQL documents that recovery conflicts occur only on standby servers ([PostgreSQL 17 statistics documentation](https://www.postgresql.org/docs/17/monitoring-stats.html)). PostgreSQL 16 documentation also lists the `confl_active_logicalslot` category ([PostgreSQL 16 statistics documentation](https://www.postgresql.org/docs/16/monitoring-stats.html)). These values therefore may be zero and are not cluster-wide standby conflict totals. In addition, the current total sums five categories and omits PostgreSQL 16+ `confl_active_logicalslot`; the existing `collect_standby_conflicts()` result is not wired into plugin output. A future correctness change should aggregate standby-local counters with version-aware category handling, or stop describing the primary-local values as cluster-wide recovery conflicts; no collector behavior changed in this review.

**Acceptance:** Shared query behavior and known exceptions are documented. A full field-by-field mapping remains a follow-up if required; the fabricated-zero case is fixed in both collector copies.

### 4. Align documented Python support with runtime APIs

The installer documentation says Python 3.6+, while the collector uses `ThreadPoolExecutor.shutdown(cancel_futures=True)`, which requires Python 3.9 or newer.

**Implemented on `v4`:** README and active Linux/Windows installers now require Python 3.9+, and Windows discovery rejects older runtimes. The agent’s configured Python must still be checked in a real install.

**Acceptance:** README/installers and collector entrypoint now require Python 3.9+, with a clear JSON prerequisite error from the collector on older runtimes. A real old-runtime run remains unverified.

### 5. Make row truncation explicit

Site24x7 child tables are limited to 25 rows. The collector truncates several tables with `[:25]`, while cluster/database totals may describe more rows than the console displays.

**Change made:** Keep the Site24x7 row limit and report truncation in `msg`, including table name and emitted/available counts. Document the 25-row cap.

**Implemented on `v4`; runtime acceptance pending:** Collector table outputs are capped at 25 rows and truncation notes are added to `msg`. The requested >25-row cases have not been run in this pass.

### 6. Protect Site24x7 template compatibility

Site24x7 requires a new template version when a metric is added, deleted, or renamed, or when tabs change; value-only collection logic changes do not require a version bump ([official versioning guidance](https://support.site24x7.com/portal/en/kb/articles/distinct-plugin-version)). The README now describes this structural rule and treats a separate plugin name as a migration contingency, not a replacement for versioning.

**Implemented on `v4`:** README now documents the structural-version rule and `PLUGIN_VERSION` was bumped to 3 for the initial output additions and to 4 for the attribute-name schema migration. README now includes a manual release checklist for matching canonical/mirror versions, checking JSON attribute changes, and reviewing limits/units. The current layout checker does not automate structural version-bump detection.

**Acceptance:** Guidance and this release’s version bump are in place. No automated structural-change guard has been added.

**Why the guard remains open:** The source declares tabs and units, but those maps do not fully declare string columns such as cluster_type, type_evidence, primary_node, and health_reason; some flat attributes are also conditional on PostgreSQL version. A source-only key scan would therefore be incomplete. A reliable guard needs a captured output-schema manifest covering representative success/error paths and PostgreSQL-version branches, plus a comparison that requires a version increase when that manifest changes.

## Priority 1 — Installation and operational safety

### 7. Make the Windows installer portable

The Windows installer checks several fixed Python paths that include a specific Windows user profile and a limited set of interpreter versions.

**Implemented on `v4`:** Windows installer discovers supported Python from PATH or the launcher and checks `psycopg2`; Linux/Windows install paths and smoke invocations were updated. Static review is complete; neither installer was executed in this pass. The README now states that live-agent installer validation remains unverified instead of claiming the Windows installer was tested.

**Acceptance:** Portability and prerequisite checks are implemented. A Windows machine with a non-default install path and dry-run still need a live installation check.

### 8. Document and tighten credential handling

The plugin config contains a plaintext PostgreSQL password. The installer also accepts passwords on command lines/environment variables, which can be exposed through process inspection or shell history depending on how it is invoked.

**Implemented on `v4`:** README documents plaintext config storage, Linux permissions, Windows ACLs, dedicated role/rotation, safer prompt/environment usage, and the libpq TLS environment-variable path and limitations. Installer smoke checks avoid password arguments.

**Additional static-review fix:** The tracked canonical config previously contained a working-looking `site24x7` password and local test endpoints. It now uses placeholder credentials and generic connection values, matching the example config; users must replace `CHANGE_ME_monitor` before running it. The installers continue to generate per-install configs and restrict their access.

The collector now detects common unmodified password placeholders and returns a configuration error before connecting, rather than surfacing a misleading PostgreSQL authentication failure. This is a configuration-path change and does not alter the emitted metric schema.

The bundled monitoring-user SQL and Linux helpers also had a built-in site24x7 password. The SQL now creates/grants the role without a password, and setup uses psql's \password prompt in a separate interactive command. This avoids a default credential and avoids placing the chosen password in command arguments or shell history. The working copies are synchronized with the canonical prerequisites.

**Monitoring setup minimum-version gap found in review:** `create_user.sql` uses psql's `\if`, which was added in PostgreSQL 10, and conditionally grants `pg_monitor` when present; it then unconditionally grants `pg_read_all_stats` and `pg_read_all_settings`. PostgreSQL 9.6's psql lacks `\if` and its default-role list lacks those roles, while PostgreSQL 10 documents both the conditional command and the roles ([psql 10 release notes](https://www.postgresql.org/docs/10/release-10.html), [PostgreSQL 9.6 roles](https://www.postgresql.org/docs/9.6/default-roles.html), [PostgreSQL 10 roles](https://www.postgresql.org/docs/10/default-roles.html)). So guarding only the role grants would not make the current helper work on 9.6. Decide whether PostgreSQL 10+ is the intended minimum and document it consistently; if earlier versions are supported, provide a separate compatible setup path and version-appropriate privileges. Some collector query paths retain pre-10 branches, so the support boundary should be explicit. This was found by source/documentation review and was not runtime-tested.

The Linux helper passes the role name as a psql variable in `\password :mon_user`. PostgreSQL documents variable interpolation in meta-command arguments, so the username is substituted while psql still prompts for the password; this usage was checked against the documentation but not runtime-tested.

The repository also contained an unreferenced legacy PowerShell runner outside the upstream package. Its hard-coded developer Python paths and sample credentials have been removed; it now uses PATH discovery, blank connection defaults, the current plugin version on wrapper errors, and `PGPASSWORD` instead of placing a supplied password in Python's process arguments. It remains outside the documented installer path and was not runtime-validated.

The cluster README now explicitly labels that wrapper as legacy and directs Windows users to the supported Python collector and installer flow.

The separate development deployment script no longer has a built-in sample password; it prompts securely or reads MONITOR_PASSWORD, writes the config to a uniquely named temporary file, restricts that file to LocalSystem and Administrators, and only then replaces the active config.

The local Patroni initializer also stopped passing replication and monitoring passwords as psql `-v` command-line arguments. It now imports them from the already-required environment variables with psql's `\getenv`; the values are still present in the container environment, but no longer appear in psql's argument list.

The Windows installer help examples no longer show passwords in command arguments, and its missing-settings message now directs unattended users to the supported environment variables. The interactive path continues to prompt with a secure, non-echoing input.

**Acceptance:** Setup documentation states where credentials are stored, how to restrict access, credential rotation, and TLS behavior. Document the monitoring-user helper minimum PostgreSQL version or validate its role grants against the minimum supported version. The active smoke-check path uses `PGPASSWORD`; environment variables can still be visible to sufficiently privileged local processes.

### 9. Clarify health and threshold configuration

The plugin reports cluster-health metrics, while Site24x7 leaves metric threshold values unset in its default profile. The README has static starter recommendations and distinguishes them from the current Zia-based anomaly-threshold option.

**Implemented on `v4`:** README explains collector health versus monitor `status`, includes starter static thresholds, documents all five configurable collector health thresholds, and describes when to consider Zia-based thresholds. No account-specific Zia profile was configured.

**Acceptance:** A new user can tell which alerts require a Site24x7 profile and can configure the recommended signals without confusing collector health codes with platform monitor availability (`status`).

## Priority 2 — Feature and model tuning

These began as candidates rather than confirmed defects. The documentation and health-threshold improvements below are now implemented on v4. A predictive/ML model is not part of this collector; the tuning here concerns database telemetry and health policy.

### 10. Add rate-oriented views for cumulative counters

PostgreSQL statistics such as commits, rollbacks, block reads, and tuple counts are cumulative counters. Their absolute values are valid but can be less useful for diagnosing current workload.

**Implemented as guidance on `v4`:** README distinguishes cumulative counters from rates and recommends static thresholds for explicit health flags. It also documents Zia-based thresholds for continuous metrics after a representative baseline, with a caution about monotonic counters.

**Deferred feature proposal:** A useful first pass would add per-second rates for commits, rollbacks, rows inserted/updated/deleted/fetched/returned, and block reads/hits. Keep these rates primary-scoped because the existing flat counters describe the active primary. Exclude conflicts from this first rate set: the collector currently reads them from the active primary, while PostgreSQL documents that recovery-conflict counters accrue only on standby servers; a standby-scoped rate needs a separate identity and aggregation design. Candidate attributes (`Commits Per Second`, `Rollbacks Per Second`, `Rows Inserted Per Sec`, `Rows Updated Per Sec`, `Rows Deleted Per Sec`, `Rows Fetched Per Sec`, `Rows Returned Per Sec`, `Block Reads Per Sec`, and `Block Hits Per Sec`) fit Site24x7's 25-character name limit; use `transactions/s`, `rows/s`, or `blocks/s` units as appropriate.

Persist prior values and a timestamp atomically. The current collector config has no Site24x7 monitor ID, so use a hash of normalized non-secret config identity (nodes, address map, discovery mode, database, username, and cluster type) plus an optional `state_id` setting for two monitors with otherwise identical config; never include the password. Include the current primary identity (node name and resolved endpoint) in the stored sample so a detected failover invalidates the rate interval. A SQLite state store is a candidate because Python provides transactional SQLite support and busy-timeout handling; serialize each read/compute/write operation in a `BEGIN IMMEDIATE` transaction with a bounded busy timeout. Store it under a documented plugin state directory with agent-only permissions on Linux and equivalent Windows ACLs.

Reset correctness must preserve the per-database shape: the current collector sums counters across `pg_stat_database`, while PostgreSQL exposes `stats_reset` per database ([PostgreSQL statistics documentation](https://www.postgresql.org/docs/17/monitoring-stats.html)). A reset in one database can be masked by growth in another if only the aggregate sum is compared. Store samples keyed by database OID with each database's `stats_reset`; calculate per-database deltas before summing rates. Define readiness behavior when the database set changes (for example, invalidate the whole rate interval for one poll) and when a database disappears. A simple aggregate-counter decrease check is insufficient.

Keep the output schema stable: emit zero rates and `Counter Rates Ready = 0` until a valid interval exists, then emit calculated rates and set the flag to `1`. Set rates back to zero and the flag to `0` after a primary change, a counter decrease/reset, invalid elapsed time, or inaccessible/corrupt state; add a concise message when state cannot be read or saved. Never emit a negative rate or treat a counter reset as workload. This adds 10 generic metric attributes (9 rates plus the readiness flag) and would require `PLUGIN_VERSION` 5; based on the current 97-attribute static audit, the estimate would be 107 of Site24x7's 200 generic-metric limit, to be re-counted before implementation. Review check: all 10 proposed labels are unique against the current collector and are at most 21 characters, within Site24x7's 25-character limit. It also creates a readiness metric that operators must account for when configuring thresholds. Before implementation, choose the state-file location and permissions, confirm the bounded lock-timeout behavior, and confirm the zero-plus-readiness-flag behavior is acceptable in dashboards. This proposal is not implemented.

### 11. Improve health-policy configurability

At the start of the review, replay delay/backlog thresholds were not configurable through the plugin, while failover and slot-WAL thresholds were. Environments differ in acceptable replication delay and backlog.

**Implemented on `v4`:** Replay delay/backlog thresholds are configurable through collector params, CLI, and installer config. Defaults are 60 seconds and 104857600 bytes; values are validated as nonnegative, and health notes identify the observed delay/backlog condition.

**Additional configuration improvement:** The active config template, example, and both installer-generated configs expose failover warning and replication-slot warning/critical thresholds. Windows accepts these through installer parameters; Linux prompts interactively and accepts environment variables for unattended runs. README gives their defaults and explains zero/ordering behavior, so operators can tune all five health policy thresholds without editing Python source.

The collector and both installers now reject negative thresholds and `slot_critical_bytes <= slot_warn_bytes` before collection/deployment. This preserves a usable warning band and matches the README requirement. Linux checks the values with its already-required system Python before attempting its database smoke check.

Manual config values that are not integers now return an actionable `ConfigError` naming the invalid threshold key, rather than the generic unexpected-entrypoint exception.

**Threshold documentation review:** The README previously implied that either slot threshold could be zero. Source validation requires `slot_critical_bytes > slot_warn_bytes >= 0`, so only the warning threshold can be zero; the README now states this precisely. The health evaluator uses strict `>` comparisons, so equality with the configured byte/second threshold does not trigger that threshold.

### 12. Improve discovery and scale observability

Discovery is a central feature, but node reachability, table caps, and discovery source affect what a user sees.

**Implemented on `v4`, with omission-count and coverage-policy gaps found in review:** Added configured/discovered/omitted counters and manager-specific seed guidance. Discovery remains bounded by the collection deadline. A separate reachable-node counter was not added because `Nodes Up` already reports reachable nodes. `Cluster Health` receives only the capped `nodes_total` and `nodes_up`; it does not receive `nodes_omitted`, so it can report healthy for the polled subset while nodes remain unpolled. The README now recommends a Site24x7 Trouble threshold on `Nodes Omitted > 0`. The omission count is also not a unique-node count: configuration omissions are added before discovery, but discovery receives only the capped seed list and builds its known-address set from those seeds. If a manager returns a full inventory containing configured seeds beyond the cap, the same nodes can be added again as discovery omissions. Conversely, the streaming-topology walker stops at `MAX_NODES` or its deadline, so additional unknown members may be missed. Thus `Nodes Omitted` can overcount or undercount. Deduplicate against the original configured endpoint set and discovered endpoints before counting; track discovery completeness separately, and decide whether incomplete coverage should degrade `Cluster Health` or use a `Discovery Complete`/`Discovery Capped` signal. **Correction from current-source review:** the diagnostic lists are initialized in the collector constructor before `_collect_internal()` parses inputs; the current source has no post-discovery reset. The earlier claim that these notes were cleared before polling was incorrect and is removed. The cache-write warning and cap notes are carried into `msg` by the existing assembly path, though these paths still need runtime acceptance.

**Documentation refinement:** The README now explains the 24-hour topology-cache fallback, its location beside the collector, and that cached membership does not make an unreachable PostgreSQL node pollable. This was confirmed against `_load_cache()` and the discovery fallback in the collector.

**Reliability improvement:** Cache refresh now writes to a unique temporary file in the plugin directory and atomically replaces `topology_cache.json` only after serialization succeeds. This avoids leaving a partially written cache if collection is interrupted and avoids temporary-file name collisions. Concurrent refreshes are still last-writer-wins; cache writes do not use a cross-process lock. Cache write failures remain non-fatal to monitoring.

The cache-write failure path adds a generic warning without exposing file paths or other sensitive details. README troubleshooting points operators to plugin-directory write access; live polling remains available when cache writes fail. The source path appears to preserve the warning in `msg`; verify this behavior in runtime acceptance.

### 13. Expand compatibility validation before claiming support

The README lists several cluster managers and PostgreSQL versions, but coverage differs between live tests and detection fixtures.

**Implemented on `v4`, with evidence retention still open:** README now separates live integration coverage, fixture-only detection, supported-but-unverified pglogical integration, detected-but-unsupported managed services, and unverified PostgreSQL/OS combinations. The stale test-suite fixture count was corrected from 13 to 16. The live-coverage table now matches the source testbeds: native multi-master is three-node PostgreSQL 17, while pg_auto_failover and CloudNativePG versions are explicitly marked unpinned. However, the workspace contains test runners and testbed definitions but no saved test logs, CI result artifacts, or release run records. The README's rule says “Live” means the plugin was actually run against a real cluster, so that claim cannot be reverified from retained repository evidence. Keep “tested” claims tied to dated run evidence or relabel them as “live testbed configured; execution evidence not retained.” Broader version coverage remains future work; no new live compatibility claims were added.

## Site24x7 guideline checklist

- Preserve required output keys: `plugin_version`, `heartbeat_required`, and reserved monitor `status` semantics (`1` when collection succeeds, `0` on configuration/execution failure; separate from cluster health).
- Keep at least one numeric metric in successful output and valid JSON on every execution path.
- Keep within documented limits: 200 generic metrics, 10 tables, 15 columns/table, 25 rows/table, and 5 string columns/table including the reserved `name` column.
- Keep `name` exactly cased in child tables; Site24x7 allows up to 520 characters in this column and 100 characters in other string columns. The collector caps child `name` values at 520 characters and other child strings at 100 characters. It limits `Cluster_Info` and `Replication_Links` to five strings including `name` by removing redundant text fields.
- Static source review confirms `Cluster_Info` and `Replication_Links` each use the five-string-column allowance (including `name`). `validate_schema()` contains row-count, total-column, string-count, and string-length assertions, but the runner calls it only for Test 1's successful three-node output. Dead-host and wrong-password cases parse JSON and check status without applying those Site24x7 schema assertions; this pass did not run the tests. Its generic-metric counter excludes several envelope keys but not the reserved `msg` key, so a warning-bearing result counts `msg` toward the 200-metric limit. It also does not assert the 25-character name limit for top-level metrics, table names, or table columns; current compliance was checked manually. Refine the reserved-key set, add name-length assertions, and extend acceptance to validate the required output envelope and applicable table/attribute limits across error and unsupported-cluster paths.
- Use `units` for numeric metrics and nested table columns. Added the missing unit maps for both standalone-compatible per-database child tables; session timing columns use milliseconds per PostgreSQL documentation. A source-level audit found 97 distinct flat data attributes, below the 200 generic-metric limit, and nested-unit maps for all ten tables. The README now includes a manual release checklist for plugin-version changes.
- Keep `msg` concise and actionable; never leak passwords or connection strings.
- Configure thresholds explicitly in Site24x7; do not imply that plugin health metrics automatically create alert thresholds.
- Increment the plugin template version when metric/table structure changes (including attribute additions, removals, renames, or tab changes); logic-only changes with unchanged names and structure do not require a bump. `PLUGIN_VERSION` is 4 for the v4 structural changes.

Reference pages: [Site24x7 custom plugin output](https://app.site24x7.com/help/admin/adding-a-monitor/plugins/custom-plugins.html), [plugin best practices](https://www.site24x7.com/help/best-practices/plugin-integrations.html), [plugin versioning](https://support.site24x7.com/portal/en/kb/articles/distinct-plugin-version), and [plugin thresholds](https://support.site24x7.com/portal/en/kb/articles/how-does-threshold-setting-work-for-plugins).

## Remaining review items

The v4 documentation and implementation updates are prepared for your review. Static cleanup now updates existing helper references to the current `Replication_Links` table. The layout checker now compares hashes for the collector, README, installers, user-setup helpers, and config template, and confirms canonical/mirror `PLUGIN_VERSION` parity. This verifies mirror consistency but does not detect schema changes that forgot a version bump. Over-limit metric/table attribute names are renamed to comply with Site24x7’s 25-character limit; the schema migration and OG differences are documented. Runtime validation, >25-row cases, Windows/Linux installer execution, and a Site24x7 screenshot remain outstanding. No automated output-schema baseline guard or interval-rate state was added.

| Review order | Open item | Current proposal | What remains before calling it complete |
| --- | --- | --- |
| 1 — Release acceptance | Runtime, cap diagnostics, and installer validation | Exercise error/partial-outage states, 25+ row cases, configured/discovered overlap above 25 nodes, topology discovery at its 25-node cap and deadline, and Linux/Windows installation paths. | Confirm accurate `Nodes Omitted` counts and cap/cache-write messages, decide the health policy for `Nodes Omitted > 0`, and run on supported local testbeds and agent environments; reconcile output with Site24x7 limits. These checks have not been run in this pass. |
| 2 — Compatibility | PostgreSQL and psql minimum version | Decide and publish the oldest supported PostgreSQL server version, including setup-tool requirements. | `create_user.sql` uses psql `\if` (added in PostgreSQL 10) and grants roles absent in 9.6. Either document PostgreSQL 10+ consistently or create a separate older-version setup path and validate its privileges. The collector's legacy query branches alone do not establish end-to-end support. |
| 3 — Reliability | Output-schema version guard | Compare a checked-in manifest of flat metrics, tab membership, table names/columns, units, and child discovery against representative collector output. | Capture populated and empty success output for physical/logical replication, PostgreSQL before/after 17 checkpoint fields, plus configuration error, unsupported cluster, and all-nodes-down output. Review which fields are conditional, then add a comparison that requires a `PLUGIN_VERSION` increment for structural changes. The current layout checker verifies mirror parity only. |
| 4 — Installer compliance | Custom Windows plugin folder name | Validate `-PluginFolderName` against Site24x7 naming rules before deploying. | The default `postgres_cluster` is compliant, but the PowerShell installer accepts arbitrary values that become both a directory name and the `.py` script basename. Reject names outside the alphanumeric/underscore rule and ensure the generated script filename stays within Site24x7's 30-character limit; validate accepted and rejected cases. |
| 5 — Optional feature | Counter rate metrics | Add reset-aware per-second rates for selected cumulative PostgreSQL counters, backed by private local state keyed to monitor and primary identity. | Select the counters and state location; define permissions and concurrent-poll behavior; validate first-sample, failover, reset, and invalid-time cases. No rate attributes are emitted today; adding them means 10 new generic attributes (9 rates plus readiness) and version 5. |
| 6 — Documentation polish | Site24x7 visual parity | Add a dashboard screenshot to the install-first README. | Capture the current v4 dashboard in a Site24x7 account after registering the versioned schema. No screenshot asset is available in the repository. |

### Review of the remaining proposals

These items remain proposals for review; this assessment does not authorize new collector behavior.

1. **Complete runtime and installer acceptance before release.** This is the highest-priority open item because current evidence is source inspection only for several failure states, row truncation, and installer flows. Run the already-listed acceptance plan in supported environments, then update claims from observed output.
2. **Set the PostgreSQL support boundary.** The supplied user-setup path makes PostgreSQL 10 the practical minimum unless an older-version helper is added. State the minimum consistently in README prerequisites and installer/setup guidance; do not infer support from collector query branches alone.
3. **Build the schema/version guard before the next structural change.** Site24x7 creates a new template when a metric is added, removed, or renamed, or tabs change; logic-only collection changes do not require a bump. A captured-output manifest is appropriate because conditional fields and PostgreSQL-version branches make source-only scans incomplete. Keep it focused on the structural surface Site24x7 registers and representative populated/empty table schemas.
4. **Validate custom installer names before relying on them.** Site24x7's [plugin registration guidance](https://support.site24x7.com/portal/en/kb/articles/possible-reasons-why-my-windows-plugin-is-not-added-to-my-site24x7-account) limits plugin script filenames to 30 characters and restricts file/folder names to alphanumeric characters and underscores. The default `postgres_cluster.py` and folder comply, but the Windows `-PluginFolderName` parameter is interpolated into the folder, script filename, and config section without visible validation. This gap affects custom names, not the default installation.
5. **Keep rate metrics optional.** They improve workload interpretation but introduce local state, permissions, reset/failover semantics, and a readiness metric. Before implementation, decide how monitor identity is represented when two monitors share the same configuration, preserve per-database `stats_reset` by database OID, and define readiness when the database set changes. An aggregate decrease check can miss one database reset masked by growth in another. Do not present zero rates as measured workload before a valid interval.
6. **Treat the dashboard screenshot as presentation polish.** It requires a registered v4 template in a Site24x7 account and is not a code correctness gate.

The official plugin limits and reserved-key references support the checklist above: [plugin limitations](https://support.site24x7.com/portal/en/kb/articles/limiting-features-of-a-plugin), [reserved keys](https://support.site24x7.com/portal/en/kb/articles/reserved-keys-in-plugins), and [template versioning](https://support.site24x7.com/portal/en/kb/articles/distinct-plugin-version). The current README also correctly says plugin alert thresholds must be configured in the web client; Site24x7 creates a default profile without setting metric threshold values ([threshold guidance](https://support.site24x7.com/portal/en/kb/articles/how-does-threshold-setting-work-for-plugins)).

### Site24x7 attribute-name limit and schema migration

Site24x7 documents a maximum attribute-name length of 25 characters ([plugin limitations](https://support.site24x7.com/portal/en/kb/articles/limiting-features-of-a-plugin)). On `v4`, cluster-specific long metric labels were shortened to `Connection Usage Percent`, `Oldest Running Txn Age`, `Logical Replication Used`, `Inactive Slots Count`, and `Failover Age Seconds`; the per-node idle-in-transaction field is `idle_in_txn_count`. The three over-limit OG-compatible names have now been renamed: flat metric `Transactions Idle In Transaction` to `Idle Transactions`, table `Tranasctions_and_Session_per_Database` to `Transactions_Per_Database`, and table field `session_idle_in_transaction_time` to `idle_in_txn_time`.

**Implemented on `v4`:** Both canonical and mirror collectors emit the renamed attributes; tab lists, child-discovery metadata, units, coverage mapping, and current README references use the new names; `PLUGIN_VERSION` is now 4. Existing cluster tests were updated where they assert the renamed table. These changes preserve Site24x7’s documented 25-character attribute-name limit, but break references to the old attributes. Existing thresholds, dashboards, reports, and integrations may need to be recreated or remapped when the new template version is registered. Confirm migration behavior in the Site24x7 account before production rollout.

**Static reference sweep:** A repository-wide search found the old names only in this migration explanation, the README migration explanation, the unchanged standalone PostgreSQL plugin and its standalone test, the archived historical documents, and `coverage_map.json`'s `old_item` entries. The active cluster collector, cluster test, installers, and current structure notes use the new names. Canonical and mirrored collectors report version 4; the legacy PowerShell wrapper also uses version 4 for its error output. This confirms text/schema-reference consistency only; it does not replace runtime output or Site24x7 template validation.

Optional follow-up work can implement the rate-state design above or add Site24x7 derivative/rate metrics if the account exposes a supported transformation. The current official help describes static and Zia-based thresholds, but does not document an in-plugin derivative transform. This collector does not contain a predictive/ML model; its current “tuning” is health-threshold configuration for replay delay/backlog, recent failover, and replication-slot WAL retention.

## Test and acceptance plan

- Run `check-layout.ps1` after editing the canonical plugin documentation/source and mirror.
- Refine the generic-metric validator to exclude Site24x7 reserved output keys such as `msg`; include a warning-bearing output when verifying the 200-metric count. Assert that top-level metric names, table names, and child column names stay within 25 characters.
- Run `python tester/test_cluster_plugin.py` and reconcile test descriptions with the actual assertions and collector output.
- Validate successful, configuration-error, authentication-error, all-nodes-unreachable, partial-node-outage, unsupported-cluster, and no-primary output as valid JSON with the required output envelope and correct `status` behavior; apply applicable Site24x7 metric/table limit checks to each representative output.
- Exercise row counts at 25 and above 25 for node, slot, and per-database tables; verify truncation notes and all Site24x7 limits.
- Verify the Windows installer with Python discovered from PATH/launcher and confirm the agent uses the same supported interpreter.
- Run the expanded layout checker to compare canonical/mirror collector, README, installer, helper, and config-template files; separately review that each metric/tab/schema change increments `PLUGIN_VERSION` and that existing/new monitor registration behavior is documented accurately.
- If counter rates are approved, verify the first sample, a known elapsed-interval calculation, primary change, counter reset/decrease, invalid elapsed time, unreadable state, and overlapping polls; confirm the readiness flag prevents a zero placeholder from being mistaken for measured workload.
- If the schema guard is approved, verify it flags a changed metric/table/column/unit manifest without a version increase and accepts the same manifest when `PLUGIN_VERSION` is incremented.
- Do not claim new PostgreSQL or cluster-manager compatibility until covered by an appropriate live integration test, and retain the run result with the plugin/testbed versions so README “tested” claims are auditable.

## Assumptions

- `upstream_layout/postgres_cluster/` remains the source of truth; `postgres_cluster/` remains its mirror.
- The current five-tab layout and current collector output are the intended v4 starting point.
- Site24x7's documented limits remain the governing output constraints.
- This proposal prioritizes correctness, clear operations, and safe compatibility before optional new telemetry.
