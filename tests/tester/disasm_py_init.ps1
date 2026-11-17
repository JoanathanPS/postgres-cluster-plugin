. .\tester\il_disasm.ps1
$t = $asm.GetType('Site24x7PluginAgent.Utils.ScriptUtils.S24x7PythonScript')
$m = $t.GetMethod('Init', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')
if ($m) { 
    Write-Output "=== S24x7PythonScript::Init ==="
    [ILDisassembler]::Disassemble($m) 
}

$m2 = $t.GetMethod('RunPlugin', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')
if ($m2) {
    Write-Output "=== S24x7PythonScript::RunPlugin (first 200 instructions) ==="
    # let's look at the beginning of RunPlugin
}
