"""
Continuous PostgreSQL Workload & Stress Traffic Generator
Runs realistic multi-threaded workload against 127.0.0.1:5432 and 127.0.0.1:5441.
Uses application superuser to generate traffic while leaving monitoring user slots open.
"""

import sys
import time
import random
import threading
import psycopg2

TARGETS = [
    {
        "host": "127.0.0.1",
        "port": 5432,
        "user": "postgres",
        "password": "site24x7_admin",
        "dbname": "postgres",
        "name": "cluster-primary-5432"
    },
    {
        "host": "127.0.0.1",
        "port": 5441,
        "user": "postgres",
        "password": "postgres_password",
        "dbname": "postgres",
        "name": "patroni-leader-5441"
    }
]

STOP_EVENT = threading.Event()
STATS = {
    "inserts": 0,
    "updates": 0,
    "deletes": 0,
    "commits": 0,
    "rollbacks": 0,
    "queries": 0,
}
STATS_LOCK = threading.Lock()


def get_conn(target):
    return psycopg2.connect(
        host=target["host"],
        port=target["port"],
        user=target["user"],
        password=target["password"],
        dbname=target["dbname"],
        connect_timeout=3
    )


def setup_tables():
    for target in TARGETS:
        try:
            with get_conn(target) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS stress_accounts (
                            id SERIAL PRIMARY KEY,
                            username VARCHAR(64) NOT NULL,
                            balance NUMERIC(12, 2) NOT NULL DEFAULT 1000.00,
                            payload TEXT,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                        CREATE INDEX IF NOT EXISTS idx_stress_acc_user ON stress_accounts(username);
                        CREATE TABLE IF NOT EXISTS stress_audit_log (
                            id SERIAL PRIMARY KEY,
                            account_id INT,
                            action VARCHAR(32),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                conn.commit()
            print(f"[+] Initialized stress tables on {target['name']}", flush=True)
        except Exception as e:
            print(f"[-] Setup failed on {target['name']}: {e}", flush=True)


def worker_inserts_and_updates(target):
    """Generates continuous INSERT, UPDATE, and DELETE activity."""
    conn = None
    while not STOP_EVENT.is_set():
        try:
            if not conn or conn.closed:
                conn = get_conn(target)
                conn.autocommit = False
            cur = conn.cursor()
            while not STOP_EVENT.is_set():
                # Bulk insert 20 rows
                rows = [(f"user_{random.randint(1, 50000)}", round(random.uniform(10, 5000), 2), "payload_data_" * 10) for _ in range(20)]
                cur.executemany("INSERT INTO stress_accounts (username, balance, payload) VALUES (%s, %s, %s)", rows)

                # Update 10 rows
                cur.execute("UPDATE stress_accounts SET balance = balance + 1.25, updated_at = NOW() WHERE id IN (SELECT id FROM stress_accounts ORDER BY RANDOM() LIMIT 10)")

                # Delete 5 rows to generate dead tuples (for autovacuum metrics)
                cur.execute("DELETE FROM stress_accounts WHERE id IN (SELECT id FROM stress_accounts ORDER BY id ASC LIMIT 5)")

                conn.commit()
                with STATS_LOCK:
                    STATS["inserts"] += 20
                    STATS["updates"] += 10
                    STATS["deletes"] += 5
                    STATS["commits"] += 1
                time.sleep(0.08)
        except Exception as e:
            if conn and not conn.closed:
                conn.close()
            time.sleep(1)


def worker_queries_and_rollbacks(target):
    """Generates continuous SELECT queries and periodic deliberate ROLLBACKs."""
    conn = None
    while not STOP_EVENT.is_set():
        try:
            if not conn or conn.closed:
                conn = get_conn(target)
                conn.autocommit = False
            cur = conn.cursor()
            while not STOP_EVENT.is_set():
                # Complex read with aggregates and joins
                cur.execute("""
                    SELECT count(*), avg(balance), max(balance), min(balance)
                    FROM stress_accounts
                    WHERE balance > %s
                """, (random.uniform(50, 1000),))
                cur.fetchall()

                # Audit log write
                cur.execute("INSERT INTO stress_audit_log (account_id, action) VALUES (%s, %s)", (random.randint(1, 1000), "CHECK"))

                if random.random() < 0.2:
                    # Deliberate rollback (20% of the time)
                    conn.rollback()
                    with STATS_LOCK:
                        STATS["rollbacks"] += 1
                        STATS["queries"] += 1
                else:
                    conn.commit()
                    with STATS_LOCK:
                        STATS["commits"] += 1
                        STATS["queries"] += 1
                time.sleep(0.05)
        except Exception:
            if conn and not conn.closed:
                conn.close()
            time.sleep(1)


def worker_idle_transactions(target):
    """Holds open transactions for 2-3 seconds to trigger idle-in-transaction metrics."""
    conn = None
    while not STOP_EVENT.is_set():
        try:
            if not conn or conn.closed:
                conn = get_conn(target)
                conn.autocommit = False
            cur = conn.cursor()
            while not STOP_EVENT.is_set():
                cur.execute("BEGIN;")
                cur.execute("SELECT id, username, balance FROM stress_accounts ORDER BY id DESC LIMIT 3 FOR UPDATE;")
                cur.fetchall()
                time.sleep(2.5)  # Idle in transaction
                conn.commit()
                with STATS_LOCK:
                    STATS["commits"] += 1
                time.sleep(1.0)
        except Exception:
            if conn and not conn.closed:
                conn.close()
            time.sleep(2)


def main():
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    print("=" * 65, flush=True)
    print("   PostgreSQL Cluster Traffic & Stress Generator Running", flush=True)
    print(f"   Targets: 127.0.0.1:5432 and 127.0.0.1:5441", flush=True)
    print(f"   Duration: {duration} seconds (10 minutes)", flush=True)
    print("=" * 65, flush=True)

    setup_tables()

    threads = []
    for target in TARGETS:
        t1 = threading.Thread(target=worker_inserts_and_updates, args=(target,), daemon=True)
        t2 = threading.Thread(target=worker_queries_and_rollbacks, args=(target,), daemon=True)
        t3 = threading.Thread(target=worker_idle_transactions, args=(target,), daemon=True)
        threads.extend([t1, t2, t3])

    for t in threads:
        t.start()

    start_time = time.time()
    try:
        while time.time() - start_time < duration:
            time.sleep(3)
            elapsed = int(time.time() - start_time)
            with STATS_LOCK:
                print(f"[{elapsed:03d}s] Commits: {STATS['commits']} | Rollbacks: {STATS['rollbacks']} | Inserts: {STATS['inserts']} | Updates: {STATS['updates']} | Queries: {STATS['reads'] if 'reads' in STATS else STATS['queries']}", flush=True)
    except KeyboardInterrupt:
        print("\nStopping traffic generator...", flush=True)
    finally:
        STOP_EVENT.set()
        time.sleep(1)
        print("=" * 65, flush=True)
        print(f"[✓] Traffic Finished! Commits: {STATS['commits']} | Rollbacks: {STATS['rollbacks']} | Inserts: {STATS['inserts']}", flush=True)
        print("=" * 65, flush=True)


if __name__ == "__main__":
    main()
