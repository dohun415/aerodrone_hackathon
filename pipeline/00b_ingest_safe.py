"""
00b. Copernicus SAFE 원본 제품 -> AOI GeoTIFF (00_fetch_data.py의 오프라인 버전)

왜 따로 필요한가
----------------
`00_fetch_data.py`는 Microsoft Planetary Computer STAC API로 밴드를
*원격에서* 열어 AOI만 윈도우 read 한다. 반면 Copernicus Browser에서
직접 받은 것은 **SAFE 원본 제품**이라 구조가 다르다:

    S2B_MSIL2A_..._T51SYB_....SAFE/
      GRANULE/L2A_T51SYB_.../IMG_DATA/R10m/
        T51SYB_..._B02_10m.jp2   <- 타일 전체(10980x10980) JP2
        T51SYB_..._B03_10m.jp2
        ...

이 스크립트는 그 JP2들을 찾아 `save_aoi_clip()`과 **같은 방식**
(rasterio.warp.transform_bounds -> windows.from_bounds -> 윈도우 read)
으로 AOI만 잘라 GeoTIFF로 저장한다.

좌표계에 대한 중요한 차이 ⚠️
---------------------------
`save_aoi_clip()`은 재투영을 하지 않는다 — 소스 CRS 그대로 잘라 쓴다.
기존 데이터는 **T52SBG 타일(EPSG:32652)** 이라 그래도 문제가 없었다.
그런데 이 SAFE는 **T51SYB 타일(EPSG:32651, UTM 51N)** 이다. 굴업도
AOI가 두 UTM 존 경계에 걸쳐 있어서 생기는 일이고, 00_fetch_data.py가
"CRS 혼동을 피하려고 T52SBG 한 타일로 고정"한다고 적어둔 바로 그
상황이다.

그래서 잘라낸 뒤 EPSG:32652로 **재투영하는 단계를 추가**했다
(`--target-crs`). `--match` 로 기존 GeoTIFF를 주면 그 격자(transform,
크기)에 정확히 맞춰서, 02·05단계처럼 두 영상의 배열 크기가 같아야
하는 단계에 바로 넣을 수 있다. 이게 회의록의 "① 좌표·해상도 통일"에
해당하는 작업이다.

재투영에는 리샘플링이 들어가므로(기본 bilinear) 원본 화소값이 그대로
보존되지는 않는다 — 정합 실험 결과를 해석할 때 감안해야 한다.
`--target-crs none` 을 주면 재투영 없이 네이티브 CRS로만 저장한다.

사용 예
-------
    python pipeline/00b_ingest_safe.py \
        --safe "data/raw/S2B_MSIL2A_..._T51SYB_....SAFE" \
        --bands B02,B03,B04,B08 \
        --match data/raw/s2_2026-09-16_52SBG_B04.tif
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject, transform_bounds
from rasterio.windows import Window, from_bounds

sys.path.append(str(Path(__file__).resolve().parent))
from _compat import ensure_ascii_proj_data

# 한글 경로에서 PROJ가 proj.db를 못 찾는 문제 (README_WINDOWS.md 3번)
ensure_ascii_proj_data()

# 00_fetch_data.py 와 같은 AOI (굴업도 인근)
AOI_BBOX_WGS84 = (125.868, 37.139, 126.060, 37.249)


def find_band_files(safe_dir: Path, bands, resolution="R10m"):
    """SAFE 안의 GRANULE/*/IMG_DATA/<resolution>/ 에서 밴드 JP2를 찾는다."""
    img_dirs = list(safe_dir.glob(f"GRANULE/*/IMG_DATA/{resolution}"))
    if not img_dirs:
        raise SystemExit(
            f"{safe_dir} 안에서 GRANULE/*/IMG_DATA/{resolution} 를 찾지 못했습니다.\n"
            f"SAFE 폴더 구조가 맞는지 확인하세요."
        )
    img_dir = img_dirs[0]

    found = {}
    for band in bands:
        # 예: T51SYB_20260812T022529_B04_10m.jp2
        matches = sorted(img_dir.glob(f"*_{band}_*.jp2"))
        if not matches:
            print(f"  [경고] {band}: {img_dir.name} 에서 찾지 못함 — 건너뜀")
            continue
        found[band] = matches[0]
    if not found:
        raise SystemExit(f"요청한 밴드({','.join(bands)})를 하나도 찾지 못했습니다.")
    return found, img_dir


def parse_safe_name(safe_dir: Path):
    """SAFE 폴더 이름에서 촬영일과 타일 ID를 뽑는다.
    S2B_MSIL2A_20260812T022529_N0512_R046_T51SYB_20260812T044438.SAFE
                 ^^^^^^^^ 날짜                    ^^^^^^ 타일
    """
    name = safe_dir.name
    m_date = re.search(r"_(\d{8})T\d{6}_", name)
    m_tile = re.search(r"_T(\d{2}[A-Z]{3})_", name)
    if not (m_date and m_tile):
        raise SystemExit(f"SAFE 폴더 이름에서 날짜/타일을 못 읽었습니다: {name}")
    d = m_date.group(1)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}", m_tile.group(1)


def clip_aoi(src_path: Path, aoi_wgs84, margin_px=0):
    """00_fetch_data.py의 save_aoi_clip()과 같은 방식으로 AOI만 윈도우 read."""
    with rasterio.open(src_path) as src:
        bounds_native = transform_bounds("EPSG:4326", src.crs, *aoi_wgs84)
        window = from_bounds(*bounds_native, transform=src.transform)
        # AOI가 타일 밖으로 나가면 read는 잘린 배열을, window_transform은
        # 요청 원점을 줘서 좌표가 어긋난다. 반드시 교집합을 먼저 취한다.
        window = window.intersection(
            Window(0, 0, src.width, src.height)).round_offsets().round_lengths()
        data = src.read(1, window=window)
        transform = src.window_transform(window)
        profile = src.profile.copy()
        profile.update(
            height=data.shape[0], width=data.shape[1], transform=transform,
            count=1, driver="GTiff", compress="deflate",
        )
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
        profile.pop("tiled", None)
        return data, profile, src.crs


def reproject_to(data, profile, src_crs, dst_crs, match_profile=None,
                 resampling=Resampling.bilinear):
    """잘라낸 배열을 목표 CRS로 재투영.

    match_profile 이 주어지면 그 격자(크기·transform)에 정확히 맞춘다 —
    02·05단계처럼 두 배열의 shape이 같아야 하는 단계에 바로 쓸 수 있다.
    """
    if match_profile is not None:
        dst_transform = match_profile["transform"]
        dst_w, dst_h = match_profile["width"], match_profile["height"]
        dst_crs = match_profile["crs"]
    else:
        dst_transform, dst_w, dst_h = calculate_default_transform(
            src_crs, dst_crs, profile["width"], profile["height"],
            *rasterio.transform.array_bounds(profile["height"], profile["width"],
                                             profile["transform"]),
        )

    dst = np.zeros((dst_h, dst_w), dtype=data.dtype)
    reproject(
        source=data, destination=dst,
        src_transform=profile["transform"], src_crs=src_crs,
        dst_transform=dst_transform, dst_crs=dst_crs,
        resampling=resampling,
    )
    out = profile.copy()
    out.update(height=dst_h, width=dst_w, transform=dst_transform, crs=dst_crs)
    return dst, out


def main():
    ap = argparse.ArgumentParser(description="Copernicus SAFE -> AOI GeoTIFF")
    ap.add_argument("--safe", required=True, help="SAFE 폴더 경로")
    ap.add_argument("--bands", default="B02,B03,B04,B08")
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--resolution", default="R10m")
    ap.add_argument("--target-crs", default="EPSG:32652",
                    help="재투영할 좌표계. 'none'이면 네이티브 CRS 유지")
    ap.add_argument("--match", default=None,
                    help="이 GeoTIFF의 격자(크기·transform)에 정확히 맞춤")
    args = ap.parse_args()

    safe_dir = Path(args.safe)
    if not safe_dir.exists():
        raise SystemExit(f"SAFE 폴더가 없습니다: {safe_dir}")

    bands = [b.strip() for b in args.bands.split(",") if b.strip()]
    date, tile = parse_safe_name(safe_dir)
    print(f"SAFE  : {safe_dir.name}")
    print(f"촬영일: {date}   타일: {tile}")

    band_files, img_dir = find_band_files(safe_dir, bands, args.resolution)
    print(f"밴드  : {', '.join(band_files)}  ({args.resolution})")
    print(f"AOI   : {AOI_BBOX_WGS84}  (굴업도)\n")

    match_profile = None
    if args.match:
        with rasterio.open(args.match) as m:
            match_profile = {"transform": m.transform, "width": m.width,
                             "height": m.height, "crs": m.crs}
        print(f"격자 맞춤 대상: {args.match}")
        print(f"  -> {match_profile['crs']}  {match_profile['height']}x{match_profile['width']}\n")

    target_crs = None if args.target_crs.lower() == "none" else args.target_crs
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = {}
    for i, (band, src_path) in enumerate(band_files.items(), 1):
        print(f"[{i}/{len(band_files)}] {band}  <- {src_path.name}")
        data, profile, src_crs = clip_aoi(src_path, AOI_BBOX_WGS84)
        print(f"        AOI 잘라냄: {data.shape}  CRS={src_crs}")

        if match_profile is not None or (target_crs and str(src_crs) != target_crs):
            data, profile = reproject_to(data, profile, src_crs, target_crs, match_profile)
            print(f"        재투영    : {data.shape}  CRS={profile['crs']}")

        out_path = out_dir / f"s2_{date}_{tile}_{band}.tif"
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(data, 1)
        size_mb = out_path.stat().st_size / 1e6
        print(f"        저장      : {out_path}  ({size_mb:.1f} MB)\n")
        written[band] = str(out_path)

    meta = {
        "source_safe": safe_dir.name,
        "datetime": date,
        "tile": tile,
        "native_crs": str(src_crs),
        "output_crs": str(profile["crs"]),
        "reprojected": str(src_crs) != str(profile["crs"]),
        "matched_grid": args.match,
        "aoi_wgs84": AOI_BBOX_WGS84,
        "files": written,
        "note": "Copernicus Browser에서 받은 SAFE 원본에서 AOI만 잘라낸 것. "
                "T51SYB는 EPSG:32651(UTM 51N)이라 기존 T52SBG(32652) 데이터와 "
                "좌표계가 달라, 잘라낸 뒤 32652로 재투영(bilinear)했다.",
    }
    meta_path = out_dir / f"safe_ingest_{date}_{tile}.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8", newline="\n")
    print(f"메타데이터: {meta_path}")
    print(f"완료 — {len(written)}개 밴드")


if __name__ == "__main__":
    main()
