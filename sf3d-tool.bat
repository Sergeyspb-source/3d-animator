@echo off
rem Wrapper CLI. Examples (run from any folder; relative paths work):
rem   sf3d-tool.bat generate "D:\My projects\SF3D\input" --category prop
rem   sf3d-tool.bat generate axe.png --category item --name axe
rem   sf3d-tool.bat post work\item\axe\raw.glb --category item --name axe --metallic 0.3
set "START_DIR=%CD%"
call "%~dp0sf3d-env.bat"
cd /d "%START_DIR%"
set "PYTHONWARNINGS=ignore"
set "ORT_LOGGING_LEVEL=3"
python "%~dp0tool\sf3d_tool.py" %*
