#!/bin/bash
# ==============================================================================
# Site24x7 PostgreSQL Cluster Plugin Installer
# Installs and configures the postgres_cluster plugin for Site24x7 Linux Agent.
# ==============================================================================

func_exit() {
    tput sgr0 2>/dev/null || true
    exit 0
}

trap func_exit SIGINT SIGTSTP

plugin="postgres_cluster"
agent_dir="/opt/site24x7/monagent"
agent_path_change=false
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

error_handler() {
    if [ $1 -ne 0 ]; then
        tput setaf 1 2>/dev/null || true
        echo "------------Error Occurred------------"
        echo "$2"
        tput sgr0 2>/dev/null || true
        echo "------------Process Exited------------"
        exit 1
    fi
}

prerequisites() {
    tput setaf 3 2>/dev/null || true
    echo "=========================================================="
    echo "    Site24x7 PostgreSQL Cluster Plugin - Prerequisites   "
    echo "=========================================================="
    tput sgr0 2>/dev/null || true
    echo "Ensure you meet the following prerequisites before proceeding:"
    echo "  1. Python 3.9 or higher must be installed on this server."
    echo "  2. The psycopg2 (or psycopg2-binary) Python module must be installed."
    echo "  3. A dedicated monitoring user (e.g. 'site24x7') with 'pg_read_all_stats'"
    echo "     must exist on the PostgreSQL cluster nodes."
    echo "     (Use create_user.sql or create_user.sh to create this role)."
    echo "  4. Network connectivity between this host and the PostgreSQL nodes."
    echo
    if [ -t 0 ] && [ -z "$NON_INTERACTIVE" ]; then
        read -p "Do you want to continue with the installation? (y/n) [y]: " continue_inst
        continue_inst="${continue_inst:-y}"
        if [[ ! "$continue_inst" =~ ^[Yy]$ ]]; then
            echo "Installation cancelled."
            exit 0
        fi
    fi
}

check_python() {
    echo "Checking Python 3 environment..."
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="python3"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_BIN="python"
    else
        error_handler 1 "Python 3 is required but neither 'python3' nor 'python' was found in PATH."
    fi

    if ! "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
        error_handler 1 "Python 3.9 or newer is required by the plugin."
    fi

    # Verify psycopg2 in system Python
    if ! $PYTHON_BIN -c "import psycopg2" >/dev/null 2>&1; then
        tput setaf 3 2>/dev/null || true
        echo "psycopg2 is not installed in system Python. Attempting to install psycopg2-binary..."
        tput sgr0 2>/dev/null || true
        $PYTHON_BIN -m pip install --quiet psycopg2-binary || {
            error_handler 1 "Failed to install psycopg2-binary. Run: pip install psycopg2-binary manually."
        }
    fi
    echo "✓ System Python ($($PYTHON_BIN --version)) and psycopg2 are ready."

}

get_plugin_data() {
    echo
    echo "Enter PostgreSQL Cluster configuration details (there are no built-in defaults):"
    if [ -t 0 ] && [ -z "$NON_INTERACTIVE" ]; then
        read -p "Enter PostgreSQL cluster seed host or IP (e.g. postgres-primary.prod.internal): " cluster_host
        read -p "Enter monitoring username: " username
        read -s -p "Enter monitoring password: " password
        echo
        read -p "Enter database name [postgres]: " db
        db="${db:-postgres}"
        read -p "Enter PostgreSQL port [5432]: " postgres_port
        postgres_port="${postgres_port:-5432}"
        read -p "Enter Patroni REST port (leave empty for default 8008; 'none' to disable): " patroni_port
        read -p "Optional address map (leave empty if not needed): " address_map
        read -p "Replay delay warning threshold seconds [60]: " replay_warn_seconds
        read -p "Replay backlog warning threshold bytes [104857600]: " replay_warn_bytes
        read -p "Recent failover warning window seconds [900]: " failover_warn_seconds
        read -p "Replication slot warning threshold bytes [1073741824]: " slot_warn_bytes
        read -p "Replication slot critical threshold bytes [10737418240]: " slot_critical_bytes
        replay_warn_seconds="${replay_warn_seconds:-60}"
        replay_warn_bytes="${replay_warn_bytes:-104857600}"
        failover_warn_seconds="${failover_warn_seconds:-900}"
        slot_warn_bytes="${slot_warn_bytes:-1073741824}"
        slot_critical_bytes="${slot_critical_bytes:-10737418240}"
    else
        # Non-interactive: everything passed as environment variables
        cluster_host="${PG_CLUSTER_HOST:-${CLUSTER_HOST:-$cluster_host}}"
        nodes="${PG_NODES:-$nodes}"
        username="${MONITOR_USER:-$username}"
        password="${MONITOR_PASSWORD:-$password}"
        db="${MONITOR_DB:-${db:-postgres}}"
        postgres_port="${POSTGRES_PORT:-${postgres_port:-5432}}"
        patroni_port="${PATRONI_PORT:-$patroni_port}"
        address_map="${ADDRESS_MAP:-$address_map}"
        replay_warn_seconds="${REPLAY_WARN_SECONDS:-60}"
        replay_warn_bytes="${REPLAY_WARN_BYTES:-104857600}"
        failover_warn_seconds="${FAILOVER_WARN_SECONDS:-900}"
        slot_warn_bytes="${SLOT_WARN_BYTES:-1073741824}"
        slot_critical_bytes="${SLOT_CRITICAL_BYTES:-10737418240}"
    fi

    missing=""
    [ -z "$cluster_host" ] && [ -z "$nodes" ] && missing="$missing cluster_host(PG_CLUSTER_HOST)"
    [ -z "$username" ] && missing="$missing username(MONITOR_USER)"
    [ -z "$password" ] && missing="$missing password(MONITOR_PASSWORD)"
    if [ -n "$missing" ]; then
        error_handler 1 "Missing required setting(s):$missing. Enter them when asked, or export the variables in brackets for a non-interactive install."
    fi

    if ! "$PYTHON_BIN" - "$replay_warn_seconds" "$replay_warn_bytes" "$failover_warn_seconds" "$slot_warn_bytes" "$slot_critical_bytes" <<'PY'
import sys
try:
    replay_seconds, replay_bytes, failover_seconds, slot_warn, slot_critical = map(int, sys.argv[1:])
except (TypeError, ValueError):
    sys.exit(1)
if min(replay_seconds, replay_bytes, failover_seconds, slot_warn, slot_critical) < 0:
    sys.exit(1)
if slot_critical <= slot_warn:
    sys.exit(1)
PY
    then
        error_handler 1 "Health thresholds must be zero or greater, and SLOT_CRITICAL_BYTES must be greater than SLOT_WARN_BYTES."
    fi
}

check_plugin_execution() {
    echo
    echo "Testing plugin execution against cluster..."
    # Locate postgres_cluster.py locally first
    PY_SOURCE="$script_dir/postgres_cluster.py"
    if [ ! -f "$PY_SOURCE" ] && [ -f "$script_dir/../postgres_cluster.py" ]; then
        PY_SOURCE="$script_dir/../postgres_cluster.py"
    fi

    # If not found locally, attempt to download from repo (final location to be decided)
    if [ ! -f "$PY_SOURCE" ]; then
        echo "postgres_cluster.py not found locally. Attempting to download from repository..."
        RAW_URL="https://raw.githubusercontent.com/JoanathanPS/postgres-cluster-plugin/upstream-layout/upstream_layout/postgres_cluster/postgres_cluster.py"
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL "$RAW_URL" -o "$script_dir/postgres_cluster.py" 2>/dev/null || true
        elif command -v wget >/dev/null 2>&1; then
            wget -q "$RAW_URL" -O "$script_dir/postgres_cluster.py" 2>/dev/null || true
        fi
        if [ -f "$script_dir/postgres_cluster.py" ]; then
            PY_SOURCE="$script_dir/postgres_cluster.py"
        else
            error_handler 1 "postgres_cluster.py not found locally and could not be downloaded. If the repository is private, please clone the repository first: git clone -b upstream-layout https://github.com/JoanathanPS/postgres-cluster-plugin.git"
        fi
    fi

    test_cmd=("$PYTHON_BIN" "$PY_SOURCE")
    if [ -n "$cluster_host" ]; then
        test_cmd+=("--cluster_host" "$cluster_host" "--postgres_port" "$postgres_port")
    else
        test_cmd+=("--nodes" "$nodes")
    fi
    test_cmd+=("--username" "$username" "--db" "$db")
    if [ -n "$patroni_port" ] && [ "$patroni_port" != "none" ]; then
        test_cmd+=("--patroni_port" "$patroni_port")
    fi
    if [ -n "$address_map" ]; then
        test_cmd+=("--address_map" "$address_map")
    fi
    test_cmd+=("--replay_warn_seconds" "$replay_warn_seconds" "--replay_warn_bytes" "$replay_warn_bytes")
    test_cmd+=("--failover_warn_seconds" "$failover_warn_seconds" "--slot_warn_bytes" "$slot_warn_bytes" "--slot_critical_bytes" "$slot_critical_bytes")

    output=$(PGPASSWORD="$password" "${test_cmd[@]}" 2>&1)
    status_code=$?
    if [ $status_code -ne 0 ]; then
        tput setaf 1 2>/dev/null || true
        echo "Plugin test execution failed with exit code $status_code:"
        echo "$output"
        tput sgr0 2>/dev/null || true
        exit 1
    fi

    if echo "$output" | grep -q '"status": 0'; then
        tput setaf 1 2>/dev/null || true
        echo "Plugin returned status 0 (error condition):"
        echo "$output"
        tput sgr0 2>/dev/null || true
        exit 1
    fi

    tput setaf 2 2>/dev/null || true
    echo "✓ Plugin test run succeeded!"
    echo "$output" | head -n 25
    tput sgr0 2>/dev/null || true
}

deploy_plugin() {
    echo
    echo "Deploying plugin to Site24x7 agent directory: $agent_dir/plugins/$plugin"
    if [ ! -d "$agent_dir" ]; then
        tput setaf 3 2>/dev/null || true
        echo "Notice: $agent_dir does not exist on this machine."
        echo "The plugin files will remain in $script_dir ready for distribution."
        tput sgr0 2>/dev/null || true
        return 0
    fi

    mkdir -p "$agent_dir/plugins/$plugin"
    cp "$PY_SOURCE" "$agent_dir/plugins/$plugin/postgres_cluster.py"
    chmod +x "$agent_dir/plugins/$plugin/postgres_cluster.py"

    cat > "$agent_dir/plugins/$plugin/postgres_cluster.cfg" <<EOF
[global_configurations]
use_agent_python=0
redirect_output=1

[$plugin]
EOF
    if [ -n "$cluster_host" ]; then
        cat >> "$agent_dir/plugins/$plugin/postgres_cluster.cfg" <<EOF
cluster_host="$cluster_host"
postgres_port="$postgres_port"
EOF
    else
        cat >> "$agent_dir/plugins/$plugin/postgres_cluster.cfg" <<EOF
nodes="$nodes"
EOF
    fi
    cat >> "$agent_dir/plugins/$plugin/postgres_cluster.cfg" <<EOF
username="$username"
password="$password"
db="$db"
patroni_port="$patroni_port"
address_map="$address_map"
replay_warn_seconds="$replay_warn_seconds"
replay_warn_bytes="$replay_warn_bytes"
failover_warn_seconds="$failover_warn_seconds"
slot_warn_bytes="$slot_warn_bytes"
slot_critical_bytes="$slot_critical_bytes"
EOF
    chmod 600 "$agent_dir/plugins/$plugin/postgres_cluster.cfg"

    echo "✓ Plugin installed at $agent_dir/plugins/$plugin"
}

main() {
    prerequisites
    check_python
    get_plugin_data
    check_plugin_execution
    deploy_plugin
    echo
    tput setaf 2 2>/dev/null || true
    echo "=========================================================="
    echo " Site24x7 PostgreSQL Cluster Plugin setup completed!     "
    echo "=========================================================="
    tput sgr0 2>/dev/null || true
}

main
