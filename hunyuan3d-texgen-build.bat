@echo off
rem Builds the two native extensions of Hunyuan3D texture generation inside the 'hunyuan' env.
rem nvcc 12.1 comes from conda (installed into the env on D:), MSVC from Build Tools 2022.
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" || exit /b 1
set "ENVDIR=D:\conda\envs\hunyuan"
set "CUDA_HOME=%ENVDIR%"
set "CUDA_PATH=%ENVDIR%"
set "PATH=%ENVDIR%\bin;%ENVDIR%\Library\bin;%ENVDIR%\Scripts;%PATH%"
set "TORCH_CUDA_ARCH_LIST=8.9"
set "DISTUTILS_USE_SDK=1"
set "NVCC_APPEND_FLAGS=-allow-unsupported-compiler -D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH"
set "PIP_CACHE_DIR=D:\conda\pip-cache"
set "TMP=D:\conda\tmp"
set "TEMP=D:\conda\tmp"
set "MAX_JOBS=4"
set "SRC=D:\My projects\SF3D\hunyuan3d-src\hy3dgen\texgen"
nvcc --version || exit /b 1
cd /d "%SRC%\custom_rasterizer" || exit /b 1
"%ENVDIR%\python.exe" -m pip install --no-build-isolation --no-deps . || exit /b 1
cd /d "%SRC%\differentiable_renderer" || exit /b 1
"%ENVDIR%\python.exe" -m pip install --no-build-isolation --no-deps . || exit /b 1
"%ENVDIR%\python.exe" -c "import custom_rasterizer, mesh_processor; print('TEXGEN_EXT_OK')"
