#!/bin/bash
# Runs the plugin from inside a test bed's Docker network (like an agent on the
# same network), so container addresses need no address_map.
# Usage: bash scripts/run_in_network.sh <docker-network> --host <container> [plugin args]
# One-time: docker build -t pgplugin-runner scripts/runner
export MSYS_NO_PATHCONV=1
NET="$1"; shift
docker run --rm --network "$NET" -v "$(cd "$(dirname "$0")/.." && pwd)/postgres:/plugin" \
  pgplugin-runner python /plugin/postgres.py "$@"
