import subprocess
import os

plugin_path = r"C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster_v5\postgres_cluster_v5.py"
out_path = os.path.abspath("payload_inspect.json")

# Execute using exact configuration without exposing password
pw = "site24x7"
cmd = [
    "python",
    plugin_path,
    "--cluster_host", "127.0.0.1",
    "--postgres_port", "5442",
    "--patroni_port", "8002",
    "--username", "site24x7",
    "--password", pw,
    "--db", "postgres",
    "--compat_official", "1",
    "--address_map", "pg-node1:5432=127.0.0.1:5441,pg-node1:8008=127.0.0.1:8001,pg-node2:5432=127.0.0.1:5442,pg-node2:8008=127.0.0.1:8002,pg-node3:5432=127.0.0.1:5443,pg-node3:8008=127.0.0.1:8003",
    "--json-out", out_path
]

res = subprocess.run(cmd, capture_output=True, text=True)
print(f"Plugin finished with exit code {res.returncode}")
print(f"Output saved to {out_path} (exists: {os.path.exists(out_path)}, size: {os.path.getsize(out_path)} bytes)")
if res.stderr:
    print(f"Stderr: {res.stderr[:200]}")
