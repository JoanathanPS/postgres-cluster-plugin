import os

for root, dirs, files in os.walk(r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin'):
    for f in files:
        if f.endswith(('.exe', '.dll')):
            p = os.path.join(root, f)
            try:
                with open(p, 'rb') as fp:
                    content = fp.read()
                    if b'already registered' in content:
                        print(f"FOUND IN: {p}")
            except Exception:
                pass
