path = r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\MonitoringAgent.exe'
with open(path, 'rb') as f:
    data = f.read()

target1 = b'Invalid data'
target2 = 'Invalid data'.encode('utf-16le')

print('In MonitoringAgent.exe (ASCII):', target1 in data)
print('In MonitoringAgent.exe (UTF16):', target2 in data)
