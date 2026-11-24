# Questions for the TL

1. **Template:** can Site24x7 update or pre-declare a plugin's template?
   - Today, 7 metrics never register until their event happens, for example Last Archive Age or Last Failover Age.

2. **Python:** on Linux, does `use_agent_python=1` use the agent's Python?
   - Where should psycopg2 be installed?
   - On Windows it only worked with `0`.

3. **Permissions:** a missing permission is shown in `msg` once, plus a "Permission Gaps" count every poll.
   - Is once enough, or should it repeat (say, daily)?

4. **Minimums:** are PostgreSQL 9.6+ and Python 3.6+ OK?

5. **Old names: keep them, or fix them in v2?**
   - **Today v2 keeps every v1 name** so existing monitors don't break:
     - the table `Tranasctions_and_Session_per_Database` (misspelled)
     - `Stats_per_DB`
     - old metric names such as "Checkpoints Req", "Maxwritten Clean", "Buffers Alloc"
     - "Cache Hit Ratio" as a 0–1 fraction, while the new metrics use %
   - **Why it matters:** customers' alerts and dashboards point at those names. Renaming one silently breaks their alert and starts a fresh chart with no history.
   - **But v2 is a new template anyway** (`plugin_version` 2), so this is the one chance to clean names up.
   - **Options:**
     - **(a) Keep the old names.** Safest for existing users, but the misspelling ships again.
     - **(b) Fix all names now.** Cleanest, and every v1 user re-creates their alerts.
     - **(c) Fix them, plus a one-version transition.** Send both the old and new name in v2, drop the old ones in v3, and list the renames in the README. *(my pick)*
   - **Ask:**
     - Does Site24x7 carry alerts or threshold profiles across a plugin_version bump?
     - Has any official plugin renamed metrics before, and how was it handled?

6. **Patroni REST API: plain HTTP, or do we need HTTPS and auth?**
   - **What v2 does now:**
     - Patroni is read only if `patroni_port` is set; otherwise SQL discovery is used.
     - `patroni_scheme=https` is supported. The certificate is verified by default; `patroni_verify=false` is for self-signed certificates.
     - **Not supported yet:** a username/password (Patroni's `restapi.authentication`) and a client certificate (mTLS).
   - **Why it matters:**
     - The plugin only reads `GET /cluster`. Patroni normally protects only the *changing* endpoints (switchover, restart) with auth, and leaves reads open.
     - Some hardened setups put auth or mTLS on every endpoint. Those would fall back to SQL discovery: it still works, but stopped members aren't seen.
   - **Ask:**
     - Is that fallback acceptable, or should v2 ship with `patroni_username`/`patroni_password` now? Adding them is small, and the agent encrypts the password like any other cfg value.
     - Do Zoho customers commonly run Patroni with REST auth?

7. **Default thresholds (for later):** can a plugin ship default threshold profiles, or do we only document recommended values in the README?
