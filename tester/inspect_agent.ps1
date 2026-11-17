. .\tester\il_disasm.ps1

Write-Host "=== Types in Site24x7PluginAgent ==="
foreach ($t in $asm.GetTypes()) {
    foreach ($m in $t.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')) {
        if ($m.Name -match '(?i)register|inventory|resp|detail|update') {
            Write-Host "$($t.FullName)::$($m.Name)"
        }
    }
}
