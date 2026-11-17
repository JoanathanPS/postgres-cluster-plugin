import os

for root, dirs, files in os.walk(r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin'):
    for f in files:
        if f.endswith(('.exe', '.dll')):
            p = os.path.join(root, f)
            with open(p, 'rb') as fp:
                content = fp.read()
                pos = 0
                while True:
                    pos = content.find(b'already', pos)
                    if pos == -1:
                        break
                    print(f"In {f} at {pos}: {content[pos-20:pos+50]}")
                    pos += 1
