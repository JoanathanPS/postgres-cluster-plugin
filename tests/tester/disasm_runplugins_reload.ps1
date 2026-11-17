$dll = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe"
$bytes = [System.IO.File]::ReadAllBytes($dll)
$asm = [System.Reflection.Assembly]::Load($bytes)
$mod = $asm.GetModules()[0]

$t = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $t.GetMethod('RunPlugins', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

$il = $m.GetMethodBody().GetILAsByteArray()

for ($i = 0x0250; $i -le 0x02DF; $i++) {
    $op = $il[$i]
    if ($op -eq 0x72) {
        $tok = [System.BitConverter]::ToInt32($il, $i+1)
        try {
            $s = $mod.ResolveString($tok)
            Write-Host "0x$($i.ToString('X4')): ldstr `"$s`""
        } catch {}
    } elseif ($op -eq 0x28) {
        $tok = [System.BitConverter]::ToInt32($il, $i+1)
        try {
            $mb = $mod.ResolveMethod($tok)
            Write-Host "0x$($i.ToString('X4')): call $($mb.DeclaringType.Name)::$($mb.Name)"
        } catch {}
    }
}
