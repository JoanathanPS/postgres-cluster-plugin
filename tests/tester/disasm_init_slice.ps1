$binDir = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64"
[System.Reflection.Assembly]::LoadFrom("$binDir\DotNetAgent.Util.dll") | Out-Null
$asm = [System.Reflection.Assembly]::LoadFrom("$binDir\Site24x7PluginAgent.exe")
. .\tester\il_disasm.ps1 > $null
$glob = $asm.GetType('Site24x7PluginAgent.Global')
$m = $glob.GetMethod('Init', [System.Reflection.BindingFlags]'Public,NonPublic,Instance')

$sw = New-Object System.IO.StringWriter
$oldOut = [Console]::Out
[Console]::SetOut($sw)
[ILDisassembler]::Disassemble($m)
[Console]::SetOut($oldOut)

$lines = $sw.ToString() -split "`r?`n"
Write-Output "Total disassembled lines: $($lines.Length)"
for ($i = 0; $i -lt $lines.Length; $i++) {
    if ($lines[$i] -match 'IL_02[0-4]') {
        Write-Output $lines[$i]
    }
}
