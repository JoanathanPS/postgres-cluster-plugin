$dll = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe"
$bytes = [System.IO.File]::ReadAllBytes($dll)
$asm = [System.Reflection.Assembly]::Load($bytes)
$mod = $asm.GetModules()[0]
$t = $asm.GetType('Site24x7PluginAgent.Global')
$m = $t.TypeInitializer
if ($m) {
    $il = $m.GetMethodBody().GetILAsByteArray()
    for ($i = 0; $i -lt $il.Length - 4; $i++) {
        if ($il[$i] -eq 0x72) {
            $tok = [System.BitConverter]::ToInt32($il, $i+1)
            try {
                $s = $mod.ResolveString($tok)
                Write-Host "ldstr: $s"
            } catch {}
        }
    }
}
