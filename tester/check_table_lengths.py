import json

with open('tester/payload_sent_v6.json') as f:
    v6 = json.load(f)

print('=== V6 TABLES ===')
for k, v in v6['data'].items():
    if isinstance(v, list):
        print(f'Table: {k} (len {len(k)})')
        if len(v) > 0:
            for col in v[0].keys():
                if len(col) > 25:
                    print(f'  Col > 25: {col} ({len(col)})')

print('=== V6 UNITS KEYS ===')
for k, v in v6.get('units', {}).items():
    if len(k) > 25:
        print(f'Units key > 25: {k} ({len(k)})')
    if isinstance(v, dict):
        for col in v.keys():
            if len(col) > 25:
                print(f'  Units table {k} col > 25: {col} ({len(col)})')
