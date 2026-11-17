#!/usr/bin/env python3
import psycopg2
import json

def inspect():
    conn = psycopg2.connect(host="127.0.0.1", port=5451, user="site24x7", password="site24x7", dbname="postgres")
    cur = conn.cursor()

    queries = {
        "pg_subscription columns": """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'pg_catalog' AND table_name = 'pg_subscription'
            ORDER BY ordinal_position;
        """,
        "pg_stat_subscription columns": """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'pg_stat_subscription'
            ORDER BY ordinal_position;
        """,
        "pg_stat_subscription_stats columns": """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'pg_stat_subscription_stats'
            ORDER BY ordinal_position;
        """,
        "pg_publication columns": """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'pg_catalog' AND table_name = 'pg_publication'
            ORDER BY ordinal_position;
        """,
        "pg_replication_slots columns": """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'pg_replication_slots'
            ORDER BY ordinal_position;
        """,
        "pg_stat_replication columns": """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'pg_stat_replication'
            ORDER BY ordinal_position;
        """,
        "pg_replication_origin_status columns": """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'pg_replication_origin_status'
            ORDER BY ordinal_position;
        """
    }

    for name, sql in queries.items():
        print(f"\n=== {name} ===")
        try:
            cur.execute(sql)
            rows = cur.fetchall()
            for col, dtype in rows:
                print(f"  {col}: {dtype}")
        except Exception as e:
            print(f"  Error: {e}")
            conn.rollback()

    # Now inspect sample data (safely mask passwords)
    print("\n=== Sample pg_subscription ===")
    cur.execute("SELECT oid, subname, subenabled, subconninfo, subpublications FROM pg_subscription;")
    for row in cur.fetchall():
        oid, subname, enabled, conninfo, pubs = row
        # Sanitize conninfo for display
        parts = [p for p in conninfo.split() if not p.startswith("password=")]
        print(f"  subname={subname}, enabled={enabled}, pubs={pubs}, conn={' '.join(parts)}")

    print("\n=== Sample pg_stat_subscription ===")
    cur.execute("SELECT subid, subname, pid, relid, received_lsn, last_msg_send_time, last_msg_receipt_time, latest_end_lsn FROM pg_stat_subscription;")
    for row in cur.fetchall():
        print(f"  {row}")

    print("\n=== Sample pg_stat_subscription_stats ===")
    cur.execute("SELECT * FROM pg_stat_subscription_stats;")
    for row in cur.fetchall():
        print(f"  {row}")

    print("\n=== Sample pg_replication_slots ===")
    cur.execute("SELECT slot_name, plugin, slot_type, active, confirmed_flush_lsn, wal_status FROM pg_replication_slots;")
    for row in cur.fetchall():
        print(f"  {row}")

    print("\n=== Sample pg_stat_replication ===")
    cur.execute("SELECT pid, application_name, client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn, write_lag, flush_lag, replay_lag FROM pg_stat_replication;")
    for row in cur.fetchall():
        print(f"  {row}")

    conn.close()

if __name__ == "__main__":
    inspect()
