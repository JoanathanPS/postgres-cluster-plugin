$dll = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe"
$bytes = [System.IO.File]::ReadAllBytes($dll)
$asm = [System.Reflection.Assembly]::Load($bytes)
$mod = $asm.GetModules()[0]

$t = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $t.GetMethod('RunPluginandWriteForReg', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

$il = $m.GetMethodBody().GetILAsByteArray()

# Print around 0x0388
Write-Host "IL bytes around 0x0388:"
for ($i = 0x0350; $i -le 0x03B0; $i++) {
    $b = $il[$i]
    if ($b -eq 0x72) {
        $tok = [System.BitConverter]::ToInt32($il, $i+1)
        try {
            $s = $mod.ResolveString($tok)
            Write-Host "0x$($i.ToString('X4')): ldstr `"$s`""
        } catch {
            Write-Host "0x$($i.ToString('X4')): ldstr (unresolved)"
        }
    } elseif ($b -eq 0x28) {
        $tok = [System.BitConverter]::ToInt32($il, $i+1)
        try {
            $mb = $mod.ResolveMethod($tok)
            Write-Host "0x$($i.ToString('X4')): call $($mb.DeclaringType.Name)::$($mb.Name)"
        } catch {
            Write-Host "0x$($i.ToString('X4')): call (unresolved)"
        }
    }
}
