"""
Workload Controller for PostgreSQL Audit.
Manages controlled workloads to verify exact metrics against live PostgreSQL instances:
- 5 client connections (2 idle, 2 active, 1 idle in transaction)
- Lock blocking scenario (1 blocker, 1 blocked session)
- Collects direct PostgreSQL truth query results.
"""

import threading
import time
import psycopg2


class WorkloadManager:
    def __init__(self, host="127.0.0.1", port=5450, user="site24x7", password="site24x7", dbname="audit_test_db"):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.dbname = dbname
        self.connections = []
        self.threads = []
        self.stop_event = threading.Event()

    def connect(self, app_name="test_worker"):
        conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=self.dbname,
            application_name=app_name,
            connect_timeout=3
        )
        self.connections.append(conn)
        return conn

    def setup_5_connection_workload(self):
        """
        Creates exactly 5 client connections on dbname:
        - 2 idle connections
        - 2 active connections running pg_sleep
        - 1 idle in transaction connection
        """
        self.stop_event.clear()

        # 1 & 2: Idle connections
        c_idle1 = self.connect(app_name="audit_idle_1")
        c_idle2 = self.connect(app_name="audit_idle_2")
        # Run a quick query so they are established and idle
        with c_idle1.cursor() as cur:
            cur.execute("SELECT 1;")
        with c_idle2.cursor() as cur:
            cur.execute("SELECT 1;")

        # 3: Idle in transaction
        c_idletxn = self.connect(app_name="audit_idle_in_txn")
        cur_txn = c_idletxn.cursor()
        cur_txn.execute("BEGIN; SELECT 1;")

        # 4 & 5: Active queries running in background threads
        def run_active_loop(app_name):
            while not self.stop_event.is_set():
                try:
                    c = psycopg2.connect(
                        host=self.host, port=self.port, user=self.user,
                        password=self.password, dbname=self.dbname,
                        application_name=app_name, connect_timeout=3
                    )
                    self.connections.append(c)
                    with c.cursor() as cur:
                        while not self.stop_event.is_set():
                            cur.execute("SELECT pg_sleep(0.5);")
                except Exception as e:
                    break

        t1 = threading.Thread(target=run_active_loop, args=("audit_active_1",), daemon=True)
        t2 = threading.Thread(target=run_active_loop, args=("audit_active_2",), daemon=True)
        t1.start()
        t2.start()
        self.threads.extend([t1, t2])
        time.sleep(1.0)

    def setup_lock_blocking_workload(self):
        """
        Sets up table and 2 sessions:
        - Session 1 (Blocker): Holds row exclusive lock inside transaction
        - Session 2 (Blocked): Waiting on row exclusive lock
        """
        # Create table as admin
        admin_conn = psycopg2.connect(
            host=self.host, port=self.port, user="postgres",
            password=self.password, dbname=self.dbname
        )
        admin_conn.autocommit = True
        with admin_conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS audit_lock_test;")
            cur.execute("CREATE TABLE audit_lock_test (id int primary key, val text);")
            cur.execute("INSERT INTO audit_lock_test VALUES (1, 'initial');")
            cur.execute("GRANT ALL ON audit_lock_test TO site24x7;")
        admin_conn.close()

        # Session 1: Blocker
        c_blocker = self.connect(app_name="audit_blocker")
        cur_b = c_blocker.cursor()
        cur_b.execute("BEGIN; UPDATE audit_lock_test SET val = 'locked' WHERE id = 1;")

        # Session 2: Blocked in background thread
        def run_blocked():
            try:
                c_blocked = psycopg2.connect(
                    host=self.host, port=self.port, user=self.user,
                    password=self.password, dbname=self.dbname,
                    application_name="audit_blocked", connect_timeout=3
                )
                self.connections.append(c_blocked)
                with c_blocked.cursor() as cur:
                    cur.execute("UPDATE audit_lock_test SET val = 'blocked' WHERE id = 1;")
            except Exception:
                pass

        t_blocked = threading.Thread(target=run_blocked, daemon=True)
        t_blocked.start()
        self.threads.append(t_blocked)
        time.sleep(1.0)

    def measure_direct_postgres(self):
        """Queries pg_stat_activity to obtain the authoritative PostgreSQL measurement."""
        meas_conn = psycopg2.connect(
            host=self.host, port=self.port, user="postgres",
            password=self.password, dbname=self.dbname
        )
        meas_conn.autocommit = True
        with meas_conn.cursor() as cur:
            # All backends in pg_stat_activity
            cur.execute("""
                SELECT
                    count(*) as total_rows,
                    count(*) FILTER (WHERE backend_type = 'client backend') as client_backends,
                    count(*) FILTER (WHERE datname = %s AND backend_type = 'client backend') as db_client_backends,
                    count(*) FILTER (WHERE datname = %s AND state = 'active' AND pid <> pg_backend_pid()) as db_active_queries,
                    count(*) FILTER (WHERE datname = %s AND state = 'idle') as db_idle_sessions,
                    count(*) FILTER (WHERE datname = %s AND state LIKE 'idle in transaction%%') as db_idle_in_txn,
                    count(*) FILTER (WHERE datname = %s AND cardinality(pg_blocking_pids(pid)) > 0) as db_blocked_sessions
                FROM pg_stat_activity;
            """, (self.dbname, self.dbname, self.dbname, self.dbname, self.dbname))
            row = cur.fetchone()

            # Global numbackends from pg_stat_database
            cur.execute("SELECT sum(numbackends) FROM pg_stat_database;")
            sum_numbackends = cur.fetchone()[0]

            # Specific database numbackends
            cur.execute("SELECT numbackends FROM pg_stat_database WHERE datname = %s;", (self.dbname,))
            db_numbackends = cur.fetchone()[0]

            # Wait events
            cur.execute("""
                SELECT coalesce(wait_event_type, 'CPU') as event_type,
                       coalesce(wait_event, 'running') as event,
                       count(*) as count
                FROM pg_stat_activity
                WHERE backend_type = 'client backend' AND pid <> pg_backend_pid()
                GROUP BY 1, 2
                ORDER BY count DESC;
            """)
            wait_events = cur.fetchall()

        meas_conn.close()
        return {
            "total_pg_stat_activity_rows": row[0],
            "global_client_backends": row[1],
            "db_client_backends": row[2],
            "db_active_queries": row[3],
            "db_idle_sessions": row[4],
            "db_idle_in_txn": row[5],
            "db_blocked_sessions": row[6],
            "global_numbackends": sum_numbackends,
            "db_numbackends": db_numbackends,
            "wait_events": wait_events
        }

    def cleanup(self):
        self.stop_event.set()
        for c in self.connections:
            try:
                c.close()
            except Exception:
                pass
        self.connections.clear()
        time.sleep(0.5)


if __name__ == "__main__":
    wm = WorkloadManager(port=5450)
    print("Setting up 5-connection workload...")
    wm.setup_5_connection_workload()
    m = wm.measure_direct_postgres()
    print("PostgreSQL Truth Measurements (5-conn workload):")
    for k, v in m.items():
        print(f"  {k}: {v}")
    wm.cleanup()
    print("Cleaned up.")
