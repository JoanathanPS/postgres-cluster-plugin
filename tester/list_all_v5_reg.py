import glob, os, json

files = sorted(glob.glob(r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\logs\Details\PluginRegisterLog*.log'))
for f in files:
    with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
        for idx, line in enumerate(fp):
            if 'postgres_cluster_v5' in line and 'output for' in line:
                payload_str = line.split('is ', 1)[1].strip()
                d = json.loads(payload_str)
                data_obj = d.get('data', {}) if 'data' in d else d
                tabs = data_obj.get('tabs', {})
                ts = line[:19]
                print(f"{ts} | {os.path.basename(f)}:{idx+1} | tabs ({len(tabs)}): {list(tabs.keys())}")
