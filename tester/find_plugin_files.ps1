. .\tester\il_disasm.ps1

$t = $asm.GetType('Site24x7PluginAgent.DataCollection')
foreach ($m in $t.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')) {
    $il = [ILDisassembler]::Disassemble($m)
    if ($il -match 'pluginFiles') {
        Write-Host "$($m.Name) touches pluginFiles"
    }
}
$tu = $asm.GetType('Site24x7PluginAgent.Utils.Util')
foreach ($m in $tu.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')) {
    $il = [ILDisassembler]::Disassemble($m)
    if ($il -match 'pluginFiles') {
        Write-Host "$($m.Name) touches pluginFiles"
    }
}
