import json

with open('tester/payload_sent_v6.json') as f:
    v6 = json.load(f)

units = v6.get('units', {})
data = v6.get('data', {})

data_tables = [k for k, v in data.items() if isinstance(v, list)]
units_tables = [k for k, v in units.items() if isinstance(v, dict)]

print('Data tables:', data_tables)
print('Units tables:', units_tables)

diff1 = set(data_tables) - set(units_tables)
print('Data tables not in units:', diff1)
diff2 = set(units_tables) - set(data_tables)
print('Units tables not in data:', diff2)
