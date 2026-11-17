import re

for exe in ['MonitoringAgent.exe', 'Site24x7PluginAgent.exe']:
    path = rf'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\{exe}'
    with open(path, 'rb') as f:
        data = f.read().decode('latin1', errors='ignore')
    matches = set(re.findall(r'(?:RegisterPlugin|PluginDetails|PluginRegister|PluginServlet|error_msg)[^\x00]{0,80}', data))
    print(f"=== {exe} ===")
    for m in sorted(matches)[:20]:
        print(m)
