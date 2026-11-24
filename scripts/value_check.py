#!/usr/bin/env python3
"""
Known-condition value test: creates conditions on a real PostgreSQL server and
checks that each plugin metric reports exactly what was created.

Needs a superuser connection to set up the conditions, and runs the plugin itself
as the monitoring user. Destructive only inside its own objects (database
`vc_db`, table `vc_t`, slot `vc_slot`), which it drops at the end.

Usage:
  python scripts/value_check.py --host 127.0.0.1 --port 5450 --super postgres:site24x7 \
      --monitor site24x7:site24x7
  python scripts/value_check.py ... --standby-port 5433     # also checks replay lag
"""

import argparse
import os
import sys
import threading
import time

import psycopg2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "postgres"))
import postgres as pg  # noqa: E402

RESULTS = []


def check(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print("%-4s %-36s %s" % ("PASS" if ok else "FAIL", name, detail))


def conn(args, user_pw, db="postgres", port=None, autocommit=True):
    user, pw = user_pw.split(":", 1)
    c = psycopg2.connect(host=args.host, port=port or args.port, user=user, password=pw, dbname=db)
    c.autocommit = autocommit
    return c


def q(c, sql):
    cur = c.cursor()
    cur.execute(sql)
    try:
        return cur.fetchall()
    except psycopg2.ProgrammingError:
        return None


def plugin(args, port=None, state_dir=None):
    user, pw = args.monitor.split(":", 1)
    return pg.run({"host": args.host, "port": str(port or args.port), "username": user,
                   "password": pw, "db": "postgres"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", default="5450")
    ap.add_argument("--super", required=True, help="user:password of a superuser")
    ap.add_argument("--monitor", required=True, help="user:password of the monitoring user")
    ap.add_argument("--standby-port", default="")
    args = ap.parse_args()

    su = conn(args, args.super)
    q(su, "DROP DATABASE IF EXISTS vc_db")
    q(su, "SELECT pg_drop_replication_slot('vc_slot') FROM pg_replication_slots WHERE slot_name = 'vc_slot'")
    q(su, "DROP TABLE IF EXISTS vc_t")
    q(su, "CREATE TABLE vc_t (id int PRIMARY KEY, v int) WITH (autovacuum_enabled = false)")
    q(su, "INSERT INTO vc_t SELECT g, 0 FROM generate_series(1, 1000) g")
    q(su, "ANALYZE vc_t")

    base = plugin(args)                       # first poll (also sets the rate baseline)
    time.sleep(1)

    # --- conditions -------------------------------------------------------------
    q(su, "CREATE DATABASE vc_db")
    q(su, "SELECT pg_create_physical_replication_slot('vc_slot', true)")   # never used: inactive
    q(su, "UPDATE vc_t SET v = 1")                                        # 1000 dead tuples
    for _ in range(5):                                                    # 5 rollbacks
        c = conn(args, args.super, autocommit=False)
        q(c, "INSERT INTO vc_t VALUES (-1, 0)")
        c.rollback()
        c.close()
    t = conn(args, args.super, autocommit=False)                          # temp file
    q(t, "SET work_mem = '64kB'")
    q(t, "SELECT * FROM generate_series(1, 200000) g ORDER BY g DESC")
    t.commit()
    t.close()

    # deadlock between two sessions
    a, b = conn(args, args.super, autocommit=False), conn(args, args.super, autocommit=False)
    q(a, "UPDATE vc_t SET v = 2 WHERE id = 1")
    q(b, "UPDATE vc_t SET v = 2 WHERE id = 2")
    errs = []

    def lock(c, sql):
        try:
            q(c, sql)
        except psycopg2.Error as e:
            errs.append(e.pgcode)
    th = threading.Thread(target=lock, args=(a, "UPDATE vc_t SET v = 3 WHERE id = 2"))
    th.start()
    time.sleep(0.5)
    lock(b, "UPDATE vc_t SET v = 3 WHERE id = 1")
    th.join()
    a.rollback(); b.rollback(); a.close(); b.close()

    # idle-in-transaction holder + a blocked waiter, kept open during the poll
    holder = conn(args, args.super, autocommit=False)
    q(holder, "LOCK TABLE vc_t IN ACCESS EXCLUSIVE MODE")
    waiter = conn(args, args.super, autocommit=False)
    wthread = threading.Thread(target=lock, args=(waiter, "SELECT count(*) FROM vc_t"))
    wthread.start()
    time.sleep(3)

    d = plugin(args)
    truth = conn(args, args.super)

    # --- checks ---------------------------------------------------------------------
    check("Transactions Idle In Transaction", d.get("Transactions Idle In Transaction", 0) >= 1,
          "got %s, expected >= 1 (the lock holder)" % d.get("Transactions Idle In Transaction"))
    check("Blocked Sessions", d.get("Blocked Sessions") == 1,
          "got %s, expected 1 (the waiter)" % d.get("Blocked Sessions"))
    check("Waiting Locks", d.get("Waiting Locks", 0) >= 1, "got %s, expected >= 1" % d.get("Waiting Locks"))
    check("Active Waiting Queries", d.get("Active Waiting Queries", 0) >= 1,
          "got %s, expected >= 1" % d.get("Active Waiting Queries"))
    check("Longest Transaction", d.get("Longest Transaction", 0) >= 3,
          "got %s s, expected >= 3 s" % d.get("Longest Transaction"))
    check("Deadlock happened (setup)", "40P01" in errs, "pgcodes %s" % errs)
    check("New Deadlocks", d.get("New Deadlocks") == 1, "got %s, expected 1" % d.get("New Deadlocks"))
    check("Total Deadlocks", d.get("Total Deadlocks", 0) - base.get("Total Deadlocks", 0) == 1,
          "delta %s, expected 1" % (d.get("Total Deadlocks", 0) - base.get("Total Deadlocks", 0)))
    rb = d.get("Total Rollbacks", 0) - base.get("Total Rollbacks", 0)
    check("Total Rollbacks", rb >= 5, "delta %s, expected >= 5 (5 rollbacks + deadlock victims)" % rb)
    # PostgreSQL prunes dead rows on the fly (HOT), so compare with its own counter
    dead = q(truth, "SELECT coalesce(sum(n_dead_tup), 0) FROM pg_stat_user_tables")[0][0]
    check("Dead Tuples", abs(d.get("Dead Tuples", -1) - dead) <= 5,
          "got %s, server counter %s" % (d.get("Dead Tuples"), dead))
    tf = d.get("Total Temp Files", 0) - base.get("Total Temp Files", 0)
    check("Total Temp Files", tf >= 1, "delta %s, expected >= 1" % tf)
    dbc = q(truth, "SELECT count(*) FROM pg_database WHERE datname NOT IN ('template0','template1')")[0][0]
    check("Database Count", d.get("Database Count") == dbc, "got %s, server says %s" % (d.get("Database Count"), dbc))
    check("Stats_per_DB has vc_db", any(r["name"] == "vc_db" for r in d.get("Stats_per_DB", [])), "")
    slots = q(truth, "SELECT count(*), count(*) FILTER (WHERE NOT active) FROM pg_replication_slots")[0]
    check("Replication Slots", d.get("Replication Slots") == slots[0], "got %s, server %s" % (d.get("Replication Slots"), slots[0]))
    check("Inactive Replication Slots", d.get("Inactive Replication Slots") == slots[1],
          "got %s, server %s" % (d.get("Inactive Replication Slots"), slots[1]))
    check("Replication_Slots has vc_slot", any(r["name"] == "vc_slot" and r.get("active") == 0
                                                 for r in d.get("Replication_Slots", [])), "")
    mc = int(q(truth, "SHOW max_connections")[0][0])
    check("Max Connections", d.get("Max Connections") == mc, "got %s, server %s" % (d.get("Max Connections"), mc))
    up = q(truth, "SELECT extract(epoch FROM now() - pg_postmaster_start_time())")[0][0]
    check("Uptime", abs(d.get("Uptime", -999) - float(up)) < 15, "got %s, server %.0f" % (d.get("Uptime"), up))
    ver = q(truth, "SHOW server_version")[0][0]
    check("Server Version", d.get("Server Version") == ver, "got %s" % d.get("Server Version"))
    size = q(truth, "SELECT round(sum(pg_database_size(oid)) / 1048576.0, 2) FROM pg_database WHERE datallowconn")[0][0]
    check("Total Database Size", abs(d.get("Total Database Size", 0) - float(size)) < 2,
          "got %s MB, server %s MB" % (d.get("Total Database Size"), size))
    xid = q(truth, "SELECT max(age(datfrozenxid)) FROM pg_database WHERE datallowconn")[0][0]
    check("Max XID Age", abs(d.get("Max XID Age", -1) - xid) < 50, "got %s, server %s" % (d.get("Max XID Age"), xid))
    conns = q(truth, "SELECT sum(numbackends) FROM pg_stat_database")[0][0]
    check("Active Connections", abs(d.get("Active Connections", -99) - conns) <= 2,
          "got %s, server %s" % (d.get("Active Connections"), conns))
    exp_util = round(100.0 * d.get("Active Connections", 0) / max(d.get("Max Connections", 1), 1), 2)
    check("Connection Utilization", d.get("Connection Utilization") == exp_util,
          "got %s, expected %s" % (d.get("Connection Utilization"), exp_util))
    check("Health/status", d.get("status") == 1 and pg.validate_output(d) == [], "violations %s" % pg.validate_output(d))

    holder.rollback(); holder.close(); wthread.join(); waiter.rollback(); waiter.close()

    if args.standby_port:
        prim = su
        sb = conn(args, args.super, port=args.standby_port)
        q(sb, "SELECT pg_wal_replay_pause()")
        q(prim, "INSERT INTO vc_t SELECT g, 0 FROM generate_series(1001, 60000) g")
        time.sleep(4)
        ds = plugin(args, port=args.standby_port)
        dp = plugin(args)
        check("Standby: Replay Lag", ds.get("Replay Lag", 0) >= 3, "got %s s with replay paused 4 s" % ds.get("Replay Lag"))
        check("Standby: Replay Backlog", ds.get("Replay Backlog", 0) > 0, "got %s MB" % ds.get("Replay Backlog"))
        check("Standby: WAL Receiver Connected", ds.get("WAL Receiver Connected") == 1, "got %s" % ds.get("WAL Receiver Connected"))
        check("Primary: Max Standby Backlog", dp.get("Max Standby Backlog", 0) > 0,
              "got %s MB (primary's view of the paused standby)" % dp.get("Max Standby Backlog"))
        q(sb, "SELECT pg_wal_replay_resume()")
        time.sleep(3)
        ds2 = plugin(args, port=args.standby_port)
        check("Standby: lag clears after resume", ds2.get("Replay Lag", 99) <= 1 and ds2.get("Replay Backlog", 99) == 0,
              "lag %s s, backlog %s MB" % (ds2.get("Replay Lag"), ds2.get("Replay Backlog")))
        sb.close()

    # cleanup
    q(su, "SELECT pg_drop_replication_slot('vc_slot')")
    q(su, "DROP TABLE vc_t")
    q(su, "DROP DATABASE vc_db")
    su.close()
    bad = [r for r in RESULTS if not r[1]]
    print("\n%d checks, %d failed" % (len(RESULTS), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
