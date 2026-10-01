"""
⑥ 품질 검증 — 회의록 "4-2. 정합 합격 기준"을 그대로 코드로 구현.

지표별 통과(🟢)/경고(🟡)/실패(🔴) 판정 + LoD(최소 탐지 한계) 계산.

LoD = 1.96 * sqrt(sigma_정합^2 + sigma_추출^2)
이보다 작게 움직인 구간은 "변화"로 세지 않고 "판단 불가"로 표시한다
(회의록 2-③ "견디기" 전략).
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np

# 이 스크립트는 판정 결과를 이모지(🟢🟡🔴)로 출력한다. Windows 콘솔의
# 기본 인코딩(cp949)에는 이 글자가 없어서 그냥 print하면 죽는다.
from _compat import enable_utf8_stdout

enable_utf8_stdout()


def grade(value, good_thresh, warn_thresh, lower_is_better=True):
    if value is None:
        return "🔴 실패 (측정 불가)"
    if lower_is_better:
        if value <= good_thresh:
            return "🟢 통과"
        elif value <= warn_thresh:
            return "🟡 경고"
        return "🔴 실패"
    else:
        if value >= good_thresh:
            return "🟢 통과"
        elif value >= warn_thresh:
            return "🟡 경고"
        return "🔴 실패"


def quadrant_coverage(pts, img_shape):
    """매칭점이 이미지 4분면에 고르게 분포하는지 확인 (회의록 기준: 분면당 10개 이상)."""
    h, w = img_shape
    cy, cx = h / 2, w / 2
    quads = [0, 0, 0, 0]  # TL, TR, BL, BR
    for x, y in pts:
        idx = (0 if y < cy else 2) + (0 if x < cx else 1)
        quads[idx] += 1
    return {"TL": quads[0], "TR": quads[1], "BL": quads[2], "BR": quads[3]}


def compute_lod(sigma_registration_m, sigma_extraction_m):
    return 1.96 * math.sqrt(sigma_registration_m**2 + sigma_extraction_m**2)


def build_report(rmse_px, inlier_ratio, pts_dst, img_shape, gsd_m,
                  sigma_extraction_m=1.0):
    quads = quadrant_coverage(pts_dst, img_shape) if pts_dst is not None else None
    quad_ok = quads and all(v >= 10 for v in quads.values())
    quad_warn = quads and sum(v >= 10 for v in quads.values()) >= 3

    sigma_registration_m = rmse_px * gsd_m if rmse_px is not None else None
    lod_m = (
        compute_lod(sigma_registration_m, sigma_extraction_m)
        if sigma_registration_m is not None
        else None
    )

    report = {
        "rmse_px": rmse_px,
        "rmse_grade": grade(rmse_px, 1.0, 2.0, lower_is_better=True),
        "inlier_ratio_pct": round(inlier_ratio * 100, 1) if inlier_ratio is not None else None,
        "inlier_grade": grade(
            inlier_ratio * 100 if inlier_ratio is not None else None, 50, 30, lower_is_better=False
        ),
        "quadrant_coverage": quads,
        "quadrant_grade": "🟢 통과" if quad_ok else ("🟡 경고" if quad_warn else "🔴 실패"),
        "sigma_registration_m": round(sigma_registration_m, 3) if sigma_registration_m else None,
        "sigma_extraction_m_assumed": sigma_extraction_m,
        "LoD_m": round(lod_m, 3) if lod_m else None,
        "LoD_note": "이보다 작게 움직인 구간은 '판단 불가'(노란색)로 표시하고 변화로 세지 않음",
    }
    return report


if __name__ == "__main__":
    import sys

    sys.path.append("pipeline")
    sys.path.append("pipeline/ai_matching")
    from sift_baseline import register_sift
    from loftr_run import register_loftr
    import rasterio

    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="data/raw/s2_2019-09-18_52SBG_B04.tif")
    ap.add_argument("--mov", default="data/raw/s2_2026-09-16_52SBG_B04.tif")
    ap.add_argument("--gsd", type=float, default=10.0)
    ap.add_argument("--sigma_extraction_m", type=float, default=10.0,
                     help="해안선 추출 오차 가정치(m). Sentinel-2 GSD 10m 기준 보수적으로 1픽셀 가정")
    args = ap.parse_args()

    with rasterio.open(args.ref) as r, rasterio.open(args.mov) as m:
        img_ref, img_mov = r.read(1), m.read(1)

    reports = {}
    for name, fn in [("SIFT+RANSAC", register_sift), ("LoFTR(kornia)", register_loftr)]:
        H, pa, pb, mask, n, el = fn(img_mov, img_ref)
        if H is None:
            reports[name] = {"error": "매칭 실패"}
            continue
        from metrics import reprojection_rmse
        rmse = reprojection_rmse(pa, pb, H, mask)
        inlier_pts = pb[mask.ravel().astype(bool)]
        inlier_ratio = mask.sum() / n
        reports[name] = build_report(
            rmse, inlier_ratio, inlier_pts, img_ref.shape, args.gsd, args.sigma_extraction_m
        )

    print(json.dumps(reports, ensure_ascii=False, indent=2))
    Path("results").mkdir(exist_ok=True)
    Path("results/quality_report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
