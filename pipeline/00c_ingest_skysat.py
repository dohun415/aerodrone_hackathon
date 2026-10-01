"""
00c. Planet SkySat `ortho_visual` -> 파이프라인 입력 GeoTIFF

회사 배포자료(`SV_202608_GYD`, SkySatCollect, 2026-08-17)를 ①단계
"좌표·해상도 통일"을 거쳐 Sentinel-2와 같은 격자에 올린다.

배포자료 실측 사양 (STAC 메타데이터에서 확인)
-------------------------------------------
    id              20260817_231616_ssc1_u0002
    촬영            2026-08-17T23:16:16Z (UTC)
    view_angle      28.9°  (경사촬영 — 전략 문서 그대로)
    ground_control_ratio 0.17  (회의록의 "GCR 0.17" 절대측위 오차 근거)
    pixel_resolution 0.5 m  (gsd 0.78 m)
    CRS             EPSG:32652  <- Sentinel-2 데이터(52SBG)와 동일
    밴드            4개 uint8 = R, G, B, **alpha**  (NIR 없음)

여기서 확인되는 두 가지
-----------------------
1) **NIR이 없다.** 전략 문서 제약①이 실물로 확인됐다 — 이 영상으로는
   NDWI를 못 쓴다. ③단계의 RGB-only 경로가 유일한 선택지다.
2) **좌표계는 이미 같다(EPSG:32652).** 그래서 ①단계에서 실제로 해야
   하는 일은 재투영이 아니라 **해상도 통일**(0.5m -> 10m, 20배)이다.

해상도 통일 방향
----------------
Sentinel(10m)을 0.5m로 올리면 없는 정보를 지어내는 셈이고 화소 수가
400배(8억 화소)가 되어 비현실적이다. 그래서 **SkySat을 10m로 내린다.**
20배 축소이므로 리샘플링은 `average`(면적 평균)를 쓴다 — `bilinear`는
20배 축소에서 앨리어싱이 생긴다.

    python pipeline/00c_ingest_skysat.py \
        --visual data/raw/SV_202608_GYD/SkySatCollect/20260817_231616_ssc1_u0002_visual.tif \
        --match data/raw/s2_2026-08-12_51SYB_B04.tif
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window, from_bounds

sys.path.append(str(Path(__file__).resolve().parent))
from _compat import ensure_ascii_proj_data

ensure_ascii_proj_data()

AOI_BBOX_WGS84 = (125.868, 37.139, 126.060, 37.249)

# SkySat visual 은 R,G,B,alpha 순. Sentinel 밴드에 대응시켜 이름 붙인다
# (B04=red 665nm, B03=green 560nm, B02=blue 490nm).
BAND_MAP = {"B04": 1, "B03": 2, "B02": 3}


def read_clip(src, band_idx, aoi_wgs84):
    """AOI만 윈도우 read (00_fetch_data.py의 save_aoi_clip과 같은 방식).

    ⚠️ 래스터 경계 밖으로 나가는 window를 그대로 쓰면 안 된다.
    SkySat 촬영 스트립은 AOI보다 작아서 `from_bounds`가 음수 오프셋
    (row_off=-896, col_off=-112)을 준다. 이때
      - `src.read(window=...)` 는 **겹치는 부분만** 돌려주고(배열이 작아짐)
      - `src.window_transform(window)` 는 **요청한 원점** 그대로를 돌려준다
    두 값이 어긋나서, 잘린 배열에 잘못된 좌표가 붙는다. 실제로 이 버그로
    SkySat이 (dx -55.8m, dy +448.2m) 어긋난 것처럼 보였다 — 마치 절대측위
    오차처럼 보이지만 순전히 전처리 실수였다.

    그래서 읽기 전에 window를 래스터 전체 영역과 교집합으로 잘라낸다.
    """
    bounds_native = transform_bounds("EPSG:4326", src.crs, *aoi_wgs84)
    window = from_bounds(*bounds_native, transform=src.transform)

    full = Window(0, 0, src.width, src.height)
    window = window.intersection(full).round_offsets().round_lengths()

    data = src.read(band_idx, window=window)
    transform = src.window_transform(window)
    assert data.shape == (int(window.height), int(window.width)), \
        f"window와 읽힌 배열이 다릅니다: {data.shape} vs {window}"
    return data, transform


def to_target_grid(data, src_transform, src_crs, match, resampling):
    """목표 격자(Sentinel-2 10m)로 리샘플링."""
    dst = np.zeros((match["height"], match["width"]), dtype=np.float32)
    reproject(
        source=data.astype(np.float32), destination=dst,
        src_transform=src_transform, src_crs=src_crs,
        dst_transform=match["transform"], dst_crs=match["crs"],
        resampling=resampling,
        src_nodata=None, dst_nodata=0,
    )
    return dst


def main():
    ap = argparse.ArgumentParser(description="SkySat ortho_visual -> 파이프라인 입력")
    ap.add_argument("--visual", required=True, help="*_visual.tif 경로")
    ap.add_argument("--match", required=True, help="이 GeoTIFF 격자에 맞춤 (Sentinel-2 10m)")
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--date", default="2026-08-17")
    ap.add_argument("--tag", default="GYD", help="파일명 태그 (굴업도)")
    ap.add_argument("--bands", default="B04,B03,B02")
    ap.add_argument("--alpha-band", type=int, default=4, help="투명도(유효화소) 밴드 번호. 0이면 없음")
    ap.add_argument("--native-clip", action="store_true",
                    help="0.5m 원해상도 AOI 잘라내기도 함께 저장 (용량 큼)")
    args = ap.parse_args()

    bands = [b.strip() for b in args.bands.split(",") if b.strip()]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with rasterio.open(args.match) as m:
        match = {"transform": m.transform, "width": m.width,
                 "height": m.height, "crs": m.crs}
    print(f"목표 격자 : {args.match}")
    print(f"            {match['crs']}  {match['height']}x{match['width']}  10m\n")

    written, native_written = {}, {}
    with rasterio.open(args.visual) as src:
        print(f"SkySat    : {Path(args.visual).name}")
        print(f"            {src.crs}  {src.height}x{src.width}  {src.res[0]}m  {src.count}밴드")
        scale = match["transform"].a / src.transform.a
        print(f"            해상도 통일: {src.res[0]}m -> {match['transform'].a}m  ({scale:.0f}배 축소, average)\n")

        # 알파 밴드로 유효화소 마스크를 만든다 (배포 영상 가장자리는 투명)
        valid_mask = None
        if args.alpha_band and src.count >= args.alpha_band:
            alpha, a_tf = read_clip(src, args.alpha_band, AOI_BBOX_WGS84)
            valid_mask = to_target_grid((alpha > 0).astype(np.float32), a_tf,
                                        src.crs, match, Resampling.average)
            print(f"[alpha] 유효화소 비율(10m 격자): {100 * (valid_mask > 0.5).mean():.2f}%\n")

        for name in bands:
            idx = BAND_MAP.get(name)
            if idx is None or idx > src.count:
                print(f"  [경고] {name}: 밴드 {idx} 없음 — 건너뜀")
                continue
            print(f"[{name}] SkySat 밴드 {idx} 읽는 중 (AOI 윈도우)...")
            data, tf = read_clip(src, idx, AOI_BBOX_WGS84)
            print(f"        원해상도 AOI: {data.shape}")

            if args.native_clip:
                np_path = out_dir / f"sk_{args.date}_{args.tag}_{name}_native05m.tif"
                prof = {"driver": "GTiff", "height": data.shape[0], "width": data.shape[1],
                        "count": 1, "dtype": "uint8", "crs": src.crs, "transform": tf,
                        "compress": "deflate"}
                with rasterio.open(np_path, "w", **prof) as d:
                    d.write(data, 1)
                native_written[name] = str(np_path)
                print(f"        원해상도 저장: {np_path.name} ({np_path.stat().st_size/1e6:.0f} MB)")

            grid = to_target_grid(data, tf, src.crs, match, Resampling.average)
            if valid_mask is not None:
                grid = np.where(valid_mask > 0.5, grid, 0)

            # 정합 스크립트들이 uint16을 기대하므로 맞춰준다 (visual은 uint8)
            out = np.clip(grid, 0, 255).astype(np.uint16)
            out_path = out_dir / f"sk_{args.date}_{args.tag}_{name}.tif"
            prof = {"driver": "GTiff", "height": match["height"], "width": match["width"],
                    "count": 1, "dtype": "uint16", "crs": match["crs"],
                    "transform": match["transform"], "compress": "deflate"}
            with rasterio.open(out_path, "w", **prof) as d:
                d.write(out, 1)
            nz = 100 * (out > 0).mean()
            print(f"        10m 저장    : {out_path.name}  유효화소 {nz:.1f}%  "
                  f"min={out.min()} max={out.max()} mean={out.mean():.1f}\n")
            written[name] = str(out_path)

    meta = {
        "source": Path(args.visual).name,
        "item_id": "20260817_231616_ssc1_u0002",
        "datetime": "2026-08-17T23:16:16Z",
        "view_angle_deg": 28.9,
        "ground_control_ratio": 0.17,
        "native_gsd_m": 0.5,
        "native_crs": "EPSG:32652",
        "has_nir": False,
        "resampled_to": args.match,
        "resampling": "average (0.5m -> 10m, 20x downsample)",
        "files_10m": written,
        "files_native": native_written,
        "note": "SkySat ortho_visual은 RGB+alpha 4밴드(uint8)로 NIR이 없다 — "
                "전략 문서 제약①이 실물로 확인됨. CRS는 이미 EPSG:32652라 "
                "①단계에서 실제 필요한 작업은 재투영이 아니라 해상도 통일이었다.",
    }
    meta_path = out_dir / f"skysat_ingest_{args.date}_{args.tag}.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8", newline="\n")
    print(f"메타데이터: {meta_path}")
    print(f"완료 — 10m {len(written)}개" + (f", 원해상도 {len(native_written)}개" if native_written else ""))


if __name__ == "__main__":
    main()
