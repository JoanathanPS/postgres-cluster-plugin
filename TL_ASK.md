# Questions for the TL

1. **Template:** can Site24x7 update or pre-declare a plugin's template? Today, 7 metrics never register until their event happens, for example Last Archive Age.
2. **Python:** on Linux, does `use_agent_python=1` use the agent's Python? Where should psycopg2 be installed? On Windows it only worked with `0`.
3. **Permissions:** a missing permission is shown in `msg` once, plus a "Permission Gaps" count every poll. Is once enough, or should it repeat (say, daily)?
4. **Alerts:** can a plugin ship default thresholds, for example Cluster Health ≥ 1 = Trouble and = 2 = Critical?
5. **Old plugin:** deprecate the other intern's `postgres_cluster` once v2 ships?
6. **Minimums:** are PostgreSQL 9.6+ and Python 3.6+ OK?
7. **Patroni:** is plain HTTP to its REST API OK for now, or is HTTPS/auth needed?
8. **PR:** one PR that replaces the `postgres` folder? Who reviews it?
