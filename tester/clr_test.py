import clr
clr.AddReference(r"C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe")
import Site24x7PluginAgent
from System.Reflection import BindingFlags

found = False
for t in Site24x7PluginAgent.__dict__.values():
    if hasattr(t, 'GetMethods'):
        for m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance):
            body = m.GetMethodBody()
            if body:
                il = bytes(body.GetILAsByteArray())
                # In IL, string tokens are ldstr 0x70XXXXXX
                # Let's see if we can resolve strings
                pass
