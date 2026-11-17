import json

with open('tester/payload_v4.json') as f:
    v4 = json.load(f)

print('V4 Transactions_Per_Database cols:')
print(list(v4['data']['Transactions_Per_Database'][0].keys()))
print('V4 units for Transactions_Per_Database:')
print(v4['units']['Transactions_Per_Database'])
