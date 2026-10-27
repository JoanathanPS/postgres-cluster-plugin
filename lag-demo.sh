#!/bin/bash
# Shell wrapper for running the pgbench replication lag demonstration
set -e

PYTHON_BIN="python3"
if ! command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

"$PYTHON_BIN" "$(dirname "$0")/tester/lag_demo.py"
