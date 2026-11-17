import json, subprocess

# Run official plugin
res_off = subprocess.run(['python', 'postgres/postgres.py', '--host', '127.0.0.1', '--port', '5432', '--username', 'site24x7', '--password', 'site24x7_password'], capture_output=True, text=True)
data_off = json.loads(res_off.stdout)

# Run cluster plugin with compat_official=1
res_cluster = subprocess.run(['python', 'postgres_cluster/postgres_cluster.py', '--host', '127.0.0.1', '--port', '5432', '--username', 'site24x7', '--password', 'site24x7_password', '--compat_official', '1'], capture_output=True, text=True)
data_cluster = json.loads(res_cluster.stdout)

reserved = {'plugin_version', 'heartbeat_required', 'status', 'msg', 'units', 'tabs', 's4z7config', 's247config'}
off_metrics = {k: v for k, v in data_off.items() if k not in reserved and not isinstance(v, (dict, list))}
cluster_metrics = {k: v for k, v in data_cluster.items() if k not in reserved and not isinstance(v, (dict, list))}

print("=== GATE 9 VERIFICATION ===")
print(f"(a) Emitted metric count with compat_official=1: {len(cluster_metrics)} (Cap: 200)")
print(f"    Emitted table count with compat_official=1: {len([k for k, v in data_cluster.items() if isinstance(v, list)])} (Cap: 10)")

print("\n(b) & (c) Legacy metric comparison side-by-side:")
print(f"{'Metric Name':<35} | {'Official postgres.py':<22} | {'Cluster Plugin (compat=1)':<25} | Agree?")
print("-" * 98)

disagreements = []
for k in sorted(off_metrics.keys()):
    v_off = off_metrics.get(k)
    v_cl = cluster_metrics.get(k)
    agree = False
    if v_cl is not None:
        try:
            f_off = float(v_off)
            f_cl = float(v_cl)
            # Allow small counter drift between consecutive executions
            agree = (abs(f_off - f_cl) <= max(10.0, 0.05 * max(abs(f_off), 1.0)))
        except (ValueError, TypeError):
            agree = (str(v_off) == str(v_cl))
    status_str = "YES" if agree else ("DRIFT/DIFF" if v_cl is not None else "MISSING")
    print(f"{k:<35} | {str(v_off):<22} | {str(v_cl):<25} | {status_str}")
    if v_cl is None:
        disagreements.append(k)

print(f"\nMissing legacy metrics: {disagreements}")
print(f"Confirmation all official metrics present: {len(disagreements) == 0}")
print(f"Confirmation numeric types in cluster plugin: {all(isinstance(v_cl, (int, float)) for k, v_cl in cluster_metrics.items() if k in off_metrics and k != 'Server Version')}")

# Run cluster plugin with compat_official=0
res_cluster_0 = subprocess.run(['python', 'postgres_cluster/postgres_cluster.py', '--host', '127.0.0.1', '--port', '5432', '--username', 'site24x7', '--password', 'site24x7_password', '--compat_official', '0'], capture_output=True, text=True)
data_cluster_0 = json.loads(res_cluster_0.stdout)
cluster_metrics_0 = {k: v for k, v in data_cluster_0.items() if k not in reserved and not isinstance(v, (dict, list))}
print(f"\n(d) Emitted metric count with compat_official=0: {len(cluster_metrics_0)} (Cap: 200)")
print(f"    Any legacy metrics present with compat_official=0?: {any(k in cluster_metrics_0 for k in off_metrics.keys())}")
