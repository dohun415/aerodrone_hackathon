"""
시연 화면 ④ "어긋남 슬라이더" (회의록 5-2, ⭐ 최우선 시연 포인트)

"지도 영상과 실제 사진이 미묘하게 어긋나 있어 AI가 정확히 판별하기
어렵다"는 기업의 문제 정의를 그대로 재현한다.

같은 영상(진짜 변화 없음)에 인위적으로 0~10px 이동을 주고,
① 기존 방식: 정합 없이 그냥 두 영상을 빼서 "변화"를 판정
② 우리 방식: SIFT로 먼저 정합한 뒤 빼서 "변화"를 판정
두 방식의 "가짜 변화 면적 비율"이 이동량에 따라 어떻게 달라지는지 비교.

기대 결과: ①은 이동량에 비례해 가짜 변화가 급증, ②는 정합이
성공하는 한 낮은 수준에서 유지됨.
"""
import json
import sys
from pathlib import Path

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio

# 한글 폰트는 OS마다 다르다(Windows 맑은 고딕 / macOS AppleGothic).
from _compat import apply_korean_font
apply_korean_font()

sys.path.append("pipeline")
sys.path.append("pipeline/ai_matching")
from sift_baseline import register_sift, to_uint8


DIFF_THRESH = 20  # 0~255 스케일에서 "변화"로 판정하는 밝기차 임계값 (naive/ours 동일하게 적용해 공정 비교)


def shift_image(img_u8, dx):
    """오른쪽으로 dx 픽셀 이동 (경계는 복제해서 이동 자체로 생기는 빈 영역을 최소화)."""
    M = np.float32([[1, 0, dx], [0, 1, 0]])
    return cv2.warpAffine(img_u8, M, (img_u8.shape[1], img_u8.shape[0]), borderMode=cv2.BORDER_REPLICATE)


def valid_crop(shape, dx, margin=5):
    """이동으로 생기는 가장자리와 여유분을 제외한 공통 유효 영역."""
    h, w = shape
    pad = int(abs(dx)) + margin
    return slice(pad, h - pad), slice(pad, w - pad)


def false_change_pct(a, b, thresh=DIFF_THRESH):
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return float((diff > thresh).mean() * 100)


def run_sweep(img_u8, shifts=range(0, 11)):
    rows = []
    for dx in shifts:
        shifted = shift_image(img_u8, dx)
        rs, cs = valid_crop(img_u8.shape, dx)

        # ① 기존 방식: 정합 없이 그냥 비교
        naive_pct = false_change_pct(img_u8[rs, cs], shifted[rs, cs])

        # ② 우리 방식: SIFT로 먼저 정합
        H, pa, pb, mask, n, el = register_sift(shifted, img_u8)
        if H is not None and mask.sum() >= 4:
            aligned = cv2.warpPerspective(shifted, H, (img_u8.shape[1], img_u8.shape[0]),
                                           borderMode=cv2.BORDER_REPLICATE)
            ours_pct = false_change_pct(img_u8[rs, cs], aligned[rs, cs])
            n_inliers = int(mask.sum())
        else:
            aligned = shifted  # 정합 실패 시 보정 없이 그대로 (최악의 경우)
            ours_pct = naive_pct
            n_inliers = 0

        rows.append({
            "shift_px": dx,
            "naive_false_change_pct": round(naive_pct, 3),
            "ours_false_change_pct": round(ours_pct, 3),
            "registration_inliers": n_inliers,
        })
        print(f"shift={dx:2d}px | 기존방식 가짜변화 {naive_pct:6.2f}% | "
              f"우리방식 가짜변화 {ours_pct:6.2f}% | 인라이어 {n_inliers}")
    return rows


def main():
    with rasterio.open("data/raw/s2_2026-09-16_52SBG_B04.tif") as f:
        img = to_uint8(f.read(1))

    rows = run_sweep(img)

    Path("results").mkdir(exist_ok=True)
    Path("results/shift_sweep.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    shifts = [r["shift_px"] for r in rows]
    naive = [r["naive_false_change_pct"] for r in rows]
    ours = [r["ours_false_change_pct"] for r in rows]

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(shifts, naive, "o-", color="#B54708", label="기존 방식 (정합 없이 비교)", linewidth=2)
    ax.plot(shifts, ours, "o-", color="#0E6A78", label="우리 방식 (SIFT 정합 후 비교)", linewidth=2)
    ax.set_xlabel("인위적으로 준 어긋남 (px)")
    ax.set_ylabel("가짜 변화로 판정된 면적 비율 (%)")
    ax.set_title("어긋남 슬라이더: 정합이 오탐을 얼마나 줄이는가\n(실제 변화 없는 영상에 인위적 이동만 부여)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("results/figures/05_shift_sweep.png", dpi=140)
    print("\n그림 저장: results/figures/05_shift_sweep.png")


if __name__ == "__main__":
    main()
