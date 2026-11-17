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
        except Exception as e:
            continue
    raise ValueError(f"Could not read {path}")

details, det_enc = read_json_any(details_path)
print("Read PluginDetails with encoding:", det_enc)
print("Original PluginDetails keys:", list(details.keys()))

if "postgres_cluster_v6-postgres_cluster" in details:
    del details["postgres_cluster_v6-postgres_cluster"]
    print("Deleted ghost postgres_cluster_v6-postgres_cluster from PluginDetails")

details["postgres_cluster_v6"] = {
    "displayname": "postgres_cluster_v6-Joana-PC.",
    "pluginkey": "NULL",
    "plugin_name": "postgres_cluster_v6",
    "JsonCount": "0",
    "status": "2",
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
print("Updated PluginDetails.txt successfully")

if os.path.exists(inv_path):
    inv, inv_enc = read_json_any(inv_path)
    print("Read Plugininventory with encoding:", inv_enc)
    if "postgres_cluster_v6-postgres_cluster" in inv:
        del inv["postgres_cluster_v6-postgres_cluster"]
        print("Deleted ghost postgres_cluster_v6-postgres_cluster from Plugininventory")

    inv["postgres_cluster_v6"] = {
        "displayname": "postgres_cluster_v6-Joana-PC.",
        "pluginkey": "NULL",
        "plugin_name": "postgres_cluster_v6",
        "JsonCount": "0",
        "status": "2",
        "timeout": "50",
        "heartbeat_required": "true",
        "script_timeout": "50",
        "poll_interval": "300",
        "dcinterval": "300",
        "version": "6"
    }

    with open(inv_path, 'w', encoding=inv_enc) as f:
        json.dump(inv, f)
    print("Updated Plugininventory.txt successfully")
