import os

target = b'PluginsRegisterThread'
root = r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin'
for r, ds, fs in os.walk(root):
    for f in fs:
        fp = os.path.join(r, f)
        try:
            with open(fp, 'rb') as fp_obj:
                data = fp_obj.read()
                if target in data:
                    print('Found in:', fp)
        except:
            pass
