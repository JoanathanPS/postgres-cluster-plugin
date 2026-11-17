. .\tester\il_disasm.ps1
$u = $asm.GetType('Site24x7PluginAgent.Utils.Util')
$m = $u.GetMethod('CheckPluginForRegister', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

[ILDisassembler]::Disassemble($m)
