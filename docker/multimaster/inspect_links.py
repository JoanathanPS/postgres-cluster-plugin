#!/usr/bin/env python3
import psycopg2

def inspect_links():
    nodes = [
        ("pg-mm1", 5451),
        ("pg-mm2", 5452),
        ("pg-mm3", 5453)
    ]

    for name, port in nodes:
        print(f"\n--- Node {name} ({port}) ---")
        conn = psycopg2.connect(host="127.0.0.1", port=port, user="site24x7", password="site24x7", dbname="postgres")
        cur = conn.cursor()

        # 1. Subscriptions on this node (incoming links)
        cur.execute("""
            SELECT s.subname,
                   s.subenabled,
                   st.pid,
                   st.received_lsn,
                   st.latest_end_lsn,
                   ROUND(COALESCE(EXTRACT(EPOCH FROM (now() - st.last_msg_receipt_time)), 0)::numeric, 2) as receipt_delay,
                   COALESCE(stats.apply_error_count, 0) as apply_errors,
                   COALESCE(stats.sync_error_count, 0) as sync_errors
            FROM pg_subscription s
            LEFT JOIN pg_stat_subscription st ON s.oid = st.subid
            LEFT JOIN pg_stat_subscription_stats stats ON s.oid = stats.subid;
        """)
        subs = cur.fetchall()
        for r in subs:
            subname, enabled, pid, r_lsn, e_lsn, delay, a_err, s_err = r
            is_active = 1 if (enabled and pid and pid > 0) else 0
            state = "streaming" if is_active else ("disabled" if not enabled else "stopped")
            print(f"  Subscription {subname}: enabled={enabled}, pid={pid}, active={is_active}, state={state}, received_lsn={r_lsn}, delay_s={delay}, apply_err={a_err}, sync_err={s_err}")

        # 2. Replication slots on this node
        cur.execute("""
            SELECT slot_name, plugin, slot_type, active, confirmed_flush_lsn
            FROM pg_replication_slots;
        """)
        slots = cur.fetchall()
        for sl in slots:
            print(f"  Slot {sl[0]}: plugin={sl[1]}, type={sl[2]}, active={sl[3]}, flush_lsn={sl[4]}")

        # 3. Walsenders on this node (outgoing links)
        cur.execute("""
            SELECT application_name, client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn,
                   ROUND(COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn), 0)::numeric, 0) as replay_lag_bytes,
                   ROUND(COALESCE(EXTRACT(EPOCH FROM replay_lag), 0)::numeric, 2) as replay_lag_s
            FROM pg_stat_replication;
        """)
        ws = cur.fetchall()
        for w in ws:
            print(f"  Walsender {w[0]}: client={w[1]}, state={w[2]}, replay_lag_bytes={w[7]}, replay_lag_s={w[8]}")

        conn.close()

if __name__ == "__main__":
    inspect_links()
