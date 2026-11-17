. .\tester\il_disasm.ps1

$t = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $t.GetMethod('RunPluginandWriteForReg', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

$lines = [ILDisassembler]::Disassemble($m)
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match 'already registered') {
        Write-Host "Match at line $i"
        for ($j = [Math]::Max(0, $i - 20); $j -le [Math]::Min($lines.Count - 1, $i + 5); $j++) {
            Write-Host "$j : " $lines[$j]
        }
    }
}
