. .\tester\il_disasm.ps1

$tu = $asm.GetType('Site24x7PluginAgent.Utils.Util')
foreach ($m in $tu.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')) {
    $il = [ILDisassembler]::Disassemble($m)
    if ($il -match 'isPluginReload|IsPluginConfigUpdated|RegistryUtil') {
        Write-Host "$($m.Name) touches registry"
    }
}
$tc = $asm.GetType('Site24x7PluginAgent.DataCollection')
foreach ($m in $tc.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')) {
    $il = [ILDisassembler]::Disassemble($m)
    if ($il -match 'isPluginReload|IsPluginConfigUpdated|RegistryUtil') {
        Write-Host "$($m.Name) touches registry"
    }
}
