. .\tester\il_disasm.ps1

foreach ($t in $asm.GetTypes()) {
    foreach ($m in $t.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')) {
        $il = [ILDisassembler]::Disassemble($m)
        if ($il -match 'already registered') {
            Write-Host "$($t.FullName)::$($m.Name)"
        }
    }
}
