import json

with open('tester/payload_sent_v6.json') as f:
    v6 = json.load(f)

long_keys_v6 = []
for k in v6['data'].keys():
    if len(k) > 25:
        long_keys_v6.append((k, len(k)))

print(f'V6 keys > 25 chars ({len(long_keys_v6)} keys):')
for k, l in sorted(long_keys_v6, key=lambda x: -x[1]):
    print(f'  {k} ({l} chars)')

with open('tester/payload_v4.json') as f:
    v4 = json.load(f)

long_keys_v4 = []
for k in v4['data'].keys():
    if len(k) > 25:
        long_keys_v4.append((k, len(k)))

print(f'\nV4 keys > 25 chars ({len(long_keys_v4)} keys):')
for k, l in sorted(long_keys_v4, key=lambda x: -x[1]):
    print(f'  {k} ({l} chars)')
