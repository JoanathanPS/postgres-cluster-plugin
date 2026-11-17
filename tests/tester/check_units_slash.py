import json

with open('tester/payload_sent_v6.json') as f:
    v6 = json.load(f)

units = v6.get('units', {})
invalid_units = []
for k, v in units.items():
    if isinstance(v, str):
        if '/' in v:
            invalid_units.append((k, v))
    elif isinstance(v, dict):
        for col, u in v.items():
            if '/' in u:
                invalid_units.append((f'{k}.{col}', u))

print('Units containing slash /:', invalid_units)
