"""
00d. 공통 유효 영역으로 잘라내기 (이종 센서 정합 전처리)

왜 필요한가
-----------
SkySat 배포영상은 AOI 사각형 전체가 아니라 **대각선 촬영 스트립**이라,
AOI 격자에 올리면 61%가 nodata(0)다. 이 상태로 정합을 돌리면 두 가지
문제가 동시에 생긴다:

1. **정규화가 뭉개진다.** 정합 스크립트의 `to_uint8()`은 1~99 퍼센타일로
   대비를 늘리는데, 화소의 61%가 0이면 퍼센타일이 전부 nodata 쪽으로
   끌려가서 실제 지표의 밝기 차이가 좁은 구간에 눌린다.
2. **가짜 경계가 생긴다.** nodata와 영상의 경계는 아주 강한 직선 에지라
   SIFT가 여기에 특징점을 몰아 잡는다. Sentinel 쪽에는 그런 경계가
   없으니 매칭이 안 되고, 매칭 예산만 잡아먹는다.

실제로 자르기 전에는 매칭점이 13~19개뿐이었고 ⑥단계 인라이어 판정이
🔴 실패였다.

무엇을 하는가
-------------
기준 영상(SkySat)의 유효화소 마스크 안에서 **완전히 유효한 최대 직사각형**
을 찾고(히스토그램 최대직사각형 O(H*W)), 주어진 모든 래스터를 그 창으로
똑같이 잘라낸다. 두 영상이 같은 격자 위에 있으므로 같은 행·열로 자르면
지리적으로도 정확히 같은 영역이 된다.

    python pipeline/00d_common_valid_crop.py \
        --mask-from data/raw/sk_2026-08-17_GYD_B04.tif \
        --rasters data/raw/sk_2026-08-17_GYD_B04.tif,data/raw/s2_2026-08-12_51SYB_B04.tif \
        --suffix _crop
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

sys.path.append(str(Path(__file__).resolve().parent))
from _compat import ensure_ascii_proj_data

ensure_ascii_proj_data()


def largest_rectangle(mask: np.ndarray):
    """True로만 채워진 최대 넓이 축정렬 직사각형을 찾는다.

    각 행까지의 연속 True 높이를 세고(histogram), 행마다
    "히스토그램에서 최대 직사각형"을 스택으로 구한다. O(H*W).
    반환: (row0, col0, height, width)
    """
    h, w = mask.shape
    heights = np.zeros(w, dtype=np.int32)
    best = (0, 0, 0, 0)
    best_area = 0

    for r in range(h):
        heights = np.where(mask[r], heights + 1, 0)
        # 히스토그램 최대 직사각형 (스택)
        stack = []           # (시작 열, 높이)
        for c in range(w + 1):
            cur = heights[c] if c < w else 0
            start = c
            while stack and stack[-1][1] >= cur:
                s, ht = stack.pop()
                area = ht * (c - s)
                if area > best_area:
                    best_area = area
                    best = (r - ht + 1, s, ht, c - s)
                start = s
            stack.append((start, cur))
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mask-from", required=True,
                    help="유효화소 마스크를 만들 기준 래스터 (0 = nodata)")
    ap.add_argument("--rasters", required=True,
                    help="같은 창으로 자를 래스터들 (쉼표 구분). 모두 같은 격자여야 함")
    ap.add_argument("--suffix", default="_crop")
    ap.add_argument("--min-side", type=int, default=64, help="이보다 작으면 실패 처리")
    args = ap.parse_args()

    with rasterio.open(args.mask_from) as m:
        base = m.read(1)
        base_shape, base_transform, base_crs = base.shape, m.transform, m.crs
    valid = base > 0
    print(f"마스크 기준 : {args.mask_from}")
    print(f"              {base_shape}, 유효화소 {100 * valid.mean():.1f}%")

    r0, c0, hh, ww = largest_rectangle(valid)
    if min(hh, ww) < args.min_side:
        raise SystemExit(f"유효 직사각형이 너무 작습니다: {hh}x{ww}")
    frac = (hh * ww) / valid.size
    print(f"최대 유효 사각형: row {r0}~{r0 + hh}, col {c0}~{c0 + ww}  "
          f"({hh}x{ww}, AOI의 {100 * frac:.1f}%)")
    print(f"                  이 창 안 유효화소: {100 * valid[r0:r0 + hh, c0:c0 + ww].mean():.2f}%\n")

    window = Window(c0, r0, ww, hh)
    written = []
    for path in [p.strip() for p in args.rasters.split(",") if p.strip()]:
        p = Path(path)
        with rasterio.open(p) as src:
            if src.shape != base_shape:
                raise SystemExit(f"격자가 다릅니다: {p} {src.shape} != {base_shape}")
            data = src.read(1, window=window)
            profile = src.profile.copy()
            profile.update(height=hh, width=ww,
                           transform=src.window_transform(window),
                           compress="deflate")
            profile.pop("blockxsize", None)
            profile.pop("blockysize", None)
            profile.pop("tiled", None)
        out = p.with_name(p.stem + args.suffix + p.suffix)
        with rasterio.open(out, "w", **profile) as dst:
            dst.write(data, 1)
        nz = 100 * (data > 0).mean()
        print(f"  {p.name}\n    -> {out.name}  {data.shape}  유효 {nz:.1f}%  "
              f"min={data.min()} max={data.max()}")
        written.append(str(out))

    meta = {
        "mask_from": args.mask_from,
        "window": {"row_off": int(r0), "col_off": int(c0),
                   "height": int(hh), "width": int(ww)},
        "aoi_fraction_pct": round(100 * frac, 2),
        "outputs": written,
        "note": "SkySat 촬영 스트립이 대각선이라 AOI의 61%가 nodata였다. "
                "정규화 왜곡과 nodata 경계의 가짜 에지를 없애기 위해 "
                "완전히 유효한 최대 직사각형으로 두 영상을 동일하게 잘랐다.",
    }
    meta_path = Path("data/raw") / "common_valid_crop.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8", newline="\n")
    print(f"\n메타데이터: {meta_path}")


if __name__ == "__main__":
    main()
