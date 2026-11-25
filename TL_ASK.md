# TL questions

## Answered (brief)

1. **Template gaps → "pre-declare them." Done, refined on 2026-11-25.** A monitor's first poll sends every metric (stand-ins where there is no real value), so the template is complete whichever server registers first. Later polls send only real values; what does not apply shows "No Data" (see TRADEOFF.md).
2. **Minimums → "whatever works."** PostgreSQL 9.6+ and Python 3.6+.
3. **Old metric names → "old charts are migrated in the backend, don't carry v1 baggage." Done.** Dropped Cache Hit Ratio, Heap Blocks Read/Hit and Index Rows Read/Fetched, which newer metrics cover. Fixed the `Tranasctions_…` table name. The README's "Upgrading from Version 1" table lists each old name and its replacement (no backend migration needed, see 7).
4. **Default thresholds → "customers set them, a plugin can't." Done.** No thresholds ship with the plugin. The Health Code covers what only the plugin can judge.
5. **`use_agent_python` → settled by testing.** The Linux agent's own Python already bundles `psycopg2`, so we ship `=1`. The README tells Windows users to set `0`. Worth mentioning: the Linux agent writes cfg passwords in plain text to `logs/details/plugins.txt`.
6. **Linux agent test → done (2026-11-24).** A real Full-Stack agent, with all 8 cluster types registered and up and complete templates. Found and fixed an installer bug: current agents say "full-stack agent service", which the v1 check didn't recognise.
7. **v1 migration and tabs → "customers upgrade one at a time when they choose to, so it doesn't matter." Done.** No backend migration is needed. The 16 running totals (Total Rows Inserted, WAL Written, Total Deadlocks…) are no longer sent; their Per Sec or New versions are. The plugin now sends 99 metrics. Tabs are now Summary + 8, all visible: Cluster, Replication, Activity, Transactions and Sessions, DB and IO stats, Vacuum and Wraparound, WAL and Archiving, BG Writer. The Plugin tab's 3 metrics moved to Summary. The README's upgrade table says the replacements are the nearest metrics, not equivalents.

8. **Standalone servers and the cluster tabs → keep the tabs, show "not applicable" as No Data.** Site24x7 fixes a plugin's tabs at the first registration, so tabs can't differ per monitor (6 tests, including empty and missing tabs and a second plugin version). Cluster-only metrics are not sent on a standalone server, so they show "No Data" and never trip a threshold. `-1` was rejected: Site24x7 treats it as a real value.
9. **Missing `pg_monitor` → unchanged.** The monitor message names the unreadable metrics once (and again when the list changes); Permission Gaps carries the count every poll for alerting. It is the user's permission choice, so the monitor stays up.
10. **Primary tab (v6) → not brought back.** It duplicated metrics and needed a second session to the primary every poll.
11. **Renames → done.** BG Writer metrics carry plain names (Scheduled Checkpoints, Buffers Written by Checkpoints / BG Writer / Backends, Backend Fsyncs, Buffers Allocated, BG Writer Stops). Listed in the README's "Metric changes" table.
12. **Patroni setups → no question for the TL.** HTTP, HTTPS, self-signed, own CA, client certificates and an authenticating proxy are all supported and tested.

All questions are answered. Open decisions are in TRADEOFF.md.
