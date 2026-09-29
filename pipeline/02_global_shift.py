"""
② 전역 이동 보정 (회의록의 AROSICS Global 역할)

이 macOS 환경은 Homebrew가 깨져 있어(freetype/fontconfig 등 여러
/opt/homebrew/opt/* 링크가 고아 상태) `brew install gdal`이 계속
실패하고, 그래서 AROSICS(내부적으로 GDAL 바인딩 필요)를 설치할 수
없었다. 대신 정합 개념자료의 "AROSICS 결과 교차검증"용으로 함께
소개된 scikit-image의 phase_cross_correlation으로 같은 역할
(영상 전체의 X/Y 서브픽셀 이동량 추정)을 수행한다.

원리: 두 영상을 푸리에 변환해서 위상 차이로 전체 이동량을 한 번에
추정. AROSICS Global과 동일하게 "국소 변형"은 못 잡고 "전체가
통째로 얼마나 밀렸는가"만 잡는다 — 그래서 이름 그대로 "전역" 보정.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import rasterio
from skimage.registration import phase_cross_correlation


def to_float(img):
    return img.astype(np.float32)


def estimate_global_shift(img_ref, img_mov, upsample_factor=100):
    """img_mov를 img_ref에 맞추려면 몇 픽셀 이동해야 하는지 서브픽셀로 추정.
    upsample_factor=100 -> 1/100 픽셀 단위까지 추정 (AROSICS의 서브픽셀 정확도에 대응)."""
    t0 = time.time()
    shift, error, diffphase = phase_cross_correlation(
        to_float(img_ref), to_float(img_mov), upsample_factor=upsample_factor
    )
    # shift = (row_shift, col_shift) = (dy, dx) : img_mov를 이만큼 옮기면 img_ref와 맞음
    return {
        "dy_px": float(shift[0]),
        "dx_px": float(shift[1]),
        "translation_error": float(error),  # 정규화된 RMS 오차 (낮을수록 신뢰도 높음)
        "elapsed_s": time.time() - t0,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="data/raw/s2_2019-09-18_52SBG_B04.tif")
    ap.add_argument("--mov", default="data/raw/s2_2026-09-16_52SBG_B04.tif")
    ap.add_argument("--gsd", type=float, default=10.0)
    args = ap.parse_args()

    with rasterio.open(args.ref) as r, rasterio.open(args.mov) as m:
        img_ref, img_mov = r.read(1), m.read(1)

    result = estimate_global_shift(img_ref, img_mov)
    result["dx_m"] = round(result["dx_px"] * args.gsd, 3)
    result["dy_m"] = round(result["dy_px"] * args.gsd, 3)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    Path("results").mkdir(exist_ok=True)
    Path("results/global_shift.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
