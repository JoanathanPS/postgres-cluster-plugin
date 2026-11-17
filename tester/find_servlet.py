with open(r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\MonitoringAgent.exe', 'rb') as f:
    data = f.read()

for enc, name in [(b'P\x00l\x00u\x00g\x00i\x00n\x00S\x00e\x00r\x00v\x00l\x00e\x00t', 'utf16'), (b'PluginServlet', 'ascii')]:
    pos = 0
    while True:
        pos = data.find(enc, pos)
        if pos == -1:
            break
        print(f"Found {name} at {pos}")
        start = max(0, pos - 200)
        end = min(len(data), pos + 300)
        chunk = data[start:end]
        if name == 'utf16':
            try:
                print(chunk.decode('utf-16le', errors='ignore'))
            except Exception as e:
                print(e)
        else:
            print(chunk.decode('latin1', errors='ignore'))
        pos += 1
