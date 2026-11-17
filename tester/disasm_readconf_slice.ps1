$binDir = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64"
[System.Reflection.Assembly]::LoadFrom("$binDir\DotNetAgent.Util.dll") | Out-Null
$asm = [System.Reflection.Assembly]::LoadFrom("$binDir\Site24x7PluginAgent.exe")

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
    if ($lines[$i] -match 'IL_04[4-7]') {
        Write-Host $lines[$i]
    }
}
