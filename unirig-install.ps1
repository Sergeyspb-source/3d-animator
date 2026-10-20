# UniRig (auto-rigging) in its own env. Everything on D:. Uses the Windows PR #70 checked out in unirig-src.
$env:CONDA_PKGS_DIRS = 'D:\conda\pkgs'; $env:PIP_CACHE_DIR = 'D:\conda\pip-cache'
$env:TMP = 'D:\conda\tmp'; $env:TEMP = 'D:\conda\tmp'; $env:HF_HOME = 'D:\conda\hf'
$conda = if ($env:CONDA_EXE) { $env:CONDA_EXE } else { 'conda' }   # run from an Anaconda/Miniconda prompt
$envdir = 'D:\conda\envs\unirig'
$py = "$envdir\python.exe"
$src = 'D:\My projects\SF3D\unirig-src'

if (-not (Test-Path $py)) { & $conda create -p $envdir python=3.11 -y }
& $py -m pip install --upgrade pip
& $py -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
& $py -c "import torch; print('TORCH', torch.__version__, torch.version.cuda, torch.cuda.is_available())"
# requirements without flash_attn (replaced by the shim on Windows)
Get-Content "$src\requirements.txt" | Where-Object { $_.Trim() -and $_ -notmatch '^flash_attn' } | Set-Content 'D:\conda\tmp\unirig-req.txt'
& $py -m pip install -r 'D:\conda\tmp\unirig-req.txt'
& $py -m pip install spconv-cu124==2.3.8
& $py -m pip install torch_scatter torch_cluster
Set-Location $src
& $py install_flash_attn_shim.py
Write-Output 'UNIRIG_INSTALL_DONE'
