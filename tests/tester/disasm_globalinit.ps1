. .\tester\il_disasm.ps1
$t = $asm.GetType('Site24x7PluginAgent.Global')
$m = $t.GetMethod('Init', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')
if ($m) { [ILDisassembler]::Disassemble($m) }
