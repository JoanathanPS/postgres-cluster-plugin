$dll = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe"
$bytes = [System.IO.File]::ReadAllBytes($dll)
$asm = [System.Reflection.Assembly]::Load($bytes)
$mod = $asm.GetModules()[0]

$t = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $t.GetMethod('RunPluginandWriteForReg', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

$il = $m.GetMethodBody().GetILAsByteArray()

for ($i = 0x0320; $i -lt 0x0388; $i++) {
    $op = $il[$i]
    Write-Host "0x$($i.ToString('X4')): 0x$($op.ToString('X2'))"
}
