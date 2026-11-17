. .\tester\il_disasm.ps1 > $null
$globalType = $asm.GetType('Site24x7PluginAgent.Global')
$m = $globalType.GetMethod('Init', [System.Reflection.BindingFlags]'Public,NonPublic,Static')

$sw = New-Object System.IO.StringWriter
$oldOut = [Console]::Out
[Console]::SetOut($sw)
[ILDisassembler]::Disassemble($m)
[Console]::SetOut($oldOut)

$lines = $sw.ToString() -split "`r?`n"
for ($i = 0; $i -lt $lines.Length; $i++) {
    if ($lines[$i] -match 'seckey') {
        for ($j = [Math]::Max(0, $i - 5); $j -le [Math]::Min($lines.Length - 1, $i + 5); $j++) {
            Write-Host $lines[$j]
        }
        Write-Host "---"
    }
}
