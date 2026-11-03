#!/usr/bin/env python3
"""
Sets up PostgreSQL Active-Active Multi-Master Logical Replication between pg-mm1 and pg-mm2.
"""

import time
import subprocess
import psycopg2

def run_cmd(cmd, check=True):
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed ({res.returncode}): {' '.join(cmd)}\nStderr: {res.stderr}\nStdout: {res.stdout}")
    return res

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
    print("Waiting for both nodes to become ready...")
    wait_for_db(5451)
    wait_for_db(5452)

    # 1. Create table app_data on both nodes
    ddl_1 = """
    DROP TABLE IF EXISTS app_data CASCADE;
    CREATE TABLE app_data (
        id bigint GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 2) PRIMARY KEY,
        node_origin text NOT NULL,
        message text NOT NULL,
        created_at timestamp DEFAULT now()
    );
    """
    ddl_2 = """
    DROP TABLE IF EXISTS app_data CASCADE;
    CREATE TABLE app_data (
        id bigint GENERATED ALWAYS AS IDENTITY (START WITH 2 INCREMENT BY 2) PRIMARY KEY,
        node_origin text NOT NULL,
        message text NOT NULL,
        created_at timestamp DEFAULT now()
    );
    """
    conn1 = psycopg2.connect(host="127.0.0.1", port=5451, user="site24x7", password="site24x7", dbname="postgres")
    conn1.autocommit = True
    with conn1.cursor() as cur:
        cur.execute(ddl_1)
        cur.execute("SELECT count(*) FROM pg_publication WHERE pubname = 'pub_mm1';")
        if cur.fetchone()[0] == 0:
            cur.execute("CREATE PUBLICATION pub_mm1 FOR TABLE app_data;")
        else:
            cur.execute("ALTER PUBLICATION pub_mm1 SET TABLE app_data;")
    conn1.close()
    print("Configured schema and pub_mm1 on pg-mm1")

    conn2 = psycopg2.connect(host="127.0.0.1", port=5452, user="site24x7", password="site24x7", dbname="postgres")
    conn2.autocommit = True
    with conn2.cursor() as cur:
        cur.execute(ddl_2)
        cur.execute("SELECT count(*) FROM pg_publication WHERE pubname = 'pub_mm2';")
        if cur.fetchone()[0] == 0:
            cur.execute("CREATE PUBLICATION pub_mm2 FOR TABLE app_data;")
        else:
            cur.execute("ALTER PUBLICATION pub_mm2 SET TABLE app_data;")
    conn2.close()
    print("Configured schema and pub_mm2 on pg-mm2")

    # 2. Create subscriptions (using origin = 'none' to prevent replication loops in PG 16)
    conn1 = psycopg2.connect(host="127.0.0.1", port=5451, user="site24x7", password="site24x7", dbname="postgres")
    conn1.autocommit = True
    with conn1.cursor() as cur:
        # Check if sub exists
        cur.execute("SELECT count(*) FROM pg_subscription WHERE subname = 'sub_mm1';")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                CREATE SUBSCRIPTION sub_mm1 
                CONNECTION 'host=pg-mm2 port=5432 dbname=postgres user=site24x7 password=site24x7' 
                PUBLICATION pub_mm2 
                WITH (copy_data = false, origin = 'none');
            """)
            print("Created subscription sub_mm1 on pg-mm1")
    conn1.close()

    conn2 = psycopg2.connect(host="127.0.0.1", port=5452, user="site24x7", password="site24x7", dbname="postgres")
    conn2.autocommit = True
    with conn2.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_subscription WHERE subname = 'sub_mm2';")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                CREATE SUBSCRIPTION sub_mm2 
                CONNECTION 'host=pg-mm1 port=5432 dbname=postgres user=site24x7 password=site24x7' 
                PUBLICATION pub_mm1 
                WITH (copy_data = false, origin = 'none');
            """)
            print("Created subscription sub_mm2 on pg-mm2")
    conn2.close()

    print("Multi-Master logical replication successfully established!")

    # 3. Test bi-directional replication!
    time.sleep(2)
    conn1 = psycopg2.connect(host="127.0.0.1", port=5451, user="site24x7", password="site24x7", dbname="postgres")
    conn1.autocommit = True
    with conn1.cursor() as cur:
        cur.execute("INSERT INTO app_data (node_origin, message) VALUES ('pg-mm1', 'Hello from Node 1');")
    conn1.close()

    time.sleep(2)
    conn2 = psycopg2.connect(host="127.0.0.1", port=5452, user="site24x7", password="site24x7", dbname="postgres")
    conn2.autocommit = True
    with conn2.cursor() as cur:
        cur.execute("SELECT count(*) FROM app_data WHERE node_origin = 'pg-mm1';")
        cnt = cur.fetchone()[0]
        assert cnt > 0, "Replication from pg-mm1 to pg-mm2 failed!"
        print(f"Verified forward replication: pg-mm2 received row from pg-mm1 (count={cnt})")
        # Now insert on node 2
        cur.execute("INSERT INTO app_data (node_origin, message) VALUES ('pg-mm2', 'Hello from Node 2');")
    conn2.close()

    time.sleep(2)
    conn1 = psycopg2.connect(host="127.0.0.1", port=5451, user="site24x7", password="site24x7", dbname="postgres")
    conn1.autocommit = True
    with conn1.cursor() as cur:
        cur.execute("SELECT count(*) FROM app_data WHERE node_origin = 'pg-mm2';")
        cnt = cur.fetchone()[0]
        assert cnt > 0, "Replication from pg-mm2 to pg-mm1 failed!"
        print(f"Verified reverse replication: pg-mm1 received row from pg-mm2 (count={cnt})")
    conn1.close()

    print("\n[SUCCESS] Bi-directional Active-Active Multi-Master replication is FULLY WORKING!")

if __name__ == "__main__":
    setup_multimaster()
