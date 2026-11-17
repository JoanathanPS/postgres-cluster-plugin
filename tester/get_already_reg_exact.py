import subprocess

ps_script = r"""
$dll = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe"
$bytes = [System.IO.File]::ReadAllBytes($dll)
$asm = [System.Reflection.Assembly]::Load($bytes)
$t = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $t.GetMethod('RunPluginandWriteForReg', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

. .\tester\il_disasm.ps1
$lines = [ILDisassembler]::Disassemble($m)
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match 'already registered') {
        Write-Host "FOUND AT $i"
        for ($j = [Math]::Max(0, $i - 20); $j -le [Math]::Min($lines.Count - 1, $i + 10); $j++) {
            Write-Host "$j : $($lines[$j])"
        }
    }
}
"""

with open("tester/disasm_temp2.ps1", "w") as f:
    f.write(ps_script)

res = subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", "tester/disasm_temp2.ps1"], capture_output=True, text=True)
lines = res.stdout.splitlines()
in_found = False
for line in lines:
    if "FOUND AT" in line:
        in_found = True
    if in_found:
        print(line)
