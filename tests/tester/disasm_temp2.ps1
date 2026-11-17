
$dll = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe"
$bytes = [System.IO.File]::ReadAllBytes($dll)
$asm = [System.Reflection.Assembly]::Load($bytes)
$t = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $t.GetMethod('RunPluginandWriteForReg', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

. .\tester\il_disasm.ps1
$lines = [ILDisassembler]::Disassemble($m)
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match 'already registered') {
        Write-Host "FOUND AT $i"
        for ($j = [Math]::Max(0, $i - 20); $j -le [Math]::Min($lines.Count - 1, $i + 10); $j++) {
            Write-Host "$j : $($lines[$j])"
        }
    }
}
