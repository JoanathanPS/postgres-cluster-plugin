. .\tester\il_disasm.ps1
$t = $asm.GetType('Site24x7PluginAgent.PluginsMonitor')
$m = $t.GetMethod('StartMonitoring', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')
if ($m) { [ILDisassembler]::Disassemble($m) }
