. .\tester\il_disasm.ps1 > $null
$util = $asm.GetType('Site24x7PluginAgent.Utils.Util')
$m = $util.GetMethod('ReadConfFile', [System.Reflection.BindingFlags]'Public,NonPublic,Static')
[ILDisassembler]::Disassemble($m)
