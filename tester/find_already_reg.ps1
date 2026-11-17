. .\tester\il_disasm.ps1

$t = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $t.GetMethod('RunPluginandWriteForReg', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

$lines = [ILDisassembler]::Disassemble($m)
$lines | Select-String -Pattern 'already registered' -Context 5, 10
