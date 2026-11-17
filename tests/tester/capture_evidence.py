import os
import sys
import subprocess
import json

python_exe = sys.executable
plugin_script = r"C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster_v6\postgres_cluster_v6.py"

args = [
    python_exe,
    plugin_script,
    '--cluster_host=127.0.0.1',
    '--postgres_port=5441',
    '--patroni_port=8001',
    '--username=postgres',
    '--password=postgres_password',
    '--db=postgres',
    '--compat_official=1',
    '--address_map=pg-node1:5432=127.0.0.1:5441,pg-node1:8008=127.0.0.1:8001,pg-node2:5432=127.0.0.1:5442,pg-node2:8008=127.0.0.1:8002,pg-node3:5432=127.0.0.1:5443,pg-node3:8008=127.0.0.1:8003',
    '--json-out=out_agent.json'
]

proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
stdout, stderr = proc.communicate()
rc = proc.returncode

print(f"EXIT CODE: {rc}")
print(f"STDERR LENGTH: {len(stderr)}")
if stderr:
    print(f"STDERR CONTENT:\n{stderr}")

try:
    data = json.loads(stdout)
    print("STDOUT PARSED SUCCESSFULLY AS JSON")
    print(f"Availability/Status: {data.get('status')}")
    print(f"Version: {data.get('version')}")
    print(f"Msg: {data.get('msg')}")
    print(f"Tabs count: {len(data.get('tabs', {}))}")
    print(f"Units count: {len(data.get('units', {}))}")
    cd = data.get('s247config', {}).get('childdiscovery', [])
    print(f"Child discovery tables: {cd}")
    
    # Count metrics
    parent_metrics = [k for k, v in data.items() if not isinstance(v, (dict, list)) and k not in ('status', 'version', 'msg')]
    print(f"Parent metrics count: {len(parent_metrics)}")
    
    child_tables = {k: len(v) for k, v in data.items() if isinstance(v, list) and k not in ('msg',)}
    print("Child tables row counts:")
    for ct, cnt in child_tables.items():
        print(f"  {ct}: {cnt} rows")

    # Check attribute lengths
    long_keys = [k for k in data.keys() if len(k) > 25]
    print(f"Attributes > 25 chars: {long_keys} (Total: {len(long_keys)})")

    # Check child column lengths
    long_cols = []
    for ct, rows in data.items():
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    for col in row.keys():
                        if len(col) > 25:
                            long_cols.append(f"{ct}.{col}")
    print(f"Child columns > 25 chars: {set(long_cols)} (Total: {len(set(long_cols))})")
    
except Exception as e:
    print(f"FAILED TO PARSE JSON: {e}")
    print("RAW STDOUT:\n", stdout[:500])
