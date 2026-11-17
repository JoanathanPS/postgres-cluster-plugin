$dll = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe"
$bytes = [System.IO.File]::ReadAllBytes($dll)
$asm = [System.Reflection.Assembly]::Load($bytes)
$mod = $asm.GetModules()[0]

$t = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $t.GetMethod('RunPluginandWriteForReg', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

$il = $m.GetMethodBody().GetILAsByteArray()
for ($i = 0; $i -lt $il.Length - 4; $i++) {
    if ($il[$i] -eq 0x72) {
        $token = [System.BitConverter]::ToInt32($il, $i + 1)
        try {
            $s = $mod.ResolveString($token)
            if ($s -match 'already registered') {
                Write-Host "Offset in IL: 0x$($i.ToString('X4'))"
                $targetOffset = $i
            }
        } catch {}
    }
}

. .\tester\il_disasm.ps1
$lines = [ILDisassembler]::Disassemble($m)
Write-Host "Total disassembled lines: $($lines.Count)"
for ($j = 0; $j -lt $lines.Count; $j++) {
    if ($lines[$j] -match 'already registered') {
        Write-Host "Line $j matches:"
        for ($k = [Math]::Max(0, $j - 35); $k -le [Math]::Min($lines.Count - 1, $j + 10); $k++) {
            Write-Host "$k : $($lines[$k])"
        }
    }
}
