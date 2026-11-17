import json

with open('tester/payload_sent_v6.json') as f:
    v6 = json.load(f)

units = v6.get('units', {})
data = v6.get('data', {})

string_scalars_in_units = []
for k, v in data.items():
    if isinstance(v, str):
        if k in units:
            string_scalars_in_units.append((k, v, units[k]))

print('String scalar metrics in units:', string_scalars_in_units)

# Check tables
table_string_cols_in_units = []
for tname, rows in data.items():
    if isinstance(rows, list) and len(rows) > 0 and tname in units:
        t_units = units[tname]
        for col, val in rows[0].items():
            if isinstance(val, str) and col in t_units:
                table_string_cols_in_units.append((tname, col, val, t_units[col]))

print('Table string columns in units:', table_string_cols_in_units)
