. .\tester\il_disasm.ps1 > $null
$util = $asm.GetType('Site24x7PluginAgent.Utils.Util')
$m = $util.GetMethod('CreateArgStr', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')
[ILDisassembler]::Disassemble($m)
