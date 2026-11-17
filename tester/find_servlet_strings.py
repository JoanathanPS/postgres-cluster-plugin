with open(r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\MonitoringAgent.exe', 'rb') as f:
    f.seek(4463500)
    chunk = f.read(8000)

print(chunk.decode('utf-16le', errors='ignore'))
