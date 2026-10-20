# Installs Hunyuan3D-2 (multiview) into its own env. Everything lives on D: (C: is small).
$ErrorActionPreference = 'Continue'
$env:CONDA_PKGS_DIRS = 'D:\conda\pkgs'; $env:PIP_CACHE_DIR = 'D:\conda\pip-cache'
$env:TMP = 'D:\conda\tmp'; $env:TEMP = 'D:\conda\tmp'; $env:HF_HOME = 'D:\conda\hf'
$conda = if ($env:CONDA_EXE) { $env:CONDA_EXE } else { 'conda' }   # run from an Anaconda/Miniconda prompt
$envdir = 'D:\conda\envs\hunyuan'
$py = "$envdir\python.exe"
$src = 'D:\My projects\SF3D\hunyuan3d-src'

if (-not (Test-Path $py)) { & $conda create -p $envdir python=3.10 -y }
& $py -m pip install torch==2.4.1 torchvision==0.19.1 --index-url https://download.pytorch.org/whl/cu121
& $py -m pip install "numpy<2" ninja pybind11 diffusers einops opencv-python-headless transformers omegaconf tqdm `
    trimesh pymeshlab pygltflib xatlas accelerate gradio==4.41.0 "fastapi==0.112.4" "starlette<0.39" "pydantic==2.10.6" `
    uvicorn rembg onnxruntime safetensors huggingface_hub
& $py -m pip install -e $src --no-deps
Write-Output 'INSTALL_DONE'
