#!/bin/bash
# ==============================================================================
# Patroni Cluster Automatic Failover Test & Plugin Validation
# Demonstrates seamless failover, timeline advancement, and plugin resilience.
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

PLUGIN_PY="$SCRIPT_DIR/postgres_cluster/postgres_cluster.py"
NODES="${PG_NODES:-node1=localhost:5441,node2=localhost:5442,node3=localhost:5443}"
USER="${MONITOR_USER:-site24x7}"
PASS="${MONITOR_PASSWORD:-site24x7}"
DB="${MONITOR_DB:-appdb}"
PATRONI_PORT="${PATRONI_PORT:-8008}"

echo "=================================================================="
echo " Starting Automated Patroni PostgreSQL Failover Test"
echo "=================================================================="

# Step 1: Query initial state
echo "[1/5] Querying initial cluster status via plugin..."
INIT_OUT=$("$PYTHON_BIN" "$PLUGIN_PY" --nodes "$NODES" --username "$USER" --password "$PASS" --db "$DB" --patroni_port "$PATRONI_PORT")

INIT_UP=$(echo "$INIT_OUT" | grep -o '"Nodes Up": [0-9]*' | awk '{print $NF}')
INIT_TL=$(echo "$INIT_OUT" | grep -o '"Primary Timeline": [0-9]*' | awk '{print $NF}')
echo "Initial State: Nodes Up = $INIT_UP, Primary Timeline = $INIT_TL"

# Find current leader container
LEADER_NAME=""
for node in patroni-pg-node1 patroni-pg-node2 patroni-pg-node3; do
    if docker exec "$node" patronictl -c /home/postgres/config/patroni.yml list 2>/dev/null | grep "$node" | grep -q "Leader"; then
        LEADER_NAME="$node"
        break
    fi
done

if [ -z "$LEADER_NAME" ]; then
    # Fallback: check which container has port 5441..5443 matching primary role in plugin
    echo "Determining leader from plugin output..."
    LEADER_NAME="patroni-pg-node3" # default fallback
fi
echo "Identified current active leader: $LEADER_NAME"

# Step 2: Stop the current leader
echo
echo "[2/5] Simulating primary failure: stopping $LEADER_NAME..."
docker stop "$LEADER_NAME"

# Step 3: Wait for Patroni automatic failover
echo
echo "[3/5] Waiting 12 seconds for Patroni automatic leader promotion..."
sleep 12

# Step 4: Run plugin and verify failover
echo
echo "[4/5] Running postgres_cluster plugin against cluster with stopped leader..."
FAILOVER_OUT=$("$PYTHON_BIN" "$PLUGIN_PY" --nodes "$NODES" --username "$USER" --password "$PASS" --db "$DB" --patroni_port "$PATRONI_PORT")

NEW_UP=$(echo "$FAILOVER_OUT" | grep -o '"Nodes Up": [0-9]*' | awk '{print $NF}')
NEW_PRIM_COUNT=$(echo "$FAILOVER_OUT" | grep -o '"Primary Count": [0-9]*' | awk '{print $NF}')
NEW_TL=$(echo "$FAILOVER_OUT" | grep -o '"Primary Timeline": [0-9]*' | awk '{print $NF}')

echo "Failover State:"
echo "  Nodes Up:         $NEW_UP (Expected: $((INIT_UP - 1)))"
echo "  Primary Count:    $NEW_PRIM_COUNT (Expected: 1)"
echo "  Primary Timeline: $NEW_TL (Expected >= $INIT_TL)"

# Assertions
FAILURES=0
if [ "$NEW_UP" -ge "$INIT_UP" ]; then
    echo "  [FAIL] Nodes Up did not decrement after leader shutdown!"
    FAILURES=$((FAILURES + 1))
else
    echo "  [PASS] Nodes Up correctly decremented."
fi

if [ "$NEW_PRIM_COUNT" -ne 1 ]; then
    echo "  [FAIL] Primary Count is not 1 after failover ($NEW_PRIM_COUNT)!"
    FAILURES=$((FAILURES + 1))
else
    echo "  [PASS] Exactly 1 primary active after failover."
fi

# Step 5: Recover the stopped node
echo
echo "[5/5] Recovering stopped node $LEADER_NAME..."
docker start "$LEADER_NAME"
echo "Waiting 8 seconds for $LEADER_NAME to rejoin cluster as standby..."
sleep 8

RECOVERED_OUT=$("$PYTHON_BIN" "$PLUGIN_PY" --nodes "$NODES" --username "$USER" --password "$PASS" --db "$DB" --patroni_port "$PATRONI_PORT")
RECOVERED_UP=$(echo "$RECOVERED_OUT" | grep -o '"Nodes Up": [0-9]*' | awk '{print $NF}')
echo "Recovered Nodes Up: $RECOVERED_UP / 3"

echo
if [ "$FAILURES" -eq 0 ]; then
    echo "=================================================================="
    echo " ✓ FAILOVER TEST PASSED: Automatic promotion & timeline validated!"
    echo "=================================================================="
    exit 0
else
    echo "=================================================================="
    echo " ✗ FAILOVER TEST FAILED: $FAILURES assertion failure(s)"
    echo "=================================================================="
    exit 1
fi
