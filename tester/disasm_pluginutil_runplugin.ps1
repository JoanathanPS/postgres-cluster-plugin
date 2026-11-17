. .\tester\il_disasm.ps1 > $null
$pluginUtil = $asm.GetType('Site24x7PluginAgent.Utils.PluginUtil')
$methods = $pluginUtil.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance') | Where-Object { $_.Name -eq 'RunPlugin' -and $_.GetParameters().Count -eq 7 }
foreach ($m in $methods) {
    [ILDisassembler]::Disassemble($m)
}
