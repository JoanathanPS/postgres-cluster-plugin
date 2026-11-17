#!/usr/bin/env python3
import psycopg2

def test_permissions():
    conn = psycopg2.connect(host="127.0.0.1", port=5451, user="site24x7", password="site24x7", dbname="postgres")
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("DROP USER IF EXISTS test_monitor;")
    cur.execute("CREATE USER test_monitor WITH PASSWORD 'secret';")
    cur.execute("GRANT pg_monitor TO test_monitor;")

    conn_test = psycopg2.connect(host="127.0.0.1", port=5451, user="test_monitor", password="secret", dbname="postgres")
    cur_test = conn_test.cursor()

    print("--- Testing pg_monitor access to stats views ---")
    try:
        cur_test.execute("SELECT subname, pid, received_lsn FROM pg_stat_subscription;")
        print("  pg_stat_subscription SUCCESS:", cur_test.fetchall())
    except Exception as e:
        print("  pg_stat_subscription FAILED:", e)
        conn_test.rollback()

    try:
        cur_test.execute("SELECT subname, apply_error_count, sync_error_count FROM pg_stat_subscription_stats;")
        print("  pg_stat_subscription_stats SUCCESS:", cur_test.fetchall())
    except Exception as e:
        print("  pg_stat_subscription_stats FAILED:", e)
        conn_test.rollback()

    try:
        cur_test.execute("SELECT slot_name, slot_type, active FROM pg_replication_slots;")
        print("  pg_replication_slots SUCCESS:", cur_test.fetchall())
    except Exception as e:
        print("  pg_replication_slots FAILED:", e)
        conn_test.rollback()

    try:
        cur_test.execute("SELECT pid, application_name, state FROM pg_stat_replication;")
        print("  pg_stat_replication SUCCESS:", cur_test.fetchall())
    except Exception as e:
        print("  pg_stat_replication FAILED:", e)
        conn_test.rollback()

    # Now what if we grant SELECT ON pg_subscription to test_monitor?
    try:
        cur.execute("GRANT SELECT ON pg_subscription TO test_monitor;")
        cur_test.execute("SELECT subname, subconninfo FROM pg_subscription;")
        rows = cur_test.fetchall()
        print("  pg_subscription WITH GRANT SELECT:", len(rows), "rows. Can see conninfo?", bool(rows[0][1]))
    except Exception as e:
        print("  GRANT SELECT ON pg_subscription failed or subconninfo masked:", e)
        conn_test.rollback()

    conn_test.close()
    cur.execute("DROP USER test_monitor;")
    conn.close()

if __name__ == "__main__":
    test_permissions()
