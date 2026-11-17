path = r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster_v4\postgres_cluster_v4.py'
with open(path, 'r', encoding='utf-8') as f:
    code = f.read()

for i, line in enumerate(code.splitlines()):
    if '"msg"' in line or "'msg'" in line:
        print(f'{i+1}: {line}')
