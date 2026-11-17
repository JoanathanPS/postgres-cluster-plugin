. .\tester\il_disasm.ps1

Write-Host "=== DataCollection.RegisterPlugin ==="
$t = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $t.GetMethod('RegisterPlugin', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')
if ($m) { [ILDisassembler]::Disassemble($m) }

Write-Host "=== Util.UpdatePluginDetails ==="
$t2 = $asm.GetType('Site24x7PluginAgent.Utils.Util')
$m2 = $t2.GetMethod('UpdatePluginDetails', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')
if ($m2) { [ILDisassembler]::Disassemble($m2) }
