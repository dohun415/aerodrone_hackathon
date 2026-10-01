"""
결과를 눈으로 확인할 수 있는 이미지 3종을 results/figures/ 에 저장.
1) 실제 2019 vs 2026 두 장면 나란히
2) 합성 벤치마크: 어긋난 상태(전) vs SIFT로 보정한 상태(후) 체커보드
3) 정합 전/후 오차 막대그래프 (합성 벤치마크 수치)
"""
import json
import sys
from pathlib import Path

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
# 한글 폰트는 OS마다 다르다(Windows 맑은 고딕 / macOS AppleGothic).
from _compat import apply_korean_font
apply_korean_font()
import numpy as np
import rasterio

sys.path.append(str(Path(__file__).resolve().parent))
from ai_matching.sift_baseline import register_sift, to_uint8

OUT = Path("results/figures")
OUT.mkdir(parents=True, exist_ok=True)


def checkerboard(a, b, n=10):
    h, w = a.shape
    out = a.copy()
    bs_h, bs_w = h // n, w // n
    for i in range(n):
        for j in range(n):
            if (i + j) % 2 == 0:
                y0, y1 = i * bs_h, (i + 1) * bs_h
                x0, x1 = j * bs_w, (j + 1) * bs_w
                out[y0:y1, x0:x1] = b[y0:y1, x0:x1]
    return out


def fig_real_pair():
    with rasterio.open("data/raw/s2_2019-09-18_52SBG_B04.tif") as a, \
         rasterio.open("data/raw/s2_2026-09-16_52SBG_B04.tif") as b:
        img_a, img_b = to_uint8(a.read(1)), to_uint8(b.read(1))
    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    axes[0].imshow(img_a, cmap="gray"); axes[0].set_title("Sentinel-2  2019-09-18"); axes[0].axis("off")
    axes[1].imshow(img_b, cmap="gray"); axes[1].set_title("Sentinel-2  2026-09-16"); axes[1].axis("off")
    fig.suptitle("옹진 서해 도서 AOI — 실제 다시기 Sentinel-2 (7년 차)")
    fig.tight_layout()
    fig.savefig(OUT / "01_real_pair.png", dpi=140)
    plt.close(fig)


def fig_synthetic_before_after():
    interim = Path("data/interim")
    src = np.load(interim / "synthetic_src.npy")
    warped = np.load(interim / "synthetic_warped.npy")
    meta = json.loads((interim / "synthetic_meta.json").read_text(encoding="utf-8"))

    src8, warped8 = to_uint8(src), to_uint8(warped)
    before = checkerboard(src8, warped8)

    H_est, pts_a, pts_b, mask, *_ = register_sift(warped, src)
    corrected = cv2.warpPerspective(warped8, H_est, (src.shape[1], src.shape[0]))
    after = checkerboard(src8, corrected)

    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    axes[0].imshow(before, cmap="gray")
    axes[0].set_title(f"정합 전 (인위적 오차 {meta['tx_m']}m,{meta['ty_m']}m + 회전{meta['rot_deg']}°)")
    axes[0].axis("off")
    axes[1].imshow(after, cmap="gray")
    axes[1].set_title("SIFT+RANSAC 보정 후 (체커보드 경계가 사라짐)")
    axes[1].axis("off")
    fig.suptitle("합성 벤치마크: 구글맵-실사 어긋남 재현 및 보정")
    fig.tight_layout()
    fig.savefig(OUT / "02_synthetic_before_after.png", dpi=140)
    plt.close(fig)


def fig_error_bars():
    results = json.loads(Path("results/synthetic_benchmark.json").read_text(encoding="utf-8"))
    names = [r["method"] for r in results]
    errs = [r["corner_err_m_mean"] for r in results]
    fig, ax = plt.subplots(figsize=(5, 4))
    bars = ax.bar(names, errs, color=["#0E6A78", "#8C6A3E"])
    ax.set_ylabel("복원 오차 평균 (m)")
    ax.set_title("합성 120m/-70m 오차 복원 정확도\n(낮을수록 좋음)")
    for b, e in zip(bars, errs):
        ax.text(b.get_x() + b.get_width() / 2, e, f"{e:.2f}m", ha="center", va="bottom")
    fig.tight_layout()
    fig.savefig(OUT / "03_error_bars.png", dpi=140)
    plt.close(fig)


if __name__ == "__main__":
    fig_real_pair()
    fig_synthetic_before_after()
    fig_error_bars()
    print("저장 완료:", list(OUT.glob("*.png")))
