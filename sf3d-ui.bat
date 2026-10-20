@echo off
rem SF3D Game Assets - graphical interface. Double-click to start.
rem Opens as an app window at http://127.0.0.1:7861 once the server is ready.
rem Close other GPU-heavy apps first (SF3D peaks at ~6.2 GB VRAM); close the old
rem sf3d-gradio.bat demo window too, it keeps its own copy of the model in memory.
call "%~dp0sf3d-env.bat"
set "GRADIO_ANALYTICS_ENABLED=False"
set "GRADIO_TEMP_DIR=D:\conda\tmp"
set "PYTHONWARNINGS=ignore"
set "ORT_LOGGING_LEVEL=3"
start "" /b powershell -NoProfile -Command "for($i=0;$i -lt 120;$i++){try{Invoke-WebRequest http://127.0.0.1:7861 -UseBasicParsing -TimeoutSec 2 | Out-Null; $e=@('C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe','C:\Program Files\Microsoft\Edge\Application\msedge.exe') | Where-Object {Test-Path $_} | Select-Object -First 1; if($e){Start-Process $e '--app=http://127.0.0.1:7861'}else{Start-Process http://127.0.0.1:7861}; break}catch{Start-Sleep 2}}"
python "%~dp0tool\sf3d_ui.py"
pause
