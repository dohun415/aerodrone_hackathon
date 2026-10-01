<#
.SYNOPSIS
  정합 파이프라인 6단계를 처음부터 끝까지 실행한다 (Windows).

.DESCRIPTION
  README의 "빠른 재현" 순서를 그대로 따라간다. 각 단계의 결과 JSON은
  results/ 에, 그림은 results/figures/ 에 저장된다.

  data/raw/ 에 GeoTIFF가 이미 있으면 00단계(다운로드)는 건너뛴다.
  -Fetch 를 주면 Sentinel-2를 새로 받는다(인터넷 필요).

.EXAMPLE
  .\run_all.ps1
  .\run_all.ps1 -Fetch
#>
[CmdletBinding()]
param(
    # Sentinel-2 원본을 Planetary Computer에서 새로 내려받는다
    [switch]$Fetch
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py   = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    throw "가상환경이 없습니다. 먼저 .\setup_windows.ps1 을 실행하세요."
}

# 콘솔·파일 입출력을 UTF-8로 고정한다. Windows 기본은 cp949라서
# ⑥단계가 출력하는 판정 이모지(🟢🟡🔴)에서 죽는다.
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Push-Location $root       # 스크립트들이 data/, results/ 를 상대경로로 쓴다
try {
    $failed = @()

    function Run-Step {
        param([string]$Label, [string]$Script, [string[]]$ScriptArgs = @())
        Write-Host "`n=== $Label ===" -ForegroundColor Cyan
        & $py $Script @ScriptArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Host "실패: $Label" -ForegroundColor Red
            $script:failed += $Label
        }
    }

    if ($Fetch -or -not (Get-ChildItem (Join-Path $root "data\raw") -Filter *.tif -EA SilentlyContinue)) {
        Run-Step "00 데이터 확보 (Sentinel-2)" "pipeline\00_fetch_data.py" @("--bands", "B04,B03,B02,B08")
    } else {
        Write-Host "`n=== 00 데이터 확보 — data/raw 에 GeoTIFF가 이미 있어 건너뜀 (-Fetch 로 강제) ===" -ForegroundColor DarkGray
    }

    Run-Step "01' 드론 시점 보정"  "pipeline\01_drone_view_rectify.py" @("--top_margin", "0.22")

    # ②단계 AROSICS는 매칭 윈도우를 '육지(섬)' 위에 놓아야 성공한다.
    # 영상 중앙은 98.8%가 바다라 실패하는데, 그 실패 자체도 결과에 기록된다.
    Run-Step "02 전역 이동 보정 (AROSICS)" "pipeline\02_global_shift.py" @(
        "--ref", "data/raw/s2_2019-09-18_52SBG_B04.tif",
        "--mov", "data/raw/s2_2026-09-16_52SBG_B04.tif",
        "--wp_x", "232210.74", "--wp_y", "4119811.13")

    Run-Step "03 수면·모래 마스킹" "pipeline\03_stable_mask.py" @("--date", "2026-09-16", "--tile", "52SBG")

    Run-Step "04 AI 정밀정합 — SIFT"  "pipeline\ai_matching\sift_baseline.py" @(
        "--src", "data/raw/s2_2019-09-18_52SBG_B04.tif",
        "--dst", "data/raw/s2_2026-09-16_52SBG_B04.tif")
    Run-Step "04 AI 정밀정합 — LoFTR" "pipeline\ai_matching\loftr_run.py" @(
        "--src", "data/raw/s2_2019-09-18_52SBG_B04.tif",
        "--dst", "data/raw/s2_2026-09-16_52SBG_B04.tif")

    Run-Step "05 국소 보정 (itk-elastix)" "pipeline\05_local_correction.py"
    Run-Step "06 품질 검증 (합격기준 + LoD)" "pipeline\06_quality_report.py"

    Run-Step "합성 벤치마크 — 생성" "pipeline\make_synthetic_pair.py"
    Run-Step "합성 벤치마크 — 실행" "pipeline\run_synthetic_bench.py"

    Run-Step "시연 화면 - 어긋남 슬라이더" "pipeline\shift_sweep_demo.py"
    Run-Step "그림 생성" "pipeline\visualize.py"

    Write-Host ""
    if ($failed.Count -gt 0) {
        Write-Host "실패한 단계: $($failed -join ', ')" -ForegroundColor Red
        exit 1
    }
    Write-Host "전체 완료. 결과: results\*.json, 그림: results\figures\*.png" -ForegroundColor Green
}
finally {
    Pop-Location
}
