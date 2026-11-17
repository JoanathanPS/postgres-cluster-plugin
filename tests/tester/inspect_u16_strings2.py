path = r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\MonitoringAgent.exe'
with open(path, 'rb') as f:
    data = f.read()

import re
sub = data[4460000:4475000]
strings = re.findall(b'(?:[\x20-\x7e]\x00){4,}', sub)
for s in strings:
    print(s.decode('utf-16le'))
