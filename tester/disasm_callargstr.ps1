$path = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe'
$bytes = [System.IO.File]::ReadAllBytes($path)
$asm = [System.Reflection.Assembly]::Load($bytes)
$dc = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $dc.GetMethod('RunPluginandWriteToRegFile', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

. .\tester\il_disasm.ps1 > $null
$insts = [ILDisassembler]::Disassemble($m)
