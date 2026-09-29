"""
⑤ 국소 보정 (회의록의 AROSICS Local / Elastix 역할)

AROSICS는 이 환경의 Homebrew 문제로 설치 불가(README 참고). 대신
정합 참고자료 페이지에도 함께 소개된 ITKElastix(pip install
itk-elastix, GDAL 불필요)로 같은 역할 — "전역 이동으로는 못 잡는,
영역마다 다르게 어긋난 부분"을 B-스플라인 비강체 정합으로 보정 —
을 수행한다.

전역 보정(②)이 이미지 전체를 하나의 이동/회전으로 맞춘 뒤, 국소
보정(⑤)은 격자 단위로 남은 잔차를 폈다 접듯이 미세 보정한다.
기복변위(A2)처럼 "산 부분만 유독 더 어긋나는" 상황에 특히 유효.
"""
import argparse
import json
import time
from pathlib import Path

import itk
import numpy as np
import rasterio


def to_float32(img):
    img = img.astype(np.float32)
    lo, hi = np.percentile(img, 1), np.percentile(img, 99)
    return np.clip((img - lo) / (hi - lo + 1e-6), 0, 1)


def bspline_register(fixed_np, moving_np):
    """B-스플라인 비강체 정합. 반환: 보정된 moving 영상, 각 격자점의 이동량 통계."""
    t0 = time.time()
    fixed = itk.image_view_from_array(to_float32(fixed_np))
    moving = itk.image_view_from_array(to_float32(moving_np))

    param_obj = itk.ParameterObject.New()
    param_map = param_obj.GetDefaultParameterMap("bspline", 2)
    param_map["MaximumNumberOfIterations"] = ["128"]
    param_obj.AddParameterMap(param_map)

    result, transform_params = itk.elastix_registration_method(
        fixed, moving, parameter_object=param_obj, log_to_console=False
    )
    elapsed = time.time() - t0
    return itk.array_from_image(result), elapsed


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixed", default="data/raw/s2_2019-09-18_52SBG_B04.tif")
    ap.add_argument("--moving", default="data/raw/s2_2026-09-16_52SBG_B04.tif")
    args = ap.parse_args()

    with rasterio.open(args.fixed) as f, rasterio.open(args.moving) as m:
        fixed_img, moving_img = f.read(1), m.read(1)

    print("B-스플라인 국소 보정 실행 중 (전역보정 이후 남은 잔차를 격자 단위로 미세보정)...")
    corrected, elapsed = bspline_register(fixed_img, moving_img)

    # 보정 전/후 밝기차(잔차)의 표준편차로 "국소 어긋남이 줄었는지"를 간접 확인
    before_resid = np.std(to_float32(fixed_img) - to_float32(moving_img))
    after_resid = np.std(to_float32(fixed_img) - corrected)

    result = {
        "elapsed_s": round(elapsed, 2),
        "residual_std_before": round(float(before_resid), 4),
        "residual_std_after": round(float(after_resid), 4),
        "residual_reduction_pct": round(float((1 - after_resid / before_resid) * 100), 1),
        "note": "잔차 표준편차가 줄어들수록 국소 보정이 효과가 있었다는 뜻. "
                "단, 7년 시차의 실제 지표 변화도 잔차에 섞여 있어 이 수치가 "
                "곧바로 '정합 오차 감소량'과 같지는 않음 — 참고용 지표.",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    Path("results").mkdir(exist_ok=True)
    Path("results/local_correction.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
