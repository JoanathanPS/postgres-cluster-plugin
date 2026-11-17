. .\tester\il_disasm.ps1
$t = $asm.GetType('Site24x7PluginAgent.Site24x7Monitoring')
$m = $t.GetMethod('OnStart', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')
if ($m) { [ILDisassembler]::Disassemble($m) }
