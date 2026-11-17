. .\tester\il_disasm.ps1 > $null
$util = $asm.GetType('Site24x7PluginAgent.Utils.Util')
$m = $util.GetMethod('ReadConfFile', [System.Reflection.BindingFlags]'Public,NonPublic,Static')

$sw = New-Object System.IO.StringWriter
$oldOut = [Console]::Out
[Console]::SetOut($sw)
[ILDisassembler]::Disassemble($m)
[Console]::SetOut($oldOut)

$text = $sw.ToString()
$lines = $text -split "`r?`n"
for ($i = 0; $i -lt $lines.Length; $i++) {
    if ($lines[$i] -like '*IL_045*' -or $lines[$i] -like '*IL_046*' -or $lines[$i] -like '*IL_052*' -or $lines[$i] -like '*IL_053*') {
        for ($j = [Math]::Max(0, $i - 5); $j -le [Math]::Min($lines.Length - 1, $i + 5); $j++) {
            Write-Host $lines[$j]
        }
        Write-Host "---"
    }
}
