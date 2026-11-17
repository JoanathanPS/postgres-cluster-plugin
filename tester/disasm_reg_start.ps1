. .\tester\il_disasm.ps1

$t = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $t.GetMethod('RegisterPlugin', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

$bytes = $m.GetMethodBody().GetILAsByteArray()
Write-Host "Method body length: $($bytes.Length)"

# Let's inspect the first 100 instructions of RegisterPlugin
[ILDisassembler]::Disassemble($m) | Select-Object -First 100
