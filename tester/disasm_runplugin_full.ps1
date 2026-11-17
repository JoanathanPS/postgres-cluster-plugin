. .\tester\il_disasm.ps1 > $null
$t = $asm.GetType('Site24x7PluginAgent.Utils.ScriptUtils.S24x7PythonScript')
$m = $t.GetMethod('RunPlugin', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

$bytes = $m.GetMethodBody().GetILAsByteArray()
$module = $m.Module

# Let's inspect instructions of RunPlugin and print lines referencing StartInfo or Arguments
$flags = [System.Reflection.BindingFlags]'Public,NonPublic,Instance,Static'
[ILDisassembler]::Disassemble($m)
