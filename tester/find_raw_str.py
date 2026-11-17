with open(r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe', 'rb') as f:
    data = f.read()

pos = data.find(b'already registered')
print("Position in x64:", pos)
if pos != -1:
    print(data[pos-50:pos+100])
