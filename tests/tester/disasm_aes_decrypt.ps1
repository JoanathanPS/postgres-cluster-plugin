$binDir = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64"
[System.Reflection.Assembly]::LoadFrom("$binDir\DotNetAgent.Util.dll") | Out-Null
$asm = [System.Reflection.Assembly]::LoadFrom("$binDir\Site24x7PluginAgent.exe")

. .\tester\il_disasm.ps1 > $null
$aes = $asm.GetType('Site24x7PluginAgent.Utils.AES')
$m = $aes.GetMethod('Decrypt', [System.Reflection.BindingFlags]'Public,NonPublic,Static')

[ILDisassembler]::Disassemble($m)
