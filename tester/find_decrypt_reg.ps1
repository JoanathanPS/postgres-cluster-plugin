$sw = New-Object System.IO.StringWriter
$oldOut = [Console]::Out
[Console]::SetOut($sw)

. .\tester\il_disasm.ps1 > $null
$dc = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $dc.GetMethod('RunPluginandWriteToRegFile', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')
[ILDisassembler]::Disassemble($m)

[Console]::SetOut($oldOut)
$text = $sw.ToString()
$lines = $text -split "`r?`n"
$matchLines = $lines | Select-String -Pattern 'Decrypt|encrypted|Crypto|AES'
Write-Host "Matches found: $($matchLines.Count)"
foreach ($ml in $matchLines) {
    Write-Host $ml
}
