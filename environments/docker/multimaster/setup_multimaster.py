#!/usr/bin/env python3
"""
Sets up PostgreSQL 17 Active-Active Multi-Master Logical Replication between 3 nodes:
pg-mm1 (5451), pg-mm2 (5452), pg-mm3 (5453).
Full mesh topology using origin = 'none' and copy_data = false.
"""

import time
import psycopg2

NODES = [
    {"name": "pg-mm1", "host": "127.0.0.1", "port": 5451, "docker_host": "pg-mm1", "id_start": 1},
    {"name": "pg-mm2", "host": "127.0.0.1", "port": 5452, "docker_host": "pg-mm2", "id_start": 2},
    {"name": "pg-mm3", "host": "127.0.0.1", "port": 5453, "docker_host": "pg-mm3", "id_start": 3},
]

def wait_for_db(port, max_retries=20):
    for i in range(max_retries):
        try:
            conn = psycopg2.connect(
                host="127.0.0.1",
                port=port,
                user="site24x7",
                password="site24x7",
                dbname="postgres",
                connect_timeout=2
            )
            conn.close()
            print(f"PostgreSQL on port {port} is ready!")
            return True
        except Exception:
            time.sleep(1)
    raise TimeoutError(f"PostgreSQL on port {port} not ready in {max_retries} seconds")

def setup_multimaster():
    print("Waiting for all 3 nodes to become ready...")
    for n in NODES:
        wait_for_db(n["port"])

    # 1. Create table app_data and publication on each node
    for n in NODES:
        ddl = f"""
        DROP TABLE IF EXISTS app_data CASCADE;
        CREATE TABLE app_data (
            id bigint GENERATED ALWAYS AS IDENTITY (START WITH {n['id_start']} INCREMENT BY 3) PRIMARY KEY,
            node_origin text NOT NULL,
            message text NOT NULL,
            created_at timestamp DEFAULT now()
        );
        """
        conn = psycopg2.connect(host="127.0.0.1", port=n["port"], user="site24x7", password="site24x7", dbname="postgres")
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(ddl)
            pubname = f"pub_{n['name'].replace('-', '_')}"
            cur.execute("SELECT count(*) FROM pg_publication WHERE pubname = %s;", (pubname,))
            if cur.fetchone()[0] == 0:
                cur.execute(f"CREATE PUBLICATION {pubname} FOR TABLE app_data;")
            else:
                cur.execute(f"ALTER PUBLICATION {pubname} SET TABLE app_data;")
        conn.close()
        print(f"Configured schema and {pubname} on {n['name']}")

    # 2. Create mesh subscriptions (using origin = 'none' to prevent replication loops)
    for n in NODES:
        conn = psycopg2.connect(host="127.0.0.1", port=n["port"], user="site24x7", password="site24x7", dbname="postgres")
        conn.autocommit = True
        with conn.cursor() as cur:
            for peer in NODES:
                if peer["name"] == n["name"]:
                    continue
                subname = f"sub_{n['name'].replace('-', '_')}_from_{peer['name'].replace('-', '_')}"
                pubname = f"pub_{peer['name'].replace('-', '_')}"
                conninfo = f"host={peer['docker_host']} port=5432 dbname=postgres user=site24x7 password=site24x7"

                cur.execute("SELECT count(*) FROM pg_subscription WHERE subname = %s;", (subname,))
                if cur.fetchone()[0] == 0:
                    cur.execute(f"""
                        CREATE SUBSCRIPTION {subname}
                        CONNECTION '{conninfo}'
                        PUBLICATION {pubname}
                        WITH (copy_data = false, origin = 'none');
                    """)
                    print(f"Created subscription {subname} on {n['name']} from {peer['name']}")
        conn.close()

    print("\nMulti-Master 3-node logical replication mesh established!")
    time.sleep(3)

    # 3. Test bi-directional replication across all 3 nodes
    print("\n--- Testing 3-Way Active-Active Replication ---")
    for n in NODES:
        conn = psycopg2.connect(host="127.0.0.1", port=n["port"], user="site24x7", password="site24x7", dbname="postgres")
        conn.autocommit = True
        with conn.cursor() as cur:
            msg = f"Hello from {n['name']}"
            cur.execute("INSERT INTO app_data (node_origin, message) VALUES (%s, %s);", (n['name'], msg))
        conn.close()
        print(f"Inserted row on {n['name']}")

    time.sleep(3)

    # Verify every node has all 3 rows
    for n in NODES:
        conn = psycopg2.connect(host="127.0.0.1", port=n["port"], user="site24x7", password="site24x7", dbname="postgres")
        with conn.cursor() as cur:
            cur.execute("SELECT node_origin, message FROM app_data ORDER BY id;")
            rows = cur.fetchall()
            print(f"\nRows seen by {n['name']} (total: {len(rows)}):")
            for r in rows:
                print(f"   [{n['name']}] origin: {r[0]}, message: {r[1]}")
            assert len(rows) == 3, f"{n['name']} only saw {len(rows)} rows, expected 3!"
        conn.close()

    print("\n[SUCCESS] 3-node Full-Mesh Active-Active Multi-Master replication is 100% VERIFIED!")

if __name__ == "__main__":
    setup_multimaster()
