"""
③ 수면·모래 마스킹 (안정 지형만 남기기)

전략 페이지의 제약 ①: 기업이 배포한 SkySat ortho_visual은 RGB뿐,
NIR 밴드가 없다 -> NDWI(정석 수체지수)를 못 쓴다.

그래서 이 스크립트는 "만약 NIR이 있었다면" vs "RGB만 있을 때" 두
가지 물 마스크를 모두 만들어서 정면으로 비교한다. 우리 Sentinel-2
데이터는 NIR(B08)을 가지고 있어서, NDWI 마스크를 "정답"으로 놓고
RGB-only 방법이 얼마나 비슷하게 흉내내는지 IoU로 측정할 수 있다.
이건 실제 회사 데이터(RGB-only)로 가면 곧바로 마주칠 문제를
Sentinel-2로 미리 정량화해보는 것.

- NDWI 방법(정답): (Green-NIR)/(Green+NIR) > 0, Otsu 임계값
- RGB-only 대안: HSV 채도(S) + 밝기(V) 기반 경험적 임계값
  (물은 대체로 채도가 낮고 일정 밝기 범위) — CoastSat 계열 문서에서
  NIR이 없을 때 쓰는 대안으로 언급되는 방식을 단순화한 버전
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import rasterio
from skimage.filters import threshold_otsu


def to_uint8(img):
    img = img.astype(np.float32)
    lo, hi = np.percentile(img, 1), np.percentile(img, 99)
    img = np.clip((img - lo) / (hi - lo + 1e-6), 0, 1)
    return (img * 255).astype(np.uint8)


def ndwi_mask(green, nir):
    """정답 마스크. NDWI > 0 을 물로 판정 (McFeeters 1996 표준 정의)."""
    g, n = green.astype(np.float32), nir.astype(np.float32)
    ndwi = (g - n) / (g + n + 1e-6)
    return ndwi > 0, ndwi


def rgb_only_water_mask(r, g, b):
    """NIR 없이 RGB만으로 물을 추정하는 대안.
    물은 (1) 채도가 낮고 (2) 파랑 채널이 상대적으로 우세한 경향을 이용.
    Otsu로 자동 임계값을 잡아 사람이 손으로 튜닝하지 않게 한다."""
    rgb = np.dstack([to_uint8(r), to_uint8(g), to_uint8(b)])
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    sat = hsv[:, :, 1].astype(np.float32)
    blue_dominance = b.astype(np.float32) - r.astype(np.float32)  # 물은 보통 B>R

    sat_thresh = threshold_otsu(sat)
    water_by_sat = sat < sat_thresh
    water_by_blue = blue_dominance > threshold_otsu(blue_dominance)
    return water_by_sat & water_by_blue


def iou(mask_a, mask_b):
    inter = np.logical_and(mask_a, mask_b).sum()
    union = np.logical_or(mask_a, mask_b).sum()
    return float(inter / union) if union else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-09-16")
    ap.add_argument("--tile", default="52SBG")
    args = ap.parse_args()

    base = f"data/raw/s2_{args.date}_{args.tile}"
    with rasterio.open(f"{base}_B02.tif") as f_b, rasterio.open(f"{base}_B03.tif") as f_g, \
         rasterio.open(f"{base}_B04.tif") as f_r, rasterio.open(f"{base}_B08.tif") as f_n:
        blue, green, red, nir = f_b.read(1), f_g.read(1), f_r.read(1), f_n.read(1)

    water_ndwi, ndwi = ndwi_mask(green, nir)
    water_rgb = rgb_only_water_mask(red, green, blue)

    score = iou(water_ndwi, water_rgb)
    water_pct_ndwi = float(water_ndwi.mean() * 100)
    water_pct_rgb = float(water_rgb.mean() * 100)

    result = {
        "date": args.date,
        "ndwi_water_pct": round(water_pct_ndwi, 2),
        "rgb_only_water_pct": round(water_pct_rgb, 2),
        "iou_rgb_vs_ndwi": round(score, 4),
        "note": "실제 SkySat(회사 데이터)은 RGB뿐이라 rgb_only 방법을 써야 함. "
                "이 IoU가 낮을수록 마스킹 단계의 오차가 뒤 단계(정합·변화탐지)에 전파될 위험이 큼.",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    Path("results").mkdir(exist_ok=True)
    Path("results/mask_comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))

    # 저장: 세 장 나란히 (원본 / NDWI 정답 / RGB-only 추정)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams["font.family"] = "AppleGothic"
    matplotlib.rcParams["axes.unicode_minus"] = False

    rgb_disp = np.dstack([to_uint8(red), to_uint8(green), to_uint8(blue)])
    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    axes[0].imshow(rgb_disp); axes[0].set_title("원본 (RGB)"); axes[0].axis("off")
    axes[1].imshow(water_ndwi, cmap="Blues"); axes[1].set_title("NDWI 정답 (NIR 사용)"); axes[1].axis("off")
    axes[2].imshow(water_rgb, cmap="Blues"); axes[2].set_title(f"RGB-only 추정 (IoU={score:.2f})"); axes[2].axis("off")
    fig.suptitle("③ 수면 마스킹 — 회사 데이터 제약(NIR 없음) 재현 실험")
    fig.tight_layout()
    Path("results/figures").mkdir(parents=True, exist_ok=True)
    fig.savefig("results/figures/04_mask_ndwi_vs_rgb.png", dpi=140)
    print("그림 저장: results/figures/04_mask_ndwi_vs_rgb.png")
