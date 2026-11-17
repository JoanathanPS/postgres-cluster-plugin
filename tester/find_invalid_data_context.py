path = r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\MonitoringAgent.exe'
with open(path, 'rb') as f:
    data = f.read()

target = b'Invalid data'
idx = 0
while True:
    idx = data.find(target, idx)
    if idx == -1:
        break
    start = max(0, idx - 100)
    end = min(len(data), idx + 100)
    print(f'Match at offset {idx}:')
    print(data[start:end])
    print('---')
    idx += len(target)
