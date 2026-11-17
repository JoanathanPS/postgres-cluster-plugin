import json
import os

details_path = r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\PluginDetails\PluginDetails.txt'
inv_path = r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\conf\Plugininventory\Plugininventory.txt'

def read_json_any(path):
    for enc in ['utf-16le', 'utf-16', 'utf-8-sig', 'utf-8', 'latin1']:
        try:
            with open(path, 'r', encoding=enc) as f:
                content = f.read().strip()
                if not content:
                    return {}, enc
                return json.loads(content), enc
        except Exception:
            continue
    raise ValueError(f"Could not read {path}")

details, det_enc = read_json_any(details_path)
details["postgres_cluster_v6"] = {
    "displayname": "postgres_cluster_v6-Joana-PC.",
    "pluginkey": "05c3fc2441167c1ae188d3e124adceaf",
    "plugin_name": "postgres_cluster_v6",
    "JsonCount": "0",
    "status": "0",
    "timeout": "50",
    "heartbeat": "True",
    "heartbeat_required": "true",
    "script_timeout": "50",
    "poll_interval": "300",
    "dcinterval": "300",
    "version": "6"
}
with open(details_path, 'w', encoding=det_enc) as f:
    json.dump(details, f)
print("Set postgres_cluster_v6 to status 0 in PluginDetails.txt")

if os.path.exists(inv_path):
    inv, inv_enc = read_json_any(inv_path)
    inv["postgres_cluster_v6"] = {
        "displayname": "postgres_cluster_v6-Joana-PC.",
        "pluginkey": "05c3fc2441167c1ae188d3e124adceaf",
        "plugin_name": "postgres_cluster_v6",
        "JsonCount": "0",
        "status": "0",
        "timeout": "50",
        "heartbeat_required": "true",
        "script_timeout": "50",
        "poll_interval": "300",
        "dcinterval": "300",
        "version": "6"
    }
    with open(inv_path, 'w', encoding=inv_enc) as f:
        json.dump(inv, f)
    print("Set postgres_cluster_v6 to status 0 in Plugininventory.txt")
