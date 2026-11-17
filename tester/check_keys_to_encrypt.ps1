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
    if ($lines[$i] -match 'keys_to_encrypt') {
        for ($j = [Math]::Max(0, $i - 10); $j -le [Math]::Min($lines.Length - 1, $i + 20); $j++) {
            Write-Host $lines[$j]
        }
        Write-Host "---"
    }
}
