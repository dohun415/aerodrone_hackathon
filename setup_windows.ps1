<#
.SYNOPSIS
  Windows용 개발환경 자동 세팅 (aerodrone_hackathon 정합 파이프라인).

.DESCRIPTION
  이 저장소는 macOS에서 개발됐다. Windows에서 막히는 지점은 딱 두 개고,
  이 스크립트가 그 두 개를 자동으로 처리한다:

   1) GDAL  — arosics(②단계)가 GDAL 파이썬 바인딩을 요구하는데, PyPI의
      `gdal`은 소스 배포만 있어서 Windows에서는 C 컴파일러 + GDAL C
      라이브러리 없이는 `pip install`이 실패한다. (macOS에서 `brew install
      gdal`로 풀었던 그 문제의 Windows 버전.) → Christoph Gohlke의
      geospatial-wheels에서 미리 빌드된 wheel을 받아 설치한다.

   2) PyTorch — PyPI의 Windows용 torch는 CPU 전용이다. NVIDIA GPU가
      감지되면 PyTorch 공식 CUDA 인덱스에서 받아 LoFTR(④단계)를
      GPU로 돌린다. GPU가 없으면 CPU 빌드로 폴백.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
#>
[CmdletBinding()]
param(
    # GPU가 있어도 CPU 빌드 torch를 설치하고 싶을 때
    [switch]$CpuOnly,
    # 기존 .venv를 지우고 처음부터 다시
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root ".venv"
$py   = Join-Path $venv "Scripts\python.exe"

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# ---------------------------------------------------------------- 1. venv
Step "1/6  Python 3.12 가상환경"
if ($Recreate -and (Test-Path $venv)) {
    Write-Host "기존 .venv 삭제..."
    Remove-Item -Recurse -Force $venv
}
if (-not (Test-Path $py)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $launcher) { throw "Python 실행기(py)를 찾을 수 없습니다. python.org에서 Python 3.12를 설치하세요." }
    & py -3.12 -m venv $venv
    if (-not (Test-Path $py)) { throw "Python 3.12가 없습니다. `py -0p` 로 설치된 버전을 확인하세요." }
}
& $py -m pip install --upgrade pip --quiet
& $py -c "import sys; print('Python', sys.version.split()[0])"

# ------------------------------------------------------- 2. 핵심 라이브러리
Step "2/6  핵심 라이브러리 (rasterio / OpenCV / scikit-image ...)"
& $py -m pip install -r (Join-Path $root "requirements-windows.txt")
if ($LASTEXITCODE -ne 0) { throw "핵심 라이브러리 설치 실패" }

# ------------------------------------------------------------- 3. GDAL wheel
Step "3/6  GDAL (Windows 미리빌드 wheel)"
$hasGdal = $false
& $py -c "from osgeo import gdal" 2>$null
if ($LASTEXITCODE -eq 0) { $hasGdal = $true }

if ($hasGdal) {
    Write-Host "GDAL 이미 설치됨 — 건너뜀"
} else {
    # 이 venv의 Python 태그(cp312 등)에 맞는 wheel을 릴리스에서 골라 받는다.
    $tag = & $py -c "import sys; print(f'cp{sys.version_info.major}{sys.version_info.minor}')"
    Write-Host "대상 Python 태그: $tag"
    $rel = Invoke-RestMethod "https://api.github.com/repos/cgohlke/geospatial-wheels/releases/latest" `
                             -Headers @{ "User-Agent" = "aerodrone-setup" }
    $asset = $rel.assets | Where-Object { $_.name -like "gdal-*-$tag-$tag-win_amd64.whl" } | Select-Object -First 1
    if (-not $asset) {
        throw @"
$tag 용 GDAL wheel을 릴리스 $($rel.tag_name) 에서 찾지 못했습니다.
수동 설치: https://github.com/cgohlke/geospatial-wheels/releases 에서
gdal-*-$tag-$tag-win_amd64.whl 을 받아 다음을 실행하세요.
  .\.venv\Scripts\python.exe -m pip install <받은파일.whl>
"@
    }
    $wheelDir = Join-Path $root "vendor_wheels"
    New-Item -ItemType Directory -Force $wheelDir | Out-Null
    $dest = Join-Path $wheelDir $asset.name
    if (-not (Test-Path $dest)) {
        Write-Host "내려받는 중: $($asset.name)  ($([math]::Round($asset.size/1MB,1)) MB)"
        Invoke-WebRequest $asset.browser_download_url -OutFile $dest -UseBasicParsing
    }
    & $py -m pip install $dest
    if ($LASTEXITCODE -ne 0) { throw "GDAL wheel 설치 실패" }
}

# ---------------------------------------------------------------- 4. arosics
Step "4/6  AROSICS (②단계 전역 이동 보정)"
& $py -m pip install "arosics==1.13.2"
if ($LASTEXITCODE -ne 0) { throw "arosics 설치 실패" }

# ------------------------------------------------------------ 5. torch/kornia
Step "5/6  PyTorch + kornia (④단계 LoFTR)"
$useCuda = $false
if (-not $CpuOnly) {
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        $useCuda = $true
        Write-Host "NVIDIA GPU 감지됨 → CUDA 빌드 설치"
        & nvidia-smi --query-gpu=name --format=csv,noheader
    } else {
        Write-Host "NVIDIA GPU 없음 → CPU 빌드 설치"
    }
}
# torchvision 은 torch 와 버전이 짝이 맞아야 한다 (2.8.0 <-> 0.23.0).
# 따로 설치하면 pip 가 torch 를 최신으로 올려버려 핀이 깨진다.
if ($useCuda) {
    & $py -m pip install "torch==2.8.0" "torchvision==0.23.0" --index-url https://download.pytorch.org/whl/cu128
} else {
    & $py -m pip install "torch==2.8.0" "torchvision==0.23.0"
}
if ($LASTEXITCODE -ne 0) { throw "torch 설치 실패" }
& $py -m pip install "kornia==0.8.2" "kornia_rs==0.2.0"
if ($LASTEXITCODE -ne 0) { throw "kornia 설치 실패" }

# ------------------------------------------------------------ 6. itk-elastix
Step "6/6  itk-elastix (⑤단계 국소 보정)"
& $py -m pip install "itk==5.4.7" "itk-elastix==0.23.0"
if ($LASTEXITCODE -ne 0) { throw "itk-elastix 설치 실패" }

# ------------------------------------------------------------------- 검증
Step "설치 검증"
& $py (Join-Path $root "check_env.py")

Write-Host "`n완료. 파이프라인 전체 실행:" -ForegroundColor Green
Write-Host "  .\run_all.ps1" -ForegroundColor Green
