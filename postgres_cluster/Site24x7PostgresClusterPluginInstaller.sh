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
    echo "  1. Python 3.6 or higher must be installed on this server."
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

    # If Site24x7 Agent has internal Python (when use_agent_python=1), install psycopg2 there as well
    for AGENT_PY in "$agent_dir/temp/Python3/bin/python3" "$agent_dir/temp/bin/python3" "$agent_dir/python/bin/python3"; do
        if [ -x "$AGENT_PY" ]; then
            echo "Found Site24x7 Agent internal Python at: $AGENT_PY"
            if ! "$AGENT_PY" -c "import psycopg2" >/dev/null 2>&1; then
                echo "Installing psycopg2-binary into Agent internal Python..."
                "$AGENT_PY" -m pip install --quiet psycopg2-binary 2>/dev/null || true
            fi
        fi
    done
}

get_plugin_data() {
    echo
    echo "Enter PostgreSQL Cluster configuration details:"
    if [ -t 0 ] && [ -z "$NON_INTERACTIVE" ]; then
        read -p "Enter cluster nodes (comma-separated host:port or name=host:port) [localhost:5441,localhost:5442,localhost:5443]: " input_nodes
        nodes="${input_nodes:-localhost:5441,localhost:5442,localhost:5443}"

        read -p "Enter monitoring username [site24x7]: " input_user
        username="${input_user:-site24x7}"

        read -s -p "Enter monitoring password [site24x7]: " input_pass
        echo
        password="${input_pass:-site24x7}"

        read -p "Enter database name [postgres]: " input_db
        db="${input_db:-postgres}"

        read -p "Enter Patroni REST port (press Enter to skip) [8008]: " input_patroni
        patroni_port="${input_patroni:-8008}"
    else
        nodes="${PG_NODES:-localhost:5441,localhost:5442,localhost:5443}"
        username="${MONITOR_USER:-site24x7}"
        password="${MONITOR_PASSWORD:-site24x7}"
        db="${MONITOR_DB:-postgres}"
        patroni_port="${PATRONI_PORT:-8008}"
    fi
}

check_plugin_execution() {
    echo
    echo "Testing plugin execution against cluster..."
    test_cmd=("$PYTHON_BIN" "$script_dir/postgres_cluster.py" "--nodes" "$nodes" "--username" "$username" "--password" "$password" "--db" "$db")
    if [ -n "$patroni_port" ] && [ "$patroni_port" != "none" ]; then
        test_cmd+=("--patroni_port" "$patroni_port")
    fi

    output=$("${test_cmd[@]}" 2>&1)
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
    cp "$script_dir/postgres_cluster.py" "$agent_dir/plugins/$plugin/"
    chmod +x "$agent_dir/plugins/$plugin/postgres_cluster.py"

    cat > "$agent_dir/plugins/$plugin/postgres_cluster.cfg" <<EOF
[global_configurations]
use_agent_python=1

[postgres_cluster]
nodes="$nodes"
username="$username"
password="$password"
db="$db"
patroni_port="$patroni_port"
EOF

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
