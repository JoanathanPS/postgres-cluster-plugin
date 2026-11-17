path = r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\MonitoringAgent.exe'
with open(path, 'rb') as f:
    data = f.read()

target = 'PluginsRegisterThread'.encode('utf-16le')
idx = data.find(target)
if idx != -1:
    print('Found at', idx)
    # search backwards and forwards for null-terminated utf16 strings
    start = max(0, idx - 2000)
    end = min(len(data), idx + 2000)
    sub = data[start:end]
    # find utf-16 strings
    import re
    # extract ASCII strings encoded as utf-16le
    strings = re.findall(b'(?:[\x20-\x7e]\x00){4,}', sub)
    for s in strings:
        print(s.decode('utf-16le'))
