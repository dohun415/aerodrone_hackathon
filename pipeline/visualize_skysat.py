"""SkySat(회사 배포자료) 관련 그림 3종 생성.

  08_skysat_coverage.png    촬영 스트립이 AOI를 얼마나 덮는지
  09_skysat_s2_crop.png     공통 유효 영역으로 자른 정합 입력
  10_skysat_alignment.png   SkySat vs Sentinel-2 정렬 상태 검증
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
from _compat import apply_korean_font, ensure_ascii_proj_data

ensure_ascii_proj_data()

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio

apply_korean_font()
OUT = Path("results/figures")
OUT.mkdir(parents=True, exist_ok=True)
RAW = Path("data/raw")


def rd(name):
    with rasterio.open(RAW / name) as s:
        return s.read(1)


def u8(x, only_valid=True):
    """1~99 퍼센타일 스트레치. nodata(0)는 통계에서 뺀다."""
    x = x.astype(np.float32)
    v = x[x > 0] if only_valid else x.ravel()
    lo, hi = np.percentile(v, 1), np.percentile(v, 99)
    return np.clip((x - lo) / (hi - lo + 1e-6), 0, 1)


def rgb(prefix):
    return np.dstack([u8(rd(f"{prefix}_{b}.tif")) for b in ("B04", "B03", "B02")])


# ---------------------------------------------- 08. 커버리지
sk_b04 = rd("sk_2026-08-17_GYD_B04.tif")
valid = sk_b04 > 0
s2 = rd("s2_2026-08-12_51SYB_B04.tif")

fig, ax = plt.subplots(1, 3, figsize=(17, 4.3))
ax[0].imshow(rgb("sk_2026-08-17_GYD"))
ax[0].set_title("SkySat 2026-08-17 (0.5m → 10m)")
ax[1].imshow(valid, cmap="gray")
ax[1].set_title(f"유효 커버리지 {100 * valid.mean():.1f}% (나머지는 촬영 안 됨)")
ax[2].imshow(u8(s2), cmap="gray")
ax[2].contour(valid, levels=[0.5], colors="r", linewidths=1.2)
ax[2].set_title("Sentinel-2 2026-08-12 + SkySat 촬영범위(빨강)")
for a in ax:
    a.axis("off")
fig.suptitle("SkySat 배포영상 커버리지 — 대각선 촬영 스트립이라 AOI를 다 덮지 않는다")
fig.tight_layout()
fig.savefig(OUT / "08_skysat_coverage.png", dpi=130)
plt.close(fig)
print("saved 08_skysat_coverage.png")

# ---------------------------------------------- 09. 공통 유효 영역
skc = rd("sk_2026-08-17_GYD_B04_crop.tif")
s2c = rd("s2_2026-08-12_51SYB_B04_crop.tif")
fig, ax = plt.subplots(1, 3, figsize=(17, 3.9))
ax[0].imshow(u8(skc), cmap="gray")
ax[0].set_title("SkySat 2026-08-17 (crop)")
ax[1].imshow(u8(s2c), cmap="gray")
ax[1].set_title("Sentinel-2 2026-08-12 (crop)")
ax[2].imshow(np.dstack([u8(skc), u8(s2c), u8(s2c)]))
ax[2].set_title("중첩 (빨강=SkySat, 청록=S2)")
for a in ax:
    a.axis("off")
fig.suptitle(f"공통 유효 영역 {skc.shape[0]}x{skc.shape[1]} (10m) — 이종 센서 정합 입력")
fig.tight_layout()
fig.savefig(OUT / "09_skysat_s2_crop.png", dpi=140)
plt.close(fig)
print("saved 09_skysat_s2_crop.png")

# ---------------------------------------------- 10. 정렬 검증
a, b = u8(skc), u8(s2c)


def corr(x, y):
    m = (x > 0) & (y > 0)
    return float(np.corrcoef(x[m], y[m])[0, 1])


fig, ax = plt.subplots(1, 3, figsize=(17, 3.9))
ax[0].imshow(np.dstack([a, b, b]))
ax[0].set_title(f"중첩 — 상관계수 {corr(a, b):.3f}")
ax[0].axis("off")
# 섬 윤곽만 겹쳐 보기
lv_a, lv_b = np.percentile(a, 93), np.percentile(b, 93)
ax[1].contour(a, levels=[lv_a], colors="red", linewidths=1.0)
ax[1].contour(b, levels=[lv_b], colors="cyan", linewidths=1.0)
ax[1].set_aspect("equal")
ax[1].invert_yaxis()
ax[1].set_title("해안선 윤곽 (빨강=SkySat, 청록=S2)")
ax[1].axis("off")
# 체커보드
n = 12
h, w = a.shape
ck = a.copy()
for i in range(0, h, h // n + 1):
    for j in range(0, w, w // n + 1):
        if ((i // (h // n + 1)) + (j // (w // n + 1))) % 2:
            ck[i:i + h // n + 1, j:j + w // n + 1] = b[i:i + h // n + 1, j:j + w // n + 1]
ax[2].imshow(ck, cmap="gray")
ax[2].set_title("체커보드 (경계에서 해안선이 이어지면 정렬됨)")
ax[2].axis("off")
fig.suptitle("SkySat vs Sentinel-2 정렬 검증 — 두 영상 모두 EPSG:32652, 10m 동일 격자")
fig.tight_layout()
fig.savefig(OUT / "10_skysat_alignment.png", dpi=140)
plt.close(fig)
print("saved 10_skysat_alignment.png")
