. .\tester\il_disasm.ps1
$entry = $asm.EntryPoint
[ILDisassembler]::Disassemble($entry)
