# TL questions: answers and next steps

## Answered

1. **Template gaps → TL: "pre-declare them as zero, nothing wrong with that."**
   - **To do:** send 0 for the 7 metrics that have no value yet, so every metric registers in the template.
   - **README note:** for the "Age" metrics, 0 means "hasn't happened yet". Alert on "Failovers 24h", not "Last Failover Age".

2. **Minimums → TL: "whatever works."** PostgreSQL 9.6+ and Python 3.6+ stay.

3. **Old metric names → TL: keep both, the old metrics plus the new ones.**
   - **v2 already does this.** Every v1 name is still sent exactly as before ("Total Commits", "Checkpoints Req", the misspelled `Tranasctions_and_Session_per_Database`, and the rest), and the new metrics are added next to them. Existing alerts and charts keep working.
   - **Nothing to change**, unless he meant also sending a cleaned-up copy of each old name. Confirm with him.

4. **Default thresholds → TL: "customers do that, a plugin can't."**
   - **Confirmed by Site24x7's plugin docs:** thresholds are set per monitor in the console ("Threshold and Availability"). A plugin cannot ship threshold profiles.
   - **Our side:** the README lists recommended thresholds. The Health Code covers what only the plugin can judge: no primary, split brain, node down.

## Patroni REST API (research done)

From Patroni's documentation (4.1.5) and the main distributions:

| Setup | What it means for us |
| :--- | :--- |
| Username/password (`restapi.authentication`) | **Only protects the endpoints that change things** (switchover, restart). The read we use, `GET /cluster`, needs no password. We don't need username/password support. |
| TLS (`certfile`) | The API becomes HTTPS. **Supported** (`patroni_scheme=https`). |
| Self-signed certificate | **Supported** (`patroni_verify=false`). |
| Client certificate, `verify_client: optional` | Only demanded on the changing endpoints, so reads still work. |
| Client certificate, `verify_client: required` | Demanded on **every** call, which blocks our read. **Not supported yet.** The plugin then falls back to SQL discovery: it still works, but stopped members aren't seen. |

**What real deployments use:**
- **Plain VM installs (Patroni docs, tutorials):** HTTP.
- **Crunchy PGO (Kubernetes operator):** HTTPS, `verify_client: optional`. Works.
- **Zalando Spilo (Kubernetes):** HTTPS, generating a self-signed certificate if none is given. Works with `patroni_verify=false`.

**Suggest:** what's there now covers all three. Add client-certificate options (`patroni_certfile`, `patroni_keyfile`) only if a customer runs `verify_client: required`. A `patroni_cafile` option (verify against the cluster's own CA instead of switching verification off) is small and worth adding.

## Still to ask

5. **Python (`use_agent_python`).** You didn't get to ask this one. In plain words:
   - **What it is:** the Site24x7 agent can run a Python plugin in two ways:
     - `use_agent_python=1`: with the Python that ships inside the agent. On Linux that's a private Python under `/opt/site24x7/monagent/venv`.
     - `use_agent_python=0`: with the server's own Python (`python3`).
   - **Why it matters:** the plugin needs the `psycopg2` library, and it has to be installed in **whichever Python runs the plugin**.
   - **The mismatch:** the official v1 cfg says `1` (agent's Python), but the official installer installs `psycopg2` into the server's Python. If the agent really uses its own Python, the library isn't there.
   - **What we saw:** on the Windows agent here, the agent's Python had no `psycopg2`, so only `0` worked.
   - **Ask:** "Which Python should plugins use on Linux, the agent's own or the system one? Should the installer put psycopg2 into the agent's Python?"
   - **Once he answers:** the installer can install `psycopg2` into the right one automatically.

6. **Permission note: once or repeated?** Waiting on you to decide. Today it's once (on registration, on change and when resolved), plus the "Permission Gaps" count every poll.

7. **Linux agent test, when he asks for it.** In plain words:
   - **Why:** most customers' database servers run Linux, so the plugin has to be proven with the real Site24x7 **Linux** agent.
   - **Done so far:** the plugin's code runs on Linux; every testbed run used Linux containers. The installer is tested in a Linux container with a stand-in agent: fresh install, upgrade keeping the cfg, and declining an upgrade.
   - **Not done:** a real Linux agent sending data to Site24x7.
   - **What it takes:** a Linux machine (a VM or a container), the Site24x7 Linux agent installed with the org's **device key** (from the console's "Add Server Monitor" page), then our installer. That adds one server to the org account. Takes about 30 minutes.
