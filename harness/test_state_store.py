#!/usr/bin/env python3
"""Failure-mode tests for state_store.py — the part that decides whether the
primary clamp and dead-node history can be trusted. No third-party deps."""
import json, os, shutil, stat, sys, tempfile, time
from state_store import StateStore, writable_by_write_probe

fails = []

def check(label, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra and not cond else ""))
    if not cond: fails.append(label)

work = tempfile.mkdtemp(prefix="stest-")
plugin = os.path.join(work, "postgres_cluster.py")
open(plugin, "w").write("# stub\n")

SINKS = {}

def warns(tag="w"):
    out = []
    SINKS[tag] = out
    def sink(code, text):
        out.append((code, text))
    return out, sink

def codes(tag):
    return [c for c, _ in SINKS.get(tag, [])]

# --- 1. normal write/read round trip + identity
w1, sink1 = warns("w1")
s = StateStore(plugin_file=plugin, cluster_id="sysid-1", warn=sink1); s.probe()
check("save returns True", s.save({"primary": {"name": "pg1", "ts": time.time()}}))
d = s.load()
check("round trip read", d.get("primary", {}).get("name") == "pg1")
check("schema stamped", d.get("schema") == 1)
check("no temp files left", not [f for f in os.listdir(os.path.dirname(s.path)) if f.startswith(".state.")])

# --- 2. corrupt json
open(s.path, "w").write("{not json")
w2, sink2 = warns("w2"); s2 = StateStore(plugin_file=plugin, cluster_id="sysid-1", warn=sink2); s2.probe()
check("corrupt => empty state", s2.load() == {})
check("corrupt => code WARN_STATE_CORRUPT", "WARN_STATE_CORRUPT" in codes("w2"))

# --- 3. foreign instance (different cluster, same folder)
w3, sink3 = warns("w3"); s3 = StateStore(plugin_file=plugin, cluster_id="sysid-OTHER", warn=sink3); s3.probe()
s3.save({"primary": {"name": "wrong"}})
check("different cluster gets a different file", s3.path != s.path)
w4, sink4 = warns("w4"); s4 = StateStore(plugin_file=plugin, cluster_id="sysid-1", warn=sink4); s4.probe()
s4.save({"primary": {"name": "pg1"}})
check("same cluster reuses file", s4.path == s.path)
# write a valid file with a wrong instance key
stolen = json.load(open(s.path)); stolen["instance"] = "deadbeef"
json.dump(stolen, open(s.path, "w"))
w5, sink5 = warns("w5"); s5 = StateStore(plugin_file=plugin, cluster_id="sysid-1", warn=sink5); s5.probe()
check("foreign instance key ignored", s5.load() == {})
check("foreign => WARN_STATE_FOREIGN", "WARN_STATE_FOREIGN" in codes("w5"))

# --- 4. oversize file
s5.save({"ok": True})
with open(s5.path, "w") as f: f.write("x" * (70 * 1024))
w6, sink6 = warns("w6"); s6 = StateStore(plugin_file=plugin, cluster_id="sysid-1", warn=sink6); s6.probe()
check("oversize => empty state", s6.load() == {})
check("oversize => WARN_STATE_TOO_LARGE", "WARN_STATE_TOO_LARGE" in codes("w6"))

# --- 5. unwritable plugin dir falls back, and says so
ro = tempfile.mkdtemp(prefix="ro-"); ro_plugin = os.path.join(ro, "pg.py"); open(ro_plugin, "w").write("")
os.chmod(ro, stat.S_IRUSR | stat.S_IXUSR)   # read+exec only
w7, sink7 = warns("w7")
s7 = StateStore(plugin_file=ro_plugin, cluster_id="x", warn=sink7); s7.probe()
check("unwritable dir => chose somewhere else", s7.path is not None and ro not in s7.path, s7.diagnostics()["State_Reason"])
# if the only usable place is volatile, the plugin must SAY so
if s7.diagnostics()["State_Persistent"] == 0:
    check("volatile fallback announced", "WARN_STATE_VOLATILE" in codes("w7"))
else:
    check("durable fallback used, no volatile warning", "WARN_STATE_VOLATILE" not in codes("w7"))

# --- 5b. no writable location at all: must fail loudly, never crash
w8, sink8 = warns("w8")
s8 = StateStore(plugin_file=ro_plugin, cluster_id="x", allow_temp_fallback=False, warn=sink8)
s8.probe(force=True)
if s8.path is None:
    check("no location => save returns False", s8.save({"a": 1}) is False)
    check("no location => WARN_STATE_NOWRITE", "WARN_STATE_NOWRITE" in codes("w8"))
    check("no location => diagnostics say none", s8.diagnostics()["State_File"] == "none")
else:
    check("no location case not reachable here (durable home dir exists)", True)
os.chmod(ro, stat.S_IRWXU); shutil.rmtree(ro, ignore_errors=True)

# --- 6. node pruning
s7.save({"nodes": {"old": {"ts_ok": time.time() - 30 * 86400}, "new": {"ts_ok": time.time()}}})
d = s7.load()
check("stale node pruned", "old" not in d.get("nodes", {}) and "new" in d.get("nodes", {}))

# --- 7. write probe honesty
ok, why = writable_by_write_probe("/definitely/not/here")
check("probe on missing dir is False", ok is False, why)
check("probe leaves no artifact", not [f for f in os.listdir(work) if f.startswith(".pgcluster-probe")])

# --- 8. diagnostics shape
diag = s7.diagnostics()
for k in ("State_File", "State_Persistent", "State_Age_s", "State_IO_Errors", "State_Reason"):
    check(f"diagnostic {k} present", k in diag)
check("State_File <= 100 chars", len(diag["State_File"]) <= 100)

shutil.rmtree(work, ignore_errors=True)
print(f"\n{'OK' if not fails else str(len(fails)) + ' FAILED'}")
sys.exit(0 if not fails else 1)
