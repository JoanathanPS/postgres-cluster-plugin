. .\tester\il_disasm.ps1
$log = $asm.GetType('Site24x7PluginAgent.Log')
[ILDisassembler]::Disassemble($log.GetMethod('PrintRegText', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance'))
