$path = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe'
$bytes = [System.IO.File]::ReadAllBytes($path)
$asm = [System.Reflection.Assembly]::Load($bytes)
$pluginUtil = $asm.GetType('Site24x7PluginAgent.Utils.PluginUtil')
$m = $pluginUtil.GetMethod('GetScriptObject', [System.Reflection.BindingFlags]'Public,NonPublic,Static')
if ($m) {
    Write-Output "=== PluginUtil::GetScriptObject parameters ==="
    $m.GetParameters() | ForEach-Object { "$($_.ParameterType.Name) $($_.Name)" }
}

$dc = $asm.GetType('Site24x7PluginAgent.DataCollection')
$mReg = $dc.GetMethod('RunPluginandWriteToRegFile', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')
# Let's inspect where GetScriptObject is called in RunPluginandWriteToRegFile
. .\tester\il_disasm.ps1 > $null
$insts = [ILDisassembler]::Disassemble($mReg)
