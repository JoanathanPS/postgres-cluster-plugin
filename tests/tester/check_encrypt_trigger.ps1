. .\tester\il_disasm.ps1 > $null
$util = $asm.GetType('Site24x7PluginAgent.Utils.Util')
$m = $util.GetMethod('ReadConfFile', [System.Reflection.BindingFlags]'Public,NonPublic,Static')

$sw = New-Object System.IO.StringWriter
$oldOut = [Console]::Out
[Console]::SetOut($sw)
[ILDisassembler]::Disassemble($m)
[Console]::SetOut($oldOut)

$lines = $sw.ToString() -split "`r?`n"
for ($i = 0; $i -lt $lines.Length; $i++) {
    if ($lines[$i] -match 'IL_03[5-9]' -or $lines[$i] -match 'IL_03A' -or $lines[$i] -match 'IL_03B' -or $lines[$i] -match 'IL_03C' -or $lines[$i] -match 'IL_03D') {
        Write-Host $lines[$i]
    }
}
