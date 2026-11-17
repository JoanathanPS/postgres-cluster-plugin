import json

with open('tester/payload_v4.json') as f:
    v4 = json.load(f)
with open('tester/payload_sent_v6.json') as f:
    v6 = json.load(f)

print('=== V4 KEYS ===')
print('Top level keys:', list(v4.keys()))

print('=== V6 KEYS ===')
print('Top level keys:', list(v6.keys()))

print('\n=== TABS ===')
print('v4 tabs:', v4['data'].get('tabs'))
print('v6 tabs:', v6['data'].get('tabs'))

print('\n=== S247CONFIG ===')
print('v4 s247config:', v4['data'].get('s247config'))
print('v6 s247config:', v6['data'].get('s247config'))

print('\n=== DATA VALUE TYPES ===')
for k, v in v6['data'].items():
    if k in ('tabs', 's247config'): continue
    if isinstance(v, list):
        print(f'Table {k}: len={len(v)}')
        if len(v) > 0:
            print(f'  First row keys: {list(v[0].keys())}')
            # check row values
            for col, val in v[0].items():
                if val is None:
                    print(f'    NULL in table {k}, column {col}!')
    elif isinstance(v, dict):
        print(f'Dict metric {k}: {v}')
    elif v is None:
        print(f'NULL scalar metric: {k}')

print('\n=== V4 TABLES ===')
for k, v in v4['data'].items():
    if isinstance(v, list):
        print(f'V4 Table {k}: len={len(v)}')
