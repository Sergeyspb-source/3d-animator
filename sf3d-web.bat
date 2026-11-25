@echo off
rem SF3D - the new web interface (beside the Gradio app, which stays on 7861): http://127.0.0.1:7890
rem Builds the page when its sources are newer than the built one (Node.js 18+ and npm needed for that),
rem then starts the server and opens an app window once it answers. Close this console to stop the server.
call "%~dp0sf3d-env.bat"
set "GRADIO_ANALYTICS_ENABLED=False"
set "PYTHONWARNINGS=ignore"
set "ORT_LOGGING_LEVEL=3"
set "PORT=7890"
set "FRONT=%~dp0tool\web\front"

powershell -NoProfile -Command "$d = Get-Item '%FRONT%\dist\index.html' -ErrorAction SilentlyContinue; $s = Get-ChildItem '%FRONT%\src', '%FRONT%\index.html', '%FRONT%\package.json' -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if (-not $d -or $s.LastWriteTime -gt $d.LastWriteTime) { exit 1 }"
if errorlevel 1 (
  echo Building the web page...
  pushd "%FRONT%"
  if not exist node_modules call npm install --no-audit --no-fund
  call npm run build
  popd
)

powershell -NoProfile -Command "try { Invoke-WebRequest http://127.0.0.1:%PORT%/api/state -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if not errorlevel 1 (
  echo The web interface is already running on %PORT%: opening a window.
  goto :open
)
start "" /b powershell -NoProfile -Command "for($i=0;$i -lt 120;$i++){try{Invoke-WebRequest http://127.0.0.1:%PORT%/api/state -UseBasicParsing -TimeoutSec 2 | Out-Null; $e=@('C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe','C:\Program Files\Microsoft\Edge\Application\msedge.exe') | Where-Object {Test-Path $_} | Select-Object -First 1; if($e){Start-Process $e '--app=http://127.0.0.1:%PORT%'}else{Start-Process http://127.0.0.1:%PORT%}; break}catch{Start-Sleep 2}}"
python "%~dp0tool\web\server.py" --port %PORT%
pause
exit /b

:open
powershell -NoProfile -Command "$e=@('C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe','C:\Program Files\Microsoft\Edge\Application\msedge.exe') | Where-Object {Test-Path $_} | Select-Object -First 1; if($e){Start-Process $e '--app=http://127.0.0.1:%PORT%'}else{Start-Process http://127.0.0.1:%PORT%}"
