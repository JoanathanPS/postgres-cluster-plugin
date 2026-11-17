with open(r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\MonitoringAgent.exe', 'rb') as f:
    data = f.read()

for enc in [b'D\x00a\x00t\x00a\x00A\x00g\x00e\x00n\x00t\x00H\x00a\x00n\x00d\x00l\x00e\x00r', b'S\x00e\x00n\x00d\x00P\x00l\x00u\x00g\x00i\x00n\x00I\x00n\x00v\x00e\x00n\x00t\x00o\x00r\x00y']:
    pos = 0
    while True:
        pos = data.find(enc, pos)
        if pos == -1:
            break
        print(f"Found at {pos}")
        chunk = data[pos-100:pos+1500]
        print(chunk.decode('utf-16le', errors='ignore'))
        pos += 1
