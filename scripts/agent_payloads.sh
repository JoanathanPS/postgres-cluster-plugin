#!/bin/bash
# Captures what the local Site24x7 Windows agent actually sends for every
# `postgres` monitor at its next poll (the agent deletes each file within
# seconds of writing it), then prints one line per monitor.
# Usage: bash scripts/agent_payloads.sh [expected_monitor_count]
D="/c/Program Files (x86)/Site24x7/WinAgent/monitoring/bin/PluginData"
OUT="${TMPDIR:-/tmp}/agent_payloads"; mkdir -p "$OUT"; rm -f "$OUT"/*
N="${1:-6}"; start=$(date +%s)
until [ "$(ls "$OUT" | wc -l)" -ge "$N" ] || [ $(( $(date +%s) - start )) -gt 420 ]; do
  cp -n "$D"/Plugin_*.txt "$OUT/" 2>/dev/null; sleep 0.5
done
python - "$OUT" <<'PY'
import json, os, sys
for f in sorted(os.listdir(sys.argv[1])):
    raw = open(os.path.join(sys.argv[1], f), "rb").read()
    wrap = None
    for enc in ("utf-16", "utf-8"):
        try:
            text = raw.decode(enc); wrap = json.loads(text[text.find("{"):]); break
        except Exception:
            pass
    if not wrap:
        print(f, "unparsed"); continue
    d = wrap.get("data", {})
    print("%s avail=%s ver=%s type=%s health=%s metrics=%d tables=%d nodes=%s msg=%s" % (
        f.split("_")[1][:8], wrap.get("availability"), wrap.get("version"), d.get("Cluster Type"),
        d.get("Health Code"), len([k for k, v in d.items() if not isinstance(v, (dict, list))]),
        len([v for v in d.values() if isinstance(v, list)]),
        [(r["name"], r["role"], r["state"]) for r in d.get("Nodes", [])], wrap.get("msg", "")[:80]))
print("full payloads kept in", sys.argv[1])
PY
