"""
② 전역 이동 보정 (회의록의 AROSICS Global 역할)

[2026-09-30 갱신] 이 macOS 환경의 Homebrew가 깨져 있었던 문제
(freetype/fontconfig/little-cms2가 심볼릭 링크가 아니라 고아
디렉터리 상태)를 해결했다 — 해당 opt 디렉터리를 지우고
`brew link --overwrite`로 재연결한 뒤 `brew install gdal`이
정상적으로 끝까지 성공. 이제 `pip install arosics`도 정상 설치되어
정합 참고자료 페이지가 1순위로 추천한 진짜 AROSICS Global을 쓴다.

phase_cross_correlation(순수 pip, GDAL 불필요) 버전은
`estimate_global_shift_phasecorr()`로 남겨뒀다 — AROSICS 없는
환경에서의 대체 경로 + 교차검증용.

AROSICS Global 원리: 두 영상(둘 다 지오코딩된 GeoTIFF) 사이에서
공통 윈도우를 잡아 X/Y 서브픽셀 이동량만 추정. 국소 변형은
⑤(itk-elastix)가 담당.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import rasterio
from skimage.registration import phase_cross_correlation

try:
    from arosics import COREG
    AROSICS_AVAILABLE = True
except ImportError:
    AROSICS_AVAILABLE = False


def to_float(img):
    return img.astype(np.float32)


def estimate_global_shift_phasecorr(img_ref, img_mov, upsample_factor=100):
    """대체 경로: scikit-image phase_cross_correlation (배열 입력, GDAL 불필요)."""
    t0 = time.time()
    shift, error, diffphase = phase_cross_correlation(
        to_float(img_ref), to_float(img_mov), upsample_factor=upsample_factor
    )
    return {
        "method": "phase_cross_correlation",
        "dy_px": float(shift[0]),
        "dx_px": float(shift[1]),
        "translation_error": float(error),
        "elapsed_s": time.time() - t0,
    }


def estimate_global_shift_arosics(ref_path, mov_path, max_shift=20, wp=(None, None), ws=(256, 256)):
    """진짜 AROSICS Global. 파일 경로(지오코딩 포함)를 직접 입력받는다.

    wp(윈도우 중심 map좌표)를 지정하지 않으면 영상 중앙을 쓰는데,
    우리 AOI는 98.8%가 바다라서 중앙이 특징점 없는 물일 확률이 높다
    (실제로 기본값으로 돌리면 "No match found in the given window"
    실패가 남). 그래서 ③단계에서 찾은 육지(섬) 중심 좌표를 넘겨준다
    — 이 자체가 "회의록 4장 지형별 정합 기준(안정 지형에서 기준점을
    뽑아야 한다)"이 왜 필요한지 보여주는 실증이다."""
    t0 = time.time()
    CR = COREG(ref_path, mov_path, ws=ws, wp=wp, max_shift=max_shift, q=True)
    CR.calculate_spatial_shifts()
    return {
        "method": "AROSICS COREG (Global)",
        "dx_px": float(CR.x_shift_px),
        "dy_px": float(CR.y_shift_px),
        "dx_m": float(CR.x_shift_map),
        "dy_m": float(CR.y_shift_map),
        "reliability_pct": float(CR.shift_reliability) if CR.shift_reliability is not None else None,
        "elapsed_s": time.time() - t0,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="data/raw/s2_2019-09-18_52SBG_B04.tif")
    ap.add_argument("--mov", default="data/raw/s2_2026-09-16_52SBG_B04.tif")
    ap.add_argument("--gsd", type=float, default=10.0)
    ap.add_argument("--force-phasecorr", action="store_true", help="AROSICS 있어도 대체 경로만 실행")
    ap.add_argument("--wp_x", type=float, default=None, help="AROSICS 매칭 윈도우 중심 map X좌표 (지정 안 하면 영상 중앙)")
    ap.add_argument("--wp_y", type=float, default=None, help="AROSICS 매칭 윈도우 중심 map Y좌표")
    args = ap.parse_args()

    result = {}

    if AROSICS_AVAILABLE and not args.force_phasecorr:
        # 기본(영상 중앙)과, 지정됐다면 특정 위치(예: 육지) 둘 다 시도해서 비교
        try:
            result["arosics_center"] = estimate_global_shift_arosics(args.ref, args.mov)
        except Exception as e:
            result["arosics_center_error"] = str(e)
        if args.wp_x is not None:
            try:
                result["arosics_on_land"] = estimate_global_shift_arosics(
                    args.ref, args.mov, wp=(args.wp_x, args.wp_y)
                )
            except Exception as e:
                result["arosics_on_land_error"] = str(e)
    else:
        result["arosics_error"] = "설치 안 됨" if not AROSICS_AVAILABLE else "건너뜀(--force-phasecorr)"

    with rasterio.open(args.ref) as r, rasterio.open(args.mov) as m:
        img_ref, img_mov = r.read(1), m.read(1)
    result["phasecorr"] = estimate_global_shift_phasecorr(img_ref, img_mov)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    Path("results").mkdir(exist_ok=True)
    Path("results/global_shift.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
