#!/usr/bin/python3

### This plugin is used for monitoring PostgreSQL Cluster
### Monitors multiple nodes, detects primary/standby roles, health, replication lag,
### replication slots, and collects PostgreSQL performance metrics against the active primary node.
###
### Language : Python
### Compatible with Site24x7 Linux and Windows Agents.

import json
import time
import traceback
from collections import OrderedDict

# Default cluster configuration
NODES = '127.0.0.1:5441:8001,127.0.0.1:5442:8002,127.0.0.1:5443:8003'  # host:port or host:port:patroni_port
USERNAME = 'site24x7'                                                    # Monitoring username
PASSWORD = 'site24x7'                                                    # Monitoring password
DB = 'postgres'                                                          # Database name to connect to
PATRONI_PORT = '8008'                                                    # Optional Patroni REST API port or mapping
CONNECT_TIMEOUT = 2                                                      # Timeout for connecting to each node (seconds)
STATEMENT_TIMEOUT_MS = 5000                                              # Per-query statement timeout in PostgreSQL (ms)

PLUGIN_VERSION = 6
HEARTBEAT = True

VERSION = None

tabs = {
    "tabs": {
        "Cluster": {
            "order": "1",
            "tablist": [
                "Cluster_Nodes",
                "Replication_Standbys",
                "Nodes Total",
                "Nodes Up",
                "Primary Count",
                "No Primary Flag",
                "Split Brain Flag",
                "Primary Timeline",
                "Max Replay Backlog",
                "Replication Slots Total",
                "Replication Slots Active",
                "Replication Slots Inactive",
                "Physical Slots",
                "Logical Slots",
                "Max Slot Lag Bytes"
            ]
        },
        "DB and IO stats": {
            "order": "2",
            "tablist": [
                "Stats_per_DB",
                "Cache Hit Ratio",
                "Dead Tuples",
                "Total Rows Deleted",
                "Total Rows Fetched",
                "Total Rows Inserted",
                "Total Rows Returned",
                "Total Rows Updated",
                "Total Block Hits",
                "Total Block Reads"
            ]
        },
        "BG Writer": {
            "order": "3",
            "tablist": [
                "Checkpoints Timed",
                "Checkpoints Req",
                "Checkpoint Write Time",
                "Checkpoint Sync Time",
                "Buffers Checkpoint",
                "Buffers Clean",
                "Maxwritten Clean",
                "Buffers Backend",
                "Buffers Backend Fsync",
                "Buffers Alloc"
            ]
        },
        "Transactions and Sessions": {
            "order": "4",
            "tablist": [
                "Tranasctions_and_Session_per_Database",
                "Oldest Transaction ID Age",
                "Total Commits",
                "Total Rollbacks",
                "Total Conflicts",
                "Total Sessions",
                "Total Sessions Abandoned",
                "Total Sessions Fatal",
                "Total Sessions Killed",
                "Transactions Idle In Transaction",
                "Transactions Open"
            ]
        },
        "Write Ahead Log": {
            "order": "5",
            "tablist": [
                "WAL Write Position",
                "WAL Insert Position",
                "WAL Flush Position",
                "WAL Files Count",
                "WAL Total Size",
                "Archive Status Success",
                "Archive Status Failed",
                "Archive Ready Files Count"
            ]
        },
        "Recovery Conflicts": {
            "order": "6",
            "tablist": [
                "Recovery Conflicts Total",
                "Conflicts Tablespace",
                "Conflicts Lock",
                "Conflicts Snapshot",
                "Conflicts Buffer Pin",
                "Conflicts Deadlock",
                "Oldest Running Transaction Age",
                "Available Connections",
                "Connection Utilization Percent"
            ]
        }
    }
}

units = {
    "Nodes Total": "nodes",
    "Nodes Up": "nodes",
    "Primary Count": "nodes",
    "No Primary Flag": "flag",
    "Split Brain Flag": "flag",
    "Primary Timeline": "timeline",
    "Max Replay Backlog": "bytes",
    "Replication Slots Total": "slots",
    "Replication Slots Active": "slots",
    "Replication Slots Inactive": "slots",
    "Physical Slots": "slots",
    "Logical Slots": "slots",
    "Max Slot Lag Bytes": "bytes",
    "Active Connections": "connections",
    "Available Connections": "connections",
    "Connection Utilization Percent": "%",
    "Max Connections": "connections",
    "Uptime": "s",
    "Total Rows Deleted": "rows",
    "Total Rows Fetched": "rows",
    "Total Rows Inserted": "rows",
    "Total Rows Returned": "rows",
    "Total Rows Updated": "rows",
    "Cache Hit Ratio": "%",
    "Dead Tuples": "tuples",
    "Oldest Transaction ID Age": "xids",
    "Total Commits": "transactions",
    "Total Rollbacks": "transactions",
    "Total Sessions": "sessions",
    "Total Sessions Abandoned": "sessions",
    "Total Sessions Fatal": "sessions",
    "Total Sessions Killed": "sessions",
    "Transactions Idle In Transaction": "transactions",
    "Transactions Open": "transactions",
    "Locks Count": "locks",
    "Database Count": "databases",
    "WAL Write Position": "MB",
    "WAL Insert Position": "MB",
    "WAL Flush Position": "MB",
    "WAL Files Count": "files",
    "WAL Total Size": "MB",
    "Archive Status Success": "files",
    "Archive Status Failed": "files",
    "Archive Ready Files Count": "files",
    "Recovery Conflicts Total": "conflicts",
    "Conflicts Tablespace": "conflicts",
    "Conflicts Lock": "conflicts",
    "Conflicts Snapshot": "conflicts",
    "Conflicts Buffer Pin": "conflicts",
    "Conflicts Deadlock": "conflicts",
    "Oldest Running Transaction Age": "s",
    "Cluster_Nodes": {
        "response_time_ms": "ms",
        "replay_backlog_bytes": "bytes",
        "replay_delay_s": "s",
        "connections": "connections"
    },
    "Replication_Standbys": {
        "replay_lag_bytes": "bytes",
        "write_lag_bytes": "bytes",
        "flush_lag_bytes": "bytes"
    }
}

dict_psqlQueries = OrderedDict({})
conn_details = ""
db_details = ""


def inititializeQueries():
    global dict_psqlQueries, conn_details, db_details
    major_version = int(VERSION % 1000000 / 10000)
    middle_version = int(VERSION % 10000 / 100)

    waiting = True
    str_tableStat = "SELECT COUNT(*) AS table_count FROM pg_stat_all_tables;"
    str_TransactionsOpen = "SELECT count(*) as transactions_open FROM pg_stat_activity WHERE xact_start IS NOT NULL;"
    str_version = "SHOW server_version;"

    if (major_version >= 9 and middle_version >= 2) or (major_version >= 10):
        str_usageActiveStat = "SELECT count(*) - ( SELECT count(*) FROM pg_stat_activity WHERE state = 'idle' ) as active_queries FROM pg_stat_activity;"
        str_usageWaitingStat = "SELECT count(*) as active_waiting_queries FROM pg_stat_activity WHERE state = 'active' AND wait_event IS NOT NULL;"
        str_TransactionsIdle = "SELECT COUNT(*) as transactions_idle_in_transaction FROM pg_stat_activity WHERE state = 'idle in transaction';"
    else:
        str_usageActiveStat = "SELECT count(*) - ( SELECT count(*) FROM pg_stat_activity WHERE current_query = '<IDLE>' ) as active_queries FROM pg_stat_activity;"
        str_TransactionsIdle = "SELECT COUNT(*) as transactions_idle_in_transaction FROM pg_stat_activity WHERE state = '<IDLE> in transaction';"
        waiting = False

    str_lockStat = "SELECT COUNT(*) as locks_count FROM pg_locks;"
    str_MaxConn = "select setting::int max_connections from pg_settings where name=$$max_connections$$;"
    str_dbStats = "SELECT sum(numbackends) as active_connections, sum(xact_commit) as total_commits, sum(xact_rollback) as total_rollbacks, sum(conflicts) as total_conflicts FROM pg_stat_database;"

    str_iostats = "SELECT sum(tup_inserted) as total_rows_inserted, sum(tup_updated) as total_rows_updated ,sum(tup_deleted) as total_rows_deleted, sum(tup_fetched) as total_rows_fetched ,sum(tup_returned) as total_rows_returned,sum(blks_read) as total_block_reads , sum(blks_hit) as total_block_hits FROM pg_stat_database;"

    if major_version >= 17:
        str_bgStats = "SELECT c.num_timed AS checkpoints_timed, c.num_requested AS checkpoints_req, c.write_time AS checkpoint_write_time, c.sync_time AS checkpoint_sync_time, c.buffers_written AS buffers_checkpoint, b.buffers_clean, b.maxwritten_clean, b.buffers_alloc FROM pg_stat_checkpointer c, pg_stat_bgwriter b;"
    else:
        str_bgStats = "SELECT checkpoints_timed,checkpoints_req,checkpoint_write_time,checkpoint_sync_time,buffers_checkpoint,buffers_clean,maxwritten_clean,buffers_backend,buffers_backend_fsync,buffers_alloc FROM pg_stat_bgwriter;"

    str_idxStats = "SELECT sum(idx_scan) as index_scans,sum(idx_tup_read) as index_rows_read, sum(idx_tup_fetch) as index_rows_fetched FROM pg_stat_user_indexes;"
    str_uptime = "SELECT FLOOR(EXTRACT(EPOCH FROM current_timestamp - pg_postmaster_start_time())) as uptime;"
    str_databaseCount = "SELECT COUNT(*) AS database_count FROM pg_database WHERE datname <> 'template0' AND datname <> 'template1';"
    str_Sessions = "SELECT SUM(sessions) as total_sessions, SUM(sessions_abandoned) as total_sessions_abandoned, SUM(sessions_fatal) as total_sessions_fatal, SUM(sessions_killed) as total_sessions_killed FROM pg_stat_database;"
    str_heap = "SELECT sum(heap_blks_read) as heap_blocks_read, sum(heap_blks_hit) as heap_blocks_hit, CASE WHEN (sum(heap_blks_hit) + sum(heap_blks_read)) = 0 THEN 0 ELSE sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) END as cache_hit_ratio FROM pg_statio_user_tables;"

    dict_psqlQueries = {
        'table_count': str_tableStat,
        'active_queries': str_usageActiveStat,
        'transactions_open': str_TransactionsOpen,
        'transacttions_idle': str_TransactionsIdle,
        'db_stats': str_dbStats,
        'bg_stats': str_bgStats,
        'locks_count': str_lockStat,
        'max_conn': str_MaxConn,
        'io_stats': str_iostats,
        'idx_stats': str_idxStats,
        'version': str_version,
        'uptime': str_uptime,
        'no of databases': str_databaseCount,
        'heap_and_cache': str_heap
    }
    if waiting:
        dict_psqlQueries['active_waiting_queries'] = str_usageWaitingStat

    if major_version >= 14:
        dict_psqlQueries['session'] = str_Sessions
        conn_details = "SELECT datname as name,xact_commit as commits, xact_rollback as rollbacks, conflicts, sessions, sessions_abandoned, sessions_fatal, sessions_killed, session_time, active_time as sessions_active_time, idle_in_transaction_time as session_idle_in_transaction_time FROM pg_stat_database;"
    else:
        conn_details = "SELECT datname as name,xact_commit as commits, xact_rollback as rollbacks, conflicts FROM pg_stat_database;"

    db_details = "SELECT d.datname AS name, s.numbackends as active_connections, ROUND(pg_database_size(d.datname) / 1024 / 1024,2) AS size_in_mb,tup_inserted as rows_inserted, tup_updated as rows_updated, tup_deleted as rows_deleted, tup_fetched as rows_fetched , tup_returned as rows_returned, blks_read as block_reads , blks_hit as block_hits FROM pg_database d JOIN pg_stat_database s ON d.oid = s.datid;"


def coerce_metric_value(val_name, raw_val):
    """
    Coerces raw database metric values to integers, floats, or strings per Site24x7 rules.
    Only Server Version and Last Archived WAL File remain strings; all other numbers are emitted as ints/floats.
    """
    if raw_val is None:
        return None
    str_val = str(raw_val).strip()
    if str_val.lower() == 'none':
        return None

    if val_name in ("Server Version", "Last Archived WAL File"):
        return str_val

    # Attempt integer conversion
    try:
        # Avoid float truncation if raw string represents a float like "12.34"
        if "." not in str_val:
            return int(str_val)
        val_f = float(str_val)
        if val_f.is_integer():
            return int(val_f)
        return round(val_f, 2)
    except (ValueError, TypeError):
        try:
            return round(float(str_val), 2)
        except (ValueError, TypeError):
            return str_val


class pgsql():
    """Reuses the exact Site24x7 PostgreSQL single-node collector logic against the active primary."""
    def __init__(self, host_name, port, username, password, db):
        self._conn = None
        self._uname = username
        self._pwd = password
        self._hostname = "127.0.0.1" if host_name in ("localhost", "127.0.0.1") else host_name
        self._port = port
        self._results = {}
        self._msg = ""
        self._db = db

    def _append_msg(self, note):
        if not note:
            return
        if self._msg:
            self._msg += f"; {note}"
        else:
            self._msg = note

    def main(self):
        global VERSION
        try:
            self._results.setdefault('plugin_version', PLUGIN_VERSION)
            self._results.setdefault('heartbeat_required', HEARTBEAT)
            import psycopg2
            self._conn = psycopg2.connect(
                dbname=self._db,
                user=self._uname,
                password=self._pwd,
                host=self._hostname,
                port=self._port,
                connect_timeout=CONNECT_TIMEOUT,
                options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"
            )
            VERSION = self._conn.server_version
            inititializeQueries()
            self.metricCollector()
        except ImportError as e:
            self._results.setdefault('status', 0)
            self._results.setdefault('msg', "psycopg2 Module Not Installed\nDependency missing:'psycopg2' Python client library\nInstall with command,\n\n pip3 install psycopg2-binary\n")
        except Exception as e:
            self._results.setdefault('status', 0)
            self._results.setdefault('msg', str(e))
        finally:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
            import copy
            final_tabs = copy.deepcopy(tabs)
            wal_keys_present = [
                m for m in final_tabs["tabs"]["Write Ahead Log"]["tablist"]
                if m in self._results
            ]
            final_tabs["tabs"]["Write Ahead Log"]["tablist"] = wal_keys_present
            self._results.update(final_tabs)
            self._results["units"] = units
            if self._msg != "":
                self._results["msg"] = self._msg
            return self._results

    def metricCollector(self):
        dictResults = {}
        cur = self._conn.cursor()
        conn_result = []
        db_result = []
        for eachQuery in dict_psqlQueries.keys():
            try:
                cur.execute(dict_psqlQueries[eachQuery])
                column_names = [desc[0] for desc in cur.description]
                dictResults.setdefault(str(eachQuery), [column_names, cur.fetchall()])
            except Exception as e:
                self._append_msg(f"{eachQuery}: {str(e).splitlines()[0]}")
                self._conn.rollback()

        try:
            cur.execute(conn_details)
            conn_column_names = [desc[0] for desc in cur.description]
            conn_table_result = cur.fetchall()
            if conn_table_result:
                conn_table_result.pop(0)
        except Exception as e:
            self._append_msg(f"conn_details: {str(e).splitlines()[0]}")
            self._conn.rollback()

        try:
            cur.execute(db_details)
            db_column_names = [desc[0] for desc in cur.description]
            db_table_result = cur.fetchall()
        except Exception as e:
            self._append_msg(f"db_details: {str(e).splitlines()[0]}")
            self._conn.rollback()

        # === WAL & Archiving Metrics (no fabricated defaults on error) ===
        try:
            cur.execute("""
                SELECT 
                    ROUND(pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0') / 1024.0 / 1024.0, 2),
                    ROUND(pg_wal_lsn_diff(pg_current_wal_insert_lsn(), '0/0') / 1024.0 / 1024.0, 2),
                    ROUND(pg_wal_lsn_diff(pg_current_wal_flush_lsn(), '0/0') / 1024.0 / 1024.0, 2);
            """)
            w_row = cur.fetchone()
            if w_row:
                if w_row[0] is not None:
                    self._results["WAL Write Position"] = round(float(w_row[0]), 2)
                if w_row[1] is not None:
                    self._results["WAL Insert Position"] = round(float(w_row[1]), 2)
                if w_row[2] is not None:
                    self._results["WAL Flush Position"] = round(float(w_row[2]), 2)
        except Exception as ex:
            self._conn.rollback()
            self._append_msg(f"wal_pos: {str(ex).splitlines()[0]}")

        # Count only WAL segments (24-hex filenames); exclude timeline .history files
        try:
            cur.execute("""
                SELECT 
                    COUNT(*) as wal_files_count,
                    COALESCE(ROUND(SUM(size) / 1024.0 / 1024.0, 2), 0.0) as total_size_mb
                FROM pg_ls_waldir()
                WHERE name ~ '^[0-9A-F]{24}$';
            """)
            w_dir = cur.fetchone()
            if w_dir:
                if w_dir[0] is not None:
                    self._results["WAL Files Count"] = int(w_dir[0])
                if w_dir[1] is not None:
                    self._results["WAL Total Size"] = round(float(w_dir[1]), 2)
        except Exception as ex:
            self._conn.rollback()
            self._append_msg(f"wal_dir: {str(ex).splitlines()[0]}")

        # Report archive metrics only when archive_mode is 'on' or 'always'
        archive_mode = "off"
        try:
            cur.execute("SHOW archive_mode;")
            a_mode_row = cur.fetchone()
            if a_mode_row and a_mode_row[0]:
                archive_mode = str(a_mode_row[0]).strip().lower()
        except Exception:
            self._conn.rollback()
            archive_mode = "off"

        if archive_mode in ("on", "always"):
            try:
                cur.execute("""
                    SELECT 
                        COALESCE(archived_count, 0),
                        COALESCE(failed_count, 0),
                        COALESCE(last_archived_wal, 'No WAL archived yet')
                    FROM pg_stat_archiver;
                """)
                a_row = cur.fetchone()
                if a_row:
                    if a_row[0] is not None:
                        self._results["Archive Status Success"] = int(a_row[0])
                    if a_row[1] is not None:
                        self._results["Archive Status Failed"] = int(a_row[1])
                    if a_row[2]:
                        self._results["Last Archived WAL File"] = str(a_row[2])
            except Exception as ex:
                self._conn.rollback()
                self._append_msg(f"archiver: {str(ex).splitlines()[0]}")

            try:
                cur.execute("SELECT COUNT(*) FROM pg_ls_archive_statusdir() WHERE name LIKE '%.ready';")
                r_row = cur.fetchone()
                if r_row and r_row[0] is not None:
                    self._results["Archive Ready Files Count"] = int(r_row[0])
            except Exception as ex:
                self._conn.rollback()
                self._append_msg(f"archive_status: {str(ex).splitlines()[0]}")
        else:
            self._append_msg("archiving not enabled")

        # === Recovery Conflicts & Transaction Metrics ===
        try:
            cur.execute("""
                SELECT 
                    COALESCE(SUM(confl_tablespace), 0),
                    COALESCE(SUM(confl_lock), 0),
                    COALESCE(SUM(confl_snapshot), 0),
                    COALESCE(SUM(confl_bufferpin), 0),
                    COALESCE(SUM(confl_deadlock), 0),
                    COALESCE(SUM(confl_tablespace) + SUM(confl_lock) + SUM(confl_snapshot) +
                             SUM(confl_bufferpin) + SUM(confl_deadlock), 0)
                FROM pg_stat_database_conflicts;
            """)
            c_row = cur.fetchone()
            if c_row:
                self._results["Conflicts Tablespace"] = int(c_row[0])
                self._results["Conflicts Lock"] = int(c_row[1])
                self._results["Conflicts Snapshot"] = int(c_row[2])
                self._results["Conflicts Buffer Pin"] = int(c_row[3])
                self._results["Conflicts Deadlock"] = int(c_row[4])
                self._results["Recovery Conflicts Total"] = int(c_row[5])
        except Exception as ex:
            self._conn.rollback()
            self._append_msg(f"conflicts: {str(ex).splitlines()[0]}")

        try:
            cur.execute("""
                SELECT COALESCE(MAX(EXTRACT(EPOCH FROM now() - xact_start))::BIGINT, 0)
                FROM pg_stat_activity
                WHERE state <> 'idle' AND xact_start IS NOT NULL;
            """)
            x_row = cur.fetchone()
            if x_row and x_row[0] is not None:
                self._results["Oldest Running Transaction Age"] = int(x_row[0])
        except Exception as ex:
            self._conn.rollback()
            self._append_msg(f"xact_age: {str(ex).splitlines()[0]}")

        # === Connection Utilization Metrics ===
        try:
            cur.execute("""
                SELECT 
                    (SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend') as active_conn,
                    (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') as max_conn,
                    (SELECT setting::int FROM pg_settings WHERE name = 'superuser_reserved_connections') as reserved_conn;
            """)
            cn_row = cur.fetchone()
            if cn_row:
                a_conn = int(cn_row[0] or 0)
                m_conn = int(cn_row[1] or 100)
                r_conn = int(cn_row[2] or 3)
                avail = max(0, m_conn - r_conn - a_conn)
                u_pct = round((a_conn / m_conn) * 100.0, 2) if m_conn > 0 else 0.0
                self._results["Available Connections"] = avail
                self._results["Connection Utilization Percent"] = u_pct
        except Exception as ex:
            try:
                self._conn.rollback()
                cur.execute("""
                    SELECT 
                        (SELECT count(*) FROM pg_stat_activity WHERE client_addr IS NOT NULL) as active_conn,
                        (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') as max_conn,
                        (SELECT setting::int FROM pg_settings WHERE name = 'superuser_reserved_connections') as reserved_conn;
                """)
                cn_row = cur.fetchone()
                if cn_row:
                    a_conn = int(cn_row[0] or 0)
                    m_conn = int(cn_row[1] or 100)
                    r_conn = int(cn_row[2] or 3)
                    avail = max(0, m_conn - r_conn - a_conn)
                    u_pct = round((a_conn / m_conn) * 100.0, 2) if m_conn > 0 else 0.0
                    self._results["Available Connections"] = avail
                    self._results["Connection Utilization Percent"] = u_pct
            except Exception as inner_ex:
                self._conn.rollback()
                self._append_msg(f"conn_util: {str(inner_ex).splitlines()[0]}")

        # === Table Bloat & TxID Wraparound Safety Metrics ===
        try:
            cur.execute("SELECT COALESCE(SUM(n_dead_tup), 0)::bigint FROM pg_stat_user_tables;")
            dt_row = cur.fetchone()
            if dt_row and dt_row[0] is not None:
                self._results["Dead Tuples"] = int(dt_row[0])
            else:
                self._results["Dead Tuples"] = 0
        except Exception as ex:
            self._conn.rollback()
            self._results["Dead Tuples"] = 0
            self._append_msg(f"dead_tup: {str(ex).splitlines()[0]}")

        try:
            cur.execute("SELECT COALESCE(MAX(age(datfrozenxid)), 0)::bigint FROM pg_database WHERE datallowconn;")
            tx_row = cur.fetchone()
            if tx_row and tx_row[0] is not None:
                self._results["Oldest Transaction ID Age"] = int(tx_row[0])
            else:
                self._results["Oldest Transaction ID Age"] = 0
        except Exception as ex:
            self._conn.rollback()
            self._results["Oldest Transaction ID Age"] = 0
            self._append_msg(f"txid_age: {str(ex).splitlines()[0]}")

        cur.close()

        # Emit top-level metrics as numbers (int or float) except strings for Server Version
        for eachKey in dictResults.keys():
            query_result = dictResults[eachKey]
            columns = query_result[0]
            rows = query_result[1]
            if rows:
                row = rows[0]
                for i, j in enumerate(columns):
                    key_title = j.replace("_", " ").title()
                    coerced = coerce_metric_value(key_title, row[i])
                    if coerced is not None:
                        self._results[key_title] = coerced

        # Compute Buffer Cache Hit Ratio (%)
        try:
            b_hits = float(self._results.get("Total Block Hits", 0) or 0)
            b_reads = float(self._results.get("Total Block Reads", 0) or 0)
            tot_blks = b_hits + b_reads
            if tot_blks > 0:
                self._results["Cache Hit Ratio"] = round((b_hits / tot_blks) * 100.0, 2)
            else:
                self._results["Cache Hit Ratio"] = 100.0
        except Exception:
            self._results["Cache Hit Ratio"] = 100.0

        # Populate Tranasctions_and_Session_per_Database with strictly numeric metrics
        for row in conn_table_result:
            tab_result = {}
            for i, j in enumerate(row):
                col = conn_column_names[i]
                if col == "name":
                    tab_result[col] = str(j)[:520] if j else ""
                elif "time" in col:
                    tab_result[col] = round(float(j or 0.0), 3)
                else:
                    try:
                        tab_result[col] = int(j or 0)
                    except (ValueError, TypeError):
                        tab_result[col] = 0
            conn_result.append(tab_result)

        # Populate Stats_per_DB with strictly numeric columns (no stringifying)
        for row in db_table_result:
            tab_result = {}
            for i, j in enumerate(row):
                col = db_column_names[i]
                if col == "name":
                    tab_result[col] = str(j)[:520] if j else ""
                elif col == "size_in_mb":
                    try:
                        tab_result[col] = round(float(j or 0.0), 2)
                    except (ValueError, TypeError):
                        tab_result[col] = 0.0
                else:
                    try:
                        tab_result[col] = int(j or 0)
                    except (ValueError, TypeError):
                        tab_result[col] = 0
            db_result.append(tab_result)

        # Enforce Site24x7 25-row tabular limit
        self._results["Tranasctions_and_Session_per_Database"] = conn_result[:25]
        self._results["Stats_per_DB"] = db_result[:25]


def clean_quotes(value):
    if not value:
        return value
    value_str = str(value).strip()
    if (value_str.startswith('"') and value_str.endswith('"')) or (value_str.startswith("'") and value_str.endswith("'")):
        return value_str[1:-1].strip()
    return value_str


def parse_nodes(nodes_str, patroni_port_cfg=None):
    """
    Parses a nodes string into a list of node definitions:
      [{'name': name, 'host': host, 'port': port, 'patroni_port': patroni_port}]
    
    Supports:
      1. Embedded per-node patroni port: "node1=localhost:5441:8001,node2=localhost:5442:8002"
      2. Mapped patroni_port: patroni_port="node1=8001,node2=8002" or "8001,8002,8003"
      3. Global patroni_port: patroni_port="8008"
    """
    nodes = []
    if not nodes_str:
        return nodes

    # Parse patroni_port_cfg map if provided
    port_map = {}
    default_patroni_port = None
    if patroni_port_cfg:
        cfg_str = clean_quotes(patroni_port_cfg)
        if "," in cfg_str or "=" in cfg_str:
            for idx, p_item in enumerate(cfg_str.split(",")):
                p_item = p_item.strip()
                if "=" in p_item:
                    k, v = p_item.split("=", 1)
                    try:
                        port_map[k.strip()] = int(v.strip())
                    except ValueError:
                        pass
                else:
                    try:
                        port_map[idx] = int(p_item)
                    except ValueError:
                        pass
        else:
            try:
                default_patroni_port = int(cfg_str)
            except ValueError:
                default_patroni_port = None

    items = [item.strip() for item in str(nodes_str).replace("\n", ",").split(",") if item.strip()]
    for idx, item in enumerate(items):
        if "=" in item:
            name, hp = item.split("=", 1)
            name = name.strip()
            hp = hp.strip()
        else:
            hp = item.strip()
            name = hp

        # Check for host:port:patroni_port embedded
        parts = hp.split(":")
        patroni_port = None
        if len(parts) >= 3:
            host = parts[0].strip()
            try:
                port = int(parts[1].strip())
            except ValueError:
                port = 5432
            try:
                patroni_port = int(parts[2].strip())
            except ValueError:
                patroni_port = None
        elif len(parts) == 2:
            host = parts[0].strip()
            try:
                port = int(parts[1].strip())
            except ValueError:
                port = 5432
        else:
            host = hp
            port = 5432

        # Resolve patroni_port if not embedded
        if patroni_port is None:
            if name in port_map:
                patroni_port = port_map[name]
            elif idx in port_map:
                patroni_port = port_map[idx]
            elif f"{host}:{port}" in port_map:
                patroni_port = port_map[f"{host}:{port}"]
            elif default_patroni_port:
                patroni_port = default_patroni_port

        connect_host = "127.0.0.1" if host in ("localhost", "127.0.0.1") else host
        nodes.append({
            "name": name,
            "host": host,
            "connect_host": connect_host,
            "port": port,
            "patroni_port": patroni_port
        })
    return nodes


def probe_patroni_rest(host, patroni_port):
    """Queries Patroni REST API if configured."""
    if not patroni_port:
        return None

    import urllib.request
    connect_host = "127.0.0.1" if host in ("localhost", "127.0.0.1") else host
    try:
        url = f"http://{connect_host}:{patroni_port}/patroni"
        req = urllib.request.Request(url, headers={"User-Agent": "Site24x7-PG-Cluster"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode('utf-8'))
    except Exception:
        pass
    return None


def get_node_timeline(cur, in_recovery):
    """
    Extracts the PostgreSQL WAL timeline ID purely via SQL, without requiring Patroni.
    On primary: extracts hex timeline prefix from pg_walfile_name(pg_current_wal_lsn()).
    On standby: queries received_tli from pg_stat_wal_receiver or pg_last_wal_replay_lsn().
    Falls back to 0 (unknown) without fabricating data.
    """
    tl = None
    if not in_recovery:
        try:
            cur.execute("SELECT ('x' || substring(pg_walfile_name(pg_current_wal_lsn()) from 1 for 8))::bit(32)::int;")
            row = cur.fetchone()
            if row and row[0] is not None:
                tl = int(row[0])
        except Exception:
            pass
    else:
        try:
            cur.execute("SELECT received_tli FROM pg_stat_wal_receiver;")
            row = cur.fetchone()
            if row and row[0] is not None:
                tl = int(row[0])
        except Exception:
            pass

        if tl is None:
            try:
                cur.execute("SELECT ('x' || substring(pg_walfile_name(pg_last_wal_replay_lsn()) from 1 for 8))::bit(32)::int;")
                row = cur.fetchone()
                if row and row[0] is not None:
                    tl = int(row[0])
            except Exception:
                pass

    if tl is None:
        try:
            cur.execute("SELECT timeline_id FROM pg_control_checkpoint();")
            row = cur.fetchone()
            if row and row[0] is not None:
                tl = int(row[0])
        except Exception:
            pass

    return tl if tl is not None else 0


class PostgresClusterCollector:
    """Monitors multiple PostgreSQL nodes, builds cluster metrics & child tables, and queries active primary."""
    def __init__(self, nodes_str, username, password, db, patroni_port=None):
        self.nodes_str = clean_quotes(nodes_str) if nodes_str else NODES
        self.username = clean_quotes(username) if username else USERNAME
        self.password = clean_quotes(password) if password else PASSWORD
        self.db = clean_quotes(db) if db else DB
        self.patroni_port_cfg = clean_quotes(patroni_port) if patroni_port else PATRONI_PORT
        self.msg_notes = []

    def _add_note(self, note):
        if note and note not in self.msg_notes:
            self.msg_notes.append(note)

    def probe_single_node(self, node_info):
        """Probes a single node for status, role, timeline, and replication health."""
        import psycopg2

        name = node_info["name"]
        host = node_info.get("connect_host") or ("127.0.0.1" if node_info["host"] in ("localhost", "127.0.0.1") else node_info["host"])
        original_host = node_info["host"]
        port = node_info["port"]
        patroni_port = node_info["patroni_port"]

        node_status = "down"
        node_role = "offline"
        timeline = 0
        resp_time_ms = 0.0
        patroni_state = "N/A"
        conn = None
        last_err = ""
        is_primary = False
        standby_lags = []
        replication_standbys = []
        node_timeline = None
        auth_failure = None
        network_failure = None
        replay_backlog_bytes = 0
        replay_delay_s = 0.0
        node_connections = 0

        t0 = time.time()
        try:
            conn = psycopg2.connect(
                dbname=self.db,
                user=self.username,
                password=self.password,
                host=host,
                port=port,
                connect_timeout=CONNECT_TIMEOUT,
                options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"
            )
        except Exception as e:
            last_err = str(e)
            if ("database" in last_err.lower() and "does not exist" in last_err.lower()) and self.db != "postgres":
                try:
                    conn = psycopg2.connect(
                        dbname="postgres",
                        user=self.username,
                        password=self.password,
                        host=host,
                        port=port,
                        connect_timeout=CONNECT_TIMEOUT,
                        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"
                    )
                except Exception as inner_e:
                    conn = None
                    last_err = str(inner_e)

        resp_time_ms = round((time.time() - t0) * 1000.0, 2)

        # Probe Patroni REST if configured
        patroni_info = probe_patroni_rest(host, patroni_port)
        if patroni_info:
            patroni_state = str(patroni_info.get("state", "running"))[:100]

        if conn is not None:
            node_status = "up"
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_is_in_recovery();")
                    in_recovery = cur.fetchone()[0]
                    node_role = "standby" if in_recovery else "primary"
                    is_primary = not in_recovery

                    # Retrieve connections on this node
                    try:
                        cur.execute("SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend';")
                        row = cur.fetchone()
                        node_connections = int(row[0]) if row and row[0] is not None else 0
                    except Exception:
                        try:
                            conn.rollback()
                            cur.execute("SELECT count(*) FROM pg_stat_activity WHERE client_addr IS NOT NULL;")
                            row = cur.fetchone()
                            node_connections = int(row[0]) if row and row[0] is not None else 0
                        except Exception:
                            conn.rollback()
                            node_connections = 0

                    # Retrieve timeline purely via SQL without fabrication
                    tl = get_node_timeline(cur, in_recovery)
                    if tl == 0 and patroni_info and "timeline" in patroni_info:
                        try:
                            tl = int(patroni_info["timeline"])
                        except Exception:
                            tl = 0
                    timeline = tl
                    node_timeline = tl if tl > 0 else None

                    if not in_recovery:
                        replay_backlog_bytes = 0
                        replay_delay_s = 0.0
                        # Query connected replicas from primary
                        try:
                            cur.execute("""
                                SELECT
                                    COALESCE(application_name, client_addr::text, 'standby') AS name,
                                    COALESCE(client_addr::text, 'local') AS client_addr,
                                    COALESCE(state, 'unknown') AS state,
                                    COALESCE(sync_state, 'unknown') AS sync_state,
                                    COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn), 0)::bigint AS replay_lag_bytes,
                                    COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), write_lsn), 0)::bigint AS write_lag_bytes,
                                    COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), flush_lsn), 0)::bigint AS flush_lag_bytes
                                FROM pg_stat_replication;
                            """)
                            for row in cur.fetchall():
                                s_name = str(row[0])[:520]
                                c_addr = str(row[1])[:100]
                                s_state = str(row[2])[:100]
                                sy_state = str(row[3])[:100]
                                r_lag = int(row[4] or 0)
                                w_lag = int(row[5] or 0)
                                f_lag = int(row[6] or 0)
                                is_sync = 1 if sy_state.lower() in ('sync', 'quorum') else 0

                                st_entry = {
                                    "name": s_name,
                                    "client_addr": c_addr,
                                    "state": s_state,
                                    "sync_state": sy_state,
                                    "is_sync": is_sync,
                                    "replay_lag_bytes": r_lag,
                                    "write_lag_bytes": w_lag,
                                    "flush_lag_bytes": f_lag
                                }
                                replication_standbys.append(st_entry)
                        except Exception as st_ex:
                            conn.rollback()
                            self._add_note(f"standby_query: {str(st_ex).splitlines()[0]}")
                    else:
                        # Standby node: check replay lag and delay from standby side
                        try:
                            cur.execute("""
                                SELECT 
                                    COALESCE(pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn()), 0)::bigint,
                                    COALESCE(EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp())), 0.0)::float;
                            """)
                            s_row = cur.fetchone()
                            if s_row:
                                replay_backlog_bytes = int(s_row[0] or 0)
                                replay_delay_s = round(float(s_row[1] or 0.0), 2)
                                standby_lags.append(replay_backlog_bytes)
                        except Exception:
                            conn.rollback()
                            replay_backlog_bytes = 0
                            replay_delay_s = 0.0
            except Exception as node_ex:
                self._add_note(f"node_probe: {str(node_ex).splitlines()[0]}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        else:
            err_lower = last_err.lower()
            if "authentication failed" in err_lower or "password" in err_lower:
                auth_failure = (name, last_err)
            else:
                network_failure = (name, last_err)

        up_num = 1 if (node_status == "up") else 0
        is_primary_num = 1 if is_primary else 0

        # Site24x7 Tabular Schema Compliance:
        # Columns: name (str, <=520), role (str, <=100), patroni_state (str, <=100),
        # up (int 1/0), is_primary (int 1/0), timeline (int), response_time_ms (float),
        # replay_backlog_bytes (int), replay_delay_s (float), connections (int), status (int 1/0)
        cluster_node = {
            "name": str(name)[:520],
            "role": str(node_role)[:100],
            "patroni_state": str(patroni_state)[:100],
            "up": up_num,
            "is_primary": is_primary_num,
            "timeline": int(timeline),
            "response_time_ms": float(resp_time_ms),
            "replay_backlog_bytes": int(replay_backlog_bytes),
            "replay_delay_s": float(replay_delay_s),
            "connections": int(node_connections),
            "status": up_num
        }

        return {
            "name": name,
            "host": host,
            "original_host": original_host,
            "port": port,
            "cluster_node": cluster_node,
            "is_up": (node_status == "up"),
            "is_primary": is_primary,
            "timeline": node_timeline,
            "standby_lags": standby_lags,
            "replication_standbys": replication_standbys,
            "auth_failure": auth_failure,
            "network_failure": network_failure
        }

    def collect(self):
        results = {
            "plugin_version": PLUGIN_VERSION,
            "heartbeat_required": HEARTBEAT,
            "status": 1
        }

        try:
            import psycopg2
        except ImportError:
            results["status"] = 0
            results["msg"] = "psycopg2 Module Not Installed\nInstall with: pip3 install psycopg2-binary"
            results.update(tabs)
            results["units"] = units
            return results

        parsed_nodes = parse_nodes(self.nodes_str, self.patroni_port_cfg)
        if not parsed_nodes:
            results["status"] = 0
            results["msg"] = "No nodes configured in nodes entry."
            results.update(tabs)
            results["units"] = units
            return results

        start_time = time.time()
        overall_deadline = 9.5  # Hard overall deadline in seconds

        import concurrent.futures

        probe_results = []
        # Manage the executor manually and call shutdown(wait=False, cancel_futures=True) after wait
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(len(parsed_nodes), 8))
        try:
            future_to_node = {executor.submit(self.probe_single_node, n): n for n in parsed_nodes}
            time_left = max(0.5, 5.0 - (time.time() - start_time))
            done, not_done = concurrent.futures.wait(future_to_node.keys(), timeout=time_left)
            for f in done:
                try:
                    probe_results.append(f.result())
                except Exception as ex:
                    node_info = future_to_node[f]
                    probe_results.append({
                        "name": node_info["name"],
                        "host": node_info["host"],
                        "port": node_info["port"],
                        "cluster_node": {
                            "name": str(node_info["name"])[:520],
                            "role": "offline",
                            "patroni_state": "N/A",
                            "up": 0,
                            "is_primary": 0,
                            "timeline": 0,
                            "response_time_ms": 0.0,
                            "replay_backlog_bytes": 0,
                            "replay_delay_s": 0.0,
                            "connections": 0,
                            "status": 0
                        },
                        "is_up": False,
                        "is_primary": False,
                        "timeline": None,
                        "standby_lags": [],
                        "replication_standbys": [],
                        "auth_failure": None,
                        "network_failure": (node_info["name"], str(ex))
                    })
            for f in not_done:
                node_info = future_to_node[f]
                probe_results.append({
                    "name": node_info["name"],
                    "host": node_info["host"],
                    "port": node_info["port"],
                    "cluster_node": {
                        "name": str(node_info["name"])[:520],
                        "role": "offline",
                        "patroni_state": "timeout",
                        "up": 0,
                        "is_primary": 0,
                        "timeline": 0,
                        "response_time_ms": 0.0,
                        "replay_backlog_bytes": 0,
                        "replay_delay_s": 0.0,
                        "connections": 0,
                        "status": 0
                    },
                    "is_up": False,
                    "is_primary": False,
                    "timeline": None,
                    "standby_lags": [],
                    "replication_standbys": [],
                    "auth_failure": None,
                    "network_failure": (node_info["name"], "Connection timeout")
                })
        finally:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                executor.shutdown(wait=False)

        # Preserve input order for cluster_nodes table
        node_order = {n["name"]: idx for idx, n in enumerate(parsed_nodes)}
        probe_results.sort(key=lambda x: node_order.get(x["name"], 0))

        cluster_nodes = []
        replication_standbys = []
        primaries = []
        standby_lags = []
        node_timelines = []
        auth_failures = []
        network_failures = []

        for res in probe_results:
            cluster_nodes.append(res["cluster_node"])
            if res["is_up"]:
                if res["timeline"] is not None and res["timeline"] > 0:
                    node_timelines.append(res["timeline"])
                if res["is_primary"]:
                    primaries.append({
                        "name": res["name"],
                        "host": res["host"],
                        "port": res["port"],
                        "timeline": res["timeline"] or 0
                    })
                    replication_standbys.extend(res["replication_standbys"])
                else:
                    standby_lags.extend(res["standby_lags"])
            else:
                if res["auth_failure"]:
                    auth_failures.append(res["auth_failure"])
                if res["network_failure"]:
                    network_failures.append(res["network_failure"])

        # Calculate cluster metrics
        nodes_total = len(cluster_nodes)
        nodes_up = sum(1 for n in cluster_nodes if n["status"] == 1)
        primary_count = len(primaries)
        no_primary_flag = 1 if primary_count == 0 else 0
        split_brain_flag = 1 if primary_count > 1 else 0
        primary_timeline = primaries[0]["timeline"] if primary_count >= 1 else (node_timelines[0] if node_timelines else 0)

        # Max replay backlog calculation
        max_replay_backlog = 0
        if replication_standbys:
            max_replay_backlog = max(int(r.get("replay_lag_bytes", 0)) for r in replication_standbys)
        elif standby_lags:
            max_replay_backlog = max(standby_lags)

        # Replication slot metrics
        slots_total = 0
        slots_active = 0
        slots_inactive = 0
        slots_physical = 0
        slots_logical = 0
        max_slot_lag_bytes = 0

        # Handle wrong password vs outage when nodes are down
        if nodes_up == 0 and len(auth_failures) == len(parsed_nodes):
            results["status"] = 0
            results["msg"] = f"password authentication failed for user \"{self.username}\""
            results["Tranasctions_and_Session_per_Database"] = []
            results["Stats_per_DB"] = []
        elif primary_count >= 1:
            detected_primary = primaries[0]

            def collect_primary_work():
                collector = pgsql(
                    detected_primary["host"],
                    detected_primary["port"],
                    self.username,
                    self.password,
                    self.db
                )
                p_data = collector.main()

                # Query replication slot metrics from detected primary
                s_tot, s_act, s_inact, s_phys, s_log, s_lag = 0, 0, 0, 0, 0, 0
                try:
                    import psycopg2
                    prim_conn = psycopg2.connect(
                        dbname=self.db,
                        user=self.username,
                        password=self.password,
                        host=detected_primary["host"],
                        port=detected_primary["port"],
                        connect_timeout=CONNECT_TIMEOUT,
                        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"
                    )
                    with prim_conn.cursor() as cur:
                        cur.execute("""
                            SELECT
                                count(*)::int AS total_slots,
                                COALESCE(count(*) FILTER (WHERE active = true), 0)::int AS active_slots,
                                COALESCE(count(*) FILTER (WHERE active = false), 0)::int AS inactive_slots,
                                COALESCE(count(*) FILTER (WHERE slot_type = 'physical'), 0)::int AS physical_slots,
                                COALESCE(count(*) FILTER (WHERE slot_type = 'logical'), 0)::int AS logical_slots,
                                COALESCE(max(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)), 0)::bigint AS max_slot_lag_bytes
                            FROM pg_replication_slots;
                        """)
                        row = cur.fetchone()
                        if row:
                            s_tot = row[0]
                            s_act = row[1]
                            s_inact = row[2]
                            s_phys = row[3]
                            s_log = row[4]
                            s_lag = row[5]
                    prim_conn.close()
                except Exception as p_ex:
                    collector._append_msg(f"slots: {str(p_ex).splitlines()[0]}")

                return p_data, (s_tot, s_act, s_inact, s_phys, s_log, s_lag)

            # Enforce primary collection within remaining deadline
            time_left_primary = max(0.5, overall_deadline - (time.time() - start_time))
            prim_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                prim_future = prim_executor.submit(collect_primary_work)
                done, _ = concurrent.futures.wait([prim_future], timeout=time_left_primary)
                if done:
                    primary_data, slot_metrics = prim_future.result()
                    slots_total, slots_active, slots_inactive, slots_physical, slots_logical, max_slot_lag_bytes = slot_metrics

                    # Copy generic metrics and table data from primary
                    for k, v in primary_data.items():
                        if k not in ("tabs", "units", "s247config", "plugin_version", "heartbeat_required"):
                            results[k] = v
                else:
                    self._add_note("Primary collection timed out")
                    results["Tranasctions_and_Session_per_Database"] = []
                    results["Stats_per_DB"] = []
            finally:
                try:
                    prim_executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    prim_executor.shutdown(wait=False)
        else:
            # Nodes are up or dead, but no primary found
            self._add_note("Cluster alert: No primary node detected (failover in progress or all nodes down/standby)")
            results["Tranasctions_and_Session_per_Database"] = []
            results["Stats_per_DB"] = []

        # Populate cluster metrics as numeric integers/floats
        results["Nodes Total"] = int(nodes_total)
        results["Nodes Up"] = int(nodes_up)
        results["Primary Count"] = int(primary_count)
        results["No Primary Flag"] = int(no_primary_flag)
        results["Split Brain Flag"] = int(split_brain_flag)
        results["Primary Timeline"] = int(primary_timeline)
        results["Max Replay Backlog"] = int(max_replay_backlog)
        results["Replication Slots Total"] = int(slots_total)
        results["Replication Slots Active"] = int(slots_active)
        results["Replication Slots Inactive"] = int(slots_inactive)
        results["Physical Slots"] = int(slots_physical)
        results["Logical Slots"] = int(slots_logical)
        results["Max Slot Lag Bytes"] = int(max_slot_lag_bytes)

        # Child tables: strictly enforce Site24x7 25-row tabular limit
        results["Cluster_Nodes"] = cluster_nodes[:25]
        results["Replication_Standbys"] = replication_standbys[:25]

        # Site24x7 child discovery: strictly per-DB tables (Cluster child tables in tablist only)
        results["s247config"] = {
            "childdiscovery": [
                "Tranasctions_and_Session_per_Database",
                "Stats_per_DB"
            ]
        }

        # Apply dynamic tabs and units (exclude absent archive metrics when archive_mode is off)
        import copy
        final_tabs = copy.deepcopy(tabs)
        wal_keys_present = [
            m for m in final_tabs["tabs"]["Write Ahead Log"]["tablist"]
            if m in results
        ]
        final_tabs["tabs"]["Write Ahead Log"]["tablist"] = wal_keys_present
        results.update(final_tabs)
        results["units"] = units

        # Merge any collector message notes without forcing status to 0
        if self.msg_notes:
            existing_msg = results.get("msg", "")
            notes_str = "; ".join(self.msg_notes)
            results["msg"] = f"{existing_msg}; {notes_str}".strip("; ") if existing_msg else notes_str

        return results


def run(param):
    """Site24x7 agent Python plugin entrypoint."""
    nodes = param.get("nodes") if param and param.get("nodes") else NODES
    username = param.get("username") if param and param.get("username") else USERNAME
    password = param.get("password") if param and param.get("password") else PASSWORD
    db = param.get("db") if param and param.get("db") else DB
    patroni_port = param.get("patroni_port") if param and param.get("patroni_port") else PATRONI_PORT

    collector = PostgresClusterCollector(nodes, username, password, db, patroni_port)
    return collector.collect()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Site24x7 PostgreSQL Cluster Plugin")
    parser.add_argument('--nodes', help='Comma-separated nodes (host:port, name=host:port, or host:port:patroni_port)', default=NODES)
    parser.add_argument('--username', help='PostgreSQL username', default=USERNAME)
    parser.add_argument('--password', help='PostgreSQL password', default=PASSWORD)
    parser.add_argument('--db', help='Database name', default=DB)
    parser.add_argument('--patroni_port', help='Patroni REST port or mapping', default=PATRONI_PORT)
    args = parser.parse_args()

    collector = PostgresClusterCollector(
        nodes_str=args.nodes,
        username=args.username,
        password=args.password,
        db=args.db,
        patroni_port=args.patroni_port
    )
    result = collector.collect()
    print(json.dumps(result))