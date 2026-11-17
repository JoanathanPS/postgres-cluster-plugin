. .\tester\il_disasm.ps1 > $null
$aes = $asm.GetType('Site24x7PluginAgent.Utils.AES')
$m = $aes.GetMethod('Decrypt', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

$sw = New-Object System.IO.StringWriter
$oldOut = [Console]::Out
[Console]::SetOut($sw)
[ILDisassembler]::Disassemble($m)
[Console]::SetOut($oldOut)

$lines = $sw.ToString() -split "`r?`n"
for ($i = 0; $i -lt $lines.Length; $i++) {
    Write-Host $lines[$i]
}

Write-Output "=== CreateHashKey ==="
$m2 = $aes.GetMethod('CreateHashKey', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')
[ILDisassembler]::Disassemble($m2)
