@echo off
rem Visual SF3D demo: upload an image, see background removal and a 3D preview, download the GLB.
rem Opens at http://127.0.0.1:7860 once the server is ready (first start takes ~1 min: loading weights).
rem Close other GPU-heavy apps first: SF3D peaks at ~6.2 GB VRAM.
call "%~dp0sf3d-env.bat"
set "GRADIO_ANALYTICS_ENABLED=False"
set "GRADIO_TEMP_DIR=D:\conda\tmp"
start "" /b powershell -NoProfile -Command "for($i=0;$i -lt 120;$i++){try{Invoke-WebRequest http://127.0.0.1:7860 -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process http://127.0.0.1:7860; break}catch{Start-Sleep 2}}"
python gradio_app.py
pause
