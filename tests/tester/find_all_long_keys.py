import json
import subprocess

# Run postgres_cluster.py locally and inspect all keys in the emitted output
p = subprocess.run(['python', 'postgres_cluster/postgres_cluster.py'], capture_output=True, text=True)
output = p.stdout.strip()

# find first '{'
idx = output.find('{')
if idx != -1:
    d = json.loads(output[idx:])
    long_keys = []
    for k in d.keys():
        if len(k) > 25:
            long_keys.append(('top_key', k, len(k)))
    for k, v in d.get('units', {}).items():
        if len(k) > 25:
            long_keys.append(('units_key', k, len(k)))
        if isinstance(v, dict):
            for col in v.keys():
                if len(col) > 25:
                    long_keys.append((f'units_{k}_col', col, len(col)))
    for k, v in d.items():
        if isinstance(v, list) and len(v) > 0:
            for col in v[0].keys():
                if len(col) > 25:
                    long_keys.append((f'table_{k}_col', col, len(col)))
    
    print('Total long keys (> 25):', len(long_keys))
    for t, k, l in long_keys:
        print(f'  [{t}] {k} -> {l} chars')
else:
    print('Failed to find JSON output')
