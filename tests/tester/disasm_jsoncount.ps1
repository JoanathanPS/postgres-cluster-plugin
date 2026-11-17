. .\tester\il_disasm.ps1
$dc = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $dc.GetMethod('SetPluginJsonCount', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

[ILDisassembler]::Disassemble($m)
