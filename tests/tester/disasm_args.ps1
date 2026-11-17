. .\tester\il_disasm.ps1
$t = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $t.GetMethod('RunPluginandWriteToRegFile', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

$bytes = $m.GetMethodBody().GetILAsByteArray()
# Let's inspect instructions from 0x0180 to 0x0350
$insts = [ILDisassembler]::ParseInstructions($m)
foreach ($i in $insts) {
    if ($i.Offset -ge 0x0180 -and $i.Offset -le 0x0380) {
        Write-Output ("  IL_{0:X4}: {1} {2}" -f $i.Offset, $i.OpCode.Name, $i.Operand)
    }
}
