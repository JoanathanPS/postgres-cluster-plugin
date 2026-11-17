. .\tester\il_disasm.ps1
$t = $asm.GetType('Site24x7PluginAgent.Utils.ScriptUtils.S24x7PythonScript')
$m = $t.GetMethod('RunPlugin', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')
if ($m) { [ILDisassembler]::Disassemble($m) }
