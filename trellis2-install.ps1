# Builds TRELLIS.2 (trellis.cpp, MIT) from source into D:\conda\trellis: trellis-cli.exe + ggml DLLs.
# Needs: VS 2022 Build Tools (C++), CMake, and the Hunyuan env (hunyuan3d-install.ps1) - its CUDA 12.1 toolkit
# (nvcc, cuBLAS) is used to compile, and its bin folder holds the CUDA runtime DLLs the app puts on PATH.
# The source is pinned to the commit that was tested on the RTX 4060 Laptop (2026-11-24). ~25 min. Run again to rebuild.
$ErrorActionPreference = 'Continue'   # git and cmake write progress to stderr; exit codes are checked below
$env:TMP = 'D:\conda\tmp'; $env:TEMP = 'D:\conda\tmp'
$root = 'D:\conda\trellis'
$src = "$root\src"
$build = "$root\build"
$commit = '7c600c64b547fddb989c66df0b1cb045add788ed'   # pwilkin/trellis.cpp, 2026-11-24 (ggml submodule f8697b3)
$cuda = 'D:\conda\envs\hunyuan'                          # CUDA 12.1 toolkit from conda (nvcc + cuBLAS)

if (-not (Test-Path "$cuda\bin\nvcc.exe")) { throw "nvcc not found in $cuda\bin: install Hunyuan3D first (hunyuan3d-install.ps1)" }
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'Visual Studio 2022 C++ build tools not found' }
$ninja = "$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja"
if (-not (Test-Path "$ninja\ninja.exe")) { $ninja = "$cuda\Scripts" }   # the hunyuan env has pip's ninja too

New-Item -ItemType Directory -Force $root | Out-Null
if (-not (Test-Path "$src\.git")) { git clone --no-checkout https://github.com/pwilkin/trellis.cpp $src }
git -C $src fetch --depth 1 origin $commit
git -C $src checkout --force $commit
if ($LASTEXITCODE -ne 0) { throw "could not check out $commit" }
git -C $src submodule update --init --depth 1
if ($LASTEXITCODE -ne 0) { throw 'could not fetch the ggml submodule' }

# cmd.exe for vcvars64; a .bat keeps the quoting of the paths with spaces simple
$bat = "$root\build_cuda.bat"
@"
@echo off
set TMP=D:\conda\tmp
set TEMP=D:\conda\tmp
call "$vs\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
set CUDA_PATH=$cuda
set PATH=$cuda\bin;$ninja;%PATH%
cmake -S "$src" -B "$build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DGGML_OPENMP=OFF -DCMAKE_CUDA_ARCHITECTURES=89 ^
  -DCMAKE_CUDA_COMPILER=$($cuda.Replace('\','/'))/bin/nvcc.exe -DCUDAToolkit_ROOT=$($cuda.Replace('\','/')) ^
  "-DCMAKE_CUDA_FLAGS=-allow-unsupported-compiler -D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH" || exit /b 2
cmake --build "$build" --target trellis-cli -j 8 || exit /b 3
"@ | Set-Content -Encoding ascii $bat
cmd.exe /c "`"$bat`""
if ($LASTEXITCODE -ne 0) { throw "build failed ($LASTEXITCODE), see the output above" }

Copy-Item "$build\trellis-cli.exe", "$build\ggml*.dll" $root -Force
Write-Output "INSTALL_DONE $root\trellis-cli.exe  (weights: trellis2-weights.ps1)"
