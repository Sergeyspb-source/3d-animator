@echo off
rem Batch run without the GUI. Examples:
rem   sf3d-batch.bat --scan
rem   sf3d-batch.bat "D:\My projects\SF3D\input"
rem   sf3d-batch.bat "D:\My projects\SF3D\input" --force --no-preview
rem Folder layout: <folder>\<item|prop|building|character>\picture.png  (SF3D, one image)
rem                <folder>\<category>\<asset>\front.png [back/left/right.png]  (Hunyuan3D, several views)
call "%~dp0sf3d-env.bat"
set "HF_HUB_OFFLINE=1"
set "GRADIO_ANALYTICS_ENABLED=False"
set "PYTHONWARNINGS=ignore"
set "PYTHONIOENCODING=utf-8"
python "%~dp0tool\batch_cli.py" %*
