# Hidden launcher for the 3d-animator web interface: builds the page when its sources are newer than the built one, starts
# the server with no console, opens an app window, and stops the server (freeing VRAM) when that window is closed.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$root   = Split-Path -Parent $PSScriptRoot
$front  = Join-Path $root 'tool\web\front'
$env_   = 'D:\conda\envs\sf3d'
$port   = 7890
$url    = "http://127.0.0.1:$port"
$log    = 'D:\conda\tmp\ui.log'
$errlog = 'D:\conda\tmp\ui.err.log'

function Test-Up { try { Invoke-WebRequest "$url/api/state" -UseBasicParsing -TimeoutSec 2 | Out-Null; $true } catch { $false } }
function Show-Error($text) { [System.Windows.Forms.MessageBox]::Show($text, '3d-animator') | Out-Null }

$server = $null
if (-not (Test-Up)) {
    # the page (Node.js 18+ and npm build it; without them the page built before is used)
    $built  = Get-Item (Join-Path $front 'dist\index.html') -ErrorAction SilentlyContinue
    $newest = Get-ChildItem (Join-Path $front 'src'), (Join-Path $front 'index.html'), (Join-Path $front 'package.json') -Recurse -File |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $built -or $newest.LastWriteTime -gt $built.LastWriteTime) {
        $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if ($npm) {
            $ok = $true
            if (-not (Test-Path (Join-Path $front 'node_modules'))) {
                $p = Start-Process $npm.Source -ArgumentList 'install', '--no-audit', '--no-fund' -WorkingDirectory $front -WindowStyle Hidden `
                    -RedirectStandardOutput $log -RedirectStandardError $errlog -Wait -PassThru
                $ok = $p.ExitCode -eq 0
            }
            if ($ok) {
                $p = Start-Process $npm.Source -ArgumentList 'run', 'build' -WorkingDirectory $front -WindowStyle Hidden `
                    -RedirectStandardOutput $log -RedirectStandardError $errlog -Wait -PassThru
                $ok = $p.ExitCode -eq 0
            }
            if (-not $ok -and -not $built) { Show-Error "Не удалось собрать страницу интерфейса 3d-animator.`n`nЖурнал: $errlog"; exit 1 }
        } elseif (-not $built) {
            Show-Error "Страница интерфейса 3d-animator не собрана, а Node.js не найден. Установите Node.js 18+ и запустите снова."
            exit 1
        }
    }
    $env:HF_HOME = 'D:\conda\hf'; $env:TMP = 'D:\conda\tmp'; $env:TEMP = 'D:\conda\tmp'
    $env:PYTHONWARNINGS = 'ignore'; $env:ORT_LOGGING_LEVEL = '3'
    $env:PATH = "$env_;$env_\Scripts;$env_\bin;$env_\Library\bin;$env:PATH"
    $server = Start-Process "$env_\python.exe" -ArgumentList "`"$root\tool\web\server.py`"", '--port', $port `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $log -RedirectStandardError $errlog
    $up = $false
    for ($i = 0; $i -lt 120; $i++) {
        if ($server.HasExited) { break }
        if (Test-Up) { $up = $true; break }
        Start-Sleep 1
    }
    if (-not $up) {
        $tail = if (Test-Path $errlog) { (Get-Content $errlog -Tail 8) -join "`n" } else { '' }
        Show-Error "Не удалось запустить интерфейс 3d-animator.`n`n$tail`n`nЖурнал: $errlog"
        if ($server -and -not $server.HasExited) { Start-Process taskkill.exe -ArgumentList '/PID', $server.Id, '/T', '/F' -WindowStyle Hidden -Wait }
        exit 1
    }
}

$browser = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($browser) {
    # Own profile = own browser process, so we can tell when the window is closed.
    $win = Start-Process $browser -PassThru -ArgumentList "--app=$url", '--user-data-dir=D:\conda\app-profile',
        '--no-first-run', '--start-maximized'
    $win.WaitForExit()
    Start-Sleep 2
    # Edge may hand over to a child process; wait until no window of our profile is left.
    while (Get-CimInstance Win32_Process -Filter "Name='$(Split-Path $browser -Leaf)'" |
           Where-Object { $_.CommandLine -like '*app-profile*' }) { Start-Sleep 2 }
    if ($server -and -not $server.HasExited) {   # only a server this launcher started, with what it runs (Blender, a model)
        Start-Process taskkill.exe -ArgumentList '/PID', $server.Id, '/T', '/F' -WindowStyle Hidden -Wait
    }
} else {
    Start-Process $url   # default browser: keep the server alive, close it manually
}
