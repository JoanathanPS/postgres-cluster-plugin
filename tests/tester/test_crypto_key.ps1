$binDir = "C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64"
[System.Reflection.Assembly]::LoadFrom("$binDir\DotNetAgent.Util.dll") | Out-Null
$asm = [System.Reflection.Assembly]::LoadFrom("$binDir\Site24x7PluginAgent.exe")

$glob = $asm.GetType('Site24x7PluginAgent.Global')
$logType = $asm.GetType('Site24x7PluginAgent.Utils.Log')
$logInst = [Activator]::CreateInstance($logType)
$glob.GetField('log', [System.Reflection.BindingFlags]'Public,NonPublic,Static').SetValue($null, $logInst)

$aes = $asm.GetType('Site24x7PluginAgent.Utils.AES')
$mDec = $aes.GetMethod('Decrypt', [System.Reflection.BindingFlags]'Public,NonPublic,Static')

$testCipher = "45cPtZ8oRlWaZi+W8l9xww=="
$keysToTry = @(
    "577111673237472603",
    "E//l5Rmnj6zjNh1y05RQHj9swVDRIqje5brl8ithEYJf8OK5oHSPaE4EvqIWCsCc"
)

foreach ($k in $keysToTry) {
    try {
        $plain = $mDec.Invoke($null, @($testCipher, $k, "SHA256"))
        Write-Output "Key '$k' successfully decrypted: $plain"
    } catch {
        Write-Output "Key '$k' failed: $_"
    }
}
