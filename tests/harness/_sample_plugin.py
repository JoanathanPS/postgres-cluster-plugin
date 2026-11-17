# Minimal stand-in with the same call shape as postgres_cluster.py, only to prove
# the harness end-to-end before the real v5 exists.
import json, psycopg2

def run(param):
    nodes = [n for n in str(param.get("nodes","")).split(",") if n]
    conn = psycopg2.connect(host="10.0.0.1", port=5401, dbname="postgres", user="monitor", connect_timeout=2)
    cur = conn.cursor(); cur.execute("SELECT pg_is_in_recovery();")
    rec = cur.fetchone()[0]
    cur.execute("SELECT sum(numbackends), sum(xact_commit) FROM pg_stat_database;")
    row = cur.fetchone()
    conn.close()
    out = {"plugin_version": 5, "heartbeat_required": True, "status": 1,
           "Primary_Up": 0 if rec else 1, "Primary_Connections": int(row[0] or 0),
           "Primary_Commits": int(row[1] or 0),
           "units": {"Primary_Up": "flag", "Primary_Connections": "connections", "Primary_Commits": "txns"},
           "tabs": {"tabs": {"Primary": {"order": "1", "tablist": ["Primary_Up", "Primary_Connections", "Primary_Commits", "Primary_Typo"]}}},
           "Cluster_Nodes": [{"name": "pg1", "role": 1 if not rec else 2, "status": 1, "last_seen_s": 0}]}
    return out
