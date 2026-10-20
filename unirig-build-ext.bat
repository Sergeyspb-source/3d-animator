@echo off
rem torch_scatter / torch_cluster are built from source here (no prebuilt wheel for this torch).
rem CPU-only on purpose: UniRig's Windows patch falls back to CPU kernels for them.
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" || exit /b 1
set "ENVDIR=D:\conda\envs\unirig"
set "PATH=%ENVDIR%;%ENVDIR%\Scripts;%PATH%"
set "DISTUTILS_USE_SDK=1"
set "FORCE_CUDA=0"
set "PIP_CACHE_DIR=D:\conda\pip-cache"
set "TMP=D:\conda\tmp"
set "TEMP=D:\conda\tmp"
set "MAX_JOBS=4"
"%ENVDIR%\python.exe" -m pip install --no-build-isolation --no-cache-dir torch_scatter torch_cluster
"%ENVDIR%\python.exe" -c "import torch, torch_scatter, torch_cluster; print('EXT_OK', torch.__version__)"
