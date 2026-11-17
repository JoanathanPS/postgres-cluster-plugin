. .\tester\il_disasm.ps1 > $null
$dc = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $dc.GetMethod('CheckPluginForRegister', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

$sw = New-Object System.IO.StringWriter
$oldOut = [Console]::Out
[Console]::SetOut($sw)
[ILDisassembler]::Disassemble($m)
[Console]::SetOut($oldOut)

$lines = $sw.ToString() -split "`r?`n"
for ($i = 0; $i -lt $lines.Length; $i++) {
    if ($lines[$i] -match 'instanceData|ReadConfFile|ConfigToHashTable') {
        for ($j = [Math]::Max(0, $i - 3); $j -le [Math]::Min($lines.Length - 1, $i + 3); $j++) {
            Write-Host $lines[$j]
        }
        Write-Host "---"
    }
}
