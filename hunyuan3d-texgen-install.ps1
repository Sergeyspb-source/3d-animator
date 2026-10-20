# nvcc into the hunyuan env (conda, on D:), then build the texgen extensions.
$env:CONDA_PKGS_DIRS = 'D:\conda\pkgs'; $env:PIP_CACHE_DIR = 'D:\conda\pip-cache'
$env:TMP = 'D:\conda\tmp'; $env:TEMP = 'D:\conda\tmp'
$conda = if ($env:CONDA_EXE) { $env:CONDA_EXE } else { 'conda' }   # run from an Anaconda/Miniconda prompt
& $conda install -p D:\conda\envs\hunyuan -c 'nvidia/label/cuda-12.1.0' cuda-nvcc cuda-cudart-dev cuda-libraries-dev -y
if (-not (Test-Path 'D:\conda\envs\hunyuan\bin\nvcc.exe')) { Write-Output 'NVCC_MISSING'; exit 1 }
cmd /c '"D:\My projects\SF3D\hunyuan3d-texgen-build.bat"'
Write-Output 'BUILD_FINISHED'
