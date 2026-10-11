# Build the orca_teleop runtime environment on Windows.
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 files as ANSI
# when there is no BOM, so non-ASCII characters break the parser. Chinese notes
# live in README.md instead.
#
# Why this script exists: orca_teleop's default adaptive_analytical retargeter needs
# Pinocchio, and the PyPI packages that provide it (pin, cmeel-urdfdom,
# cmeel-tinyxml2) have NEVER shipped a Windows wheel -- across all their releases
# the win_amd64 file count is zero. So `uv sync --extra adaptive` cannot work on
# Windows. Workaround: take Pinocchio from conda-forge (win-64 has a py312 build of
# 4.1.0), install everything else with pip, and install orca_teleop itself with
# --no-deps so pip never reaches for the cmeel packages.
#
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File setup-teleop-env.ps1 [-SkipTorch]

param(
    [string]$EnvName = "orca-teleop",
    [string]$CondaExe = "D:\tools\miniconda\Scripts\conda.exe",
    [string]$CondaForge = "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge",
    [switch]$SkipTorch
)

$ErrorActionPreference = "Stop"

# Locate the ORCA checkouts. Same search order as orca_paths.py:
#   $env:ORCA_LINK_ORCA_ROOT, then <orca-link>\..\orca-ecosystem, then <orca-link>\vendor
function Resolve-OrcaRoot {
    $candidates = @()
    if ($env:ORCA_LINK_ORCA_ROOT) { $candidates += $env:ORCA_LINK_ORCA_ROOT }
    $candidates += (Join-Path (Split-Path $PSScriptRoot -Parent) "orca-ecosystem")
    $candidates += (Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) "orca-ecosystem")
    $candidates += (Join-Path $PSScriptRoot "vendor")
    foreach ($c in $candidates) {
        if ((Test-Path (Join-Path $c "orca_core-upstream")) -or (Test-Path (Join-Path $c "orca_core"))) {
            return $c
        }
    }
    return $null
}

$orcaRoot = Resolve-OrcaRoot
if (-not $orcaRoot) {
    Write-Host "Cannot find the ORCA checkouts. Looked in:"
    Write-Host "  `$env:ORCA_LINK_ORCA_ROOT"
    Write-Host "  $PSScriptRoot\..\orca-ecosystem"
    Write-Host "  $PSScriptRoot\vendor"
    Write-Host ""
    Write-Host "Clone them first, e.g.:"
    Write-Host "  mkdir `"$PSScriptRoot\..\orca-ecosystem`""
    Write-Host "  cd `"$PSScriptRoot\..\orca-ecosystem`""
    Write-Host "  git clone https://github.com/orcahand/orca_core.git orca_core-upstream"
    Write-Host "  git clone https://github.com/orcahand/orca_teleop.git orca_teleop"
    Write-Host "  git clone https://github.com/orcahand/orcahand_description.git orcahand_description"
    Write-Host "  `$env:ORCAHAND_DESCRIPTION_DIR = `"$PSScriptRoot\..\orca-ecosystem\orcahand_description`""
    exit 1
}

$coreName = if (Test-Path (Join-Path $orcaRoot "orca_core-upstream")) { "orca_core-upstream" } else { "orca_core" }
$teleop = Join-Path $orcaRoot "orca_teleop"
$core = Join-Path $orcaRoot $coreName
$condaRoot = Split-Path (Split-Path $CondaExe -Parent) -Parent
$envPy = Join-Path $condaRoot "envs\$EnvName\python.exe"
Write-Host "ORCA root: $orcaRoot"

Write-Host "==> 1/5 conda env: python 3.12 + pinocchio + nlopt (conda-forge mirror)"
if (-not (Test-Path $envPy)) {
    & $CondaExe create -n $EnvName --override-channels -c $CondaForge `
        python=3.12 "pinocchio=4.1.0" nlopt pyyaml -y
} else {
    Write-Host "    already exists, skipping"
}
if (-not (Test-Path $envPy)) { throw "conda env creation failed, missing: $envPy" }

Write-Host "==> 2/5 verify Pinocchio and NLopt import"
& $envPy -c "import pinocchio, nlopt, sys; print('    python', sys.version.split()[0], '| pinocchio', pinocchio.__version__, '| nlopt', nlopt.__version__)"

Write-Host "==> 3/5 pip dependencies"
# torch comes from the CPU index: on Windows the default PyPI wheel is the CUDA
# build and is several times larger.
if (-not $SkipTorch) {
    & $envPy -m pip install --disable-pip-version-check -q `
        torch --index-url https://download.pytorch.org/whl/cpu
}
& $envPy -m pip install --disable-pip-version-check -q `
    "pytorch-kinematics" "numpy>=2" "pyyaml" "grpcio>=1.62.3" "protobuf>=4.25.9,<5" "aiohttp>=3.10"

Write-Host "==> 4/5 orca_core (upstream) + orca_teleop (--no-deps)"
& $envPy -m pip install --disable-pip-version-check -q -e $core
# --no-deps is deliberate: orca_teleop depends on the cmeel `pin` package, which has
# no Windows wheel; conda already provided Pinocchio.
& $envPy -m pip install --disable-pip-version-check -q --no-deps -e $teleop

Write-Host "==> 5/5 smoke test: import both retargeter backends"
& $envPy -c @"
import orca_teleop
from orca_teleop.retargeting.retargeter import Retargeter, TargetPose
from orca_teleop.retargeting.adaptive_analytical import AdaptiveAnalyticalRetargeter
import pinocchio as pin
print('    orca_teleop import OK; pinocchio', pin.__version__)
"@

Write-Host ""
Write-Host "Environment ready: $envPy"
Write-Host "The scripts resolve the ORCA checkouts on their own. To make it explicit, set:"
Write-Host "  `$env:ORCA_LINK_ORCA_ROOT = '$orcaRoot'"
Write-Host "  `$env:ORCAHAND_DESCRIPTION_DIR = '$(Join-Path $orcaRoot "orcahand_description")'"
