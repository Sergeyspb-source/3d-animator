# Hidden launcher for the SF3D GUI: starts the server with no console, opens an app window,
# and stops the server (freeing VRAM) when that window is closed.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$root   = Split-Path -Parent $PSScriptRoot
$env_   = 'D:\conda\envs\sf3d'
$port   = 7861
$url    = "http://127.0.0.1:$port"
$log    = 'D:\conda\tmp\ui.log'
$errlog = 'D:\conda\tmp\ui.err.log'

function Test-Up { try { Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2 | Out-Null; $true } catch { $false } }

$server = $null
if (-not (Test-Up)) {
    $env:HF_HOME = 'D:\conda\hf'; $env:TMP = 'D:\conda\tmp'; $env:TEMP = 'D:\conda\tmp'
    $env:GRADIO_ANALYTICS_ENABLED = 'False'; $env:GRADIO_TEMP_DIR = 'D:\conda\tmp'
    $env:PYTHONWARNINGS = 'ignore'; $env:ORT_LOGGING_LEVEL = '3'
    $env:PATH = "$env_;$env_\Scripts;$env_\bin;$env_\Library\bin;$env:PATH"
    $server = Start-Process "$env_\python.exe" -ArgumentList "`"$root\tool\sf3d_ui.py`"" `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $log -RedirectStandardError $errlog
    $up = $false
    for ($i = 0; $i -lt 90; $i++) {
        if ($server.HasExited) { break }
        if (Test-Up) { $up = $true; break }
        Start-Sleep 1
    }
    if (-not $up) {
        $tail = if (Test-Path $errlog) { (Get-Content $errlog -Tail 8) -join "`n" } else { '' }
        [System.Windows.Forms.MessageBox]::Show("Не удалось запустить интерфейс SF3D.`n`n$tail`n`nЖурнал: $errlog", 'SF3D') | Out-Null
        if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
        exit 1
    }
}

$browser = @(
    "$env:ProgramFiles (x86)\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($browser) {
    # Own profile = own browser process, so we can tell when the window is closed.
    $win = Start-Process $browser -PassThru -ArgumentList "--app=$url", '--user-data-dir=D:\conda\app-profile',
        '--no-first-run', '--window-size=1250,950'
    $win.WaitForExit()
    Start-Sleep 2
    # Edge may hand over to a child process; wait until no window of our profile is left.
    while (Get-CimInstance Win32_Process -Filter "Name='$(Split-Path $browser -Leaf)'" |
           Where-Object { $_.CommandLine -like '*app-profile*' }) { Start-Sleep 2 }
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
} else {
    Start-Process $url   # default browser: keep the server alive, close it manually
}
