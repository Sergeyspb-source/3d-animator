@echo off
rem Environment for SF3D: conda env, caches and HF models all on D: (C: is small).
set "ENVDIR=D:\conda\envs\sf3d"
set "PATH=%ENVDIR%;%ENVDIR%\Scripts;%ENVDIR%\bin;%ENVDIR%\Library\bin;%PATH%"
set "HF_HOME=D:\conda\hf"
set "PIP_CACHE_DIR=D:\conda\pip-cache"
set "TMP=D:\conda\tmp"
set "TEMP=D:\conda\tmp"
cd /d "D:\My projects\SF3D\sf3d-src"
