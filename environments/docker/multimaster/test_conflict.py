import psycopg2, time, sys
sys.path.insert(0, r"D:\College\Year 3\Internship\Zoho\Task 2 - PostgreSQL Cluster Plugin - v2\postgres_cluster")
import postgres_cluster

print("Simulating concurrent conflicting write during disconnected link...")
c2 = psycopg2.connect(host='127.0.0.1', port=5452, user='site24x7', password='site24x7', dbname='postgres')
c2.autocommit = True
c3 = psycopg2.connect(host='127.0.0.1', port=5453, user='site24x7', password='site24x7', dbname='postgres')
c3.autocommit = True

# Disable subscription
with c3.cursor() as cur:
    cur.execute("ALTER SUBSCRIPTION sub_pg_mm3_from_pg_mm2 DISABLE;")

time.sleep(0.5)

# Conflicting inserts
with c3.cursor() as cur:
    cur.execute("INSERT INTO app_data (id, node_origin, message) OVERRIDING SYSTEM VALUE VALUES (66666, 'node3', 'from_3') ON CONFLICT DO NOTHING;")
with c2.cursor() as cur:
    cur.execute("INSERT INTO app_data (id, node_origin, message) OVERRIDING SYSTEM VALUE VALUES (66666, 'node2', 'from_2') ON CONFLICT DO NOTHING;")

# Re-enable subscription to force apply worker to process conflict
with c3.cursor() as cur:
    cur.execute("ALTER SUBSCRIPTION sub_pg_mm3_from_pg_mm2 ENABLE;")

time.sleep(2)

# Check subscription stats
with c3.cursor() as cur:
    cur.execute("SELECT subname, apply_error_count, sync_error_count FROM pg_stat_subscription_stats WHERE subname = 'sub_pg_mm3_from_pg_mm2';")
    print("pg_stat_subscription_stats on node 3:", cur.fetchall())

# Run collector
res = postgres_cluster.run({
    'nodes': '127.0.0.1:5451',
    'username': 'site24x7',
    'password': 'site24x7',
    'db': 'postgres',
    'address_map': 'pg-mm1:5432=127.0.0.1:5451,pg-mm2:5432=127.0.0.1:5452,pg-mm3:5432=127.0.0.1:5453'
})

print("\n--- Collector Results ---")
print("Cluster Health:", res.get("Cluster Health"))
print("Subscription Apply Errors:", res.get("Subscription Apply Errors"))
print("Subscription Conflicts:", res.get("Subscription Conflicts"))
print("Msg:", res.get("msg"))

# Reset/clean conflict rows
with c2.cursor() as cur:
    cur.execute("DELETE FROM app_data WHERE id IN (66666, 77777);")
with c3.cursor() as cur:
    cur.execute("DELETE FROM app_data WHERE id IN (66666, 77777);")
print("Conflict test completed successfully.")
