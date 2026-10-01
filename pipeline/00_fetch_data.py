"""
옹진 서해 도서 AOI에 대해 Microsoft Planetary Computer에서
Sentinel-2 L2A 장면을 검색하고, AOI만 윈도우 read로 잘라
data/raw/ 에 GeoTIFF로 저장한다. (계정 불필요)

트랙 B의 재료 데이터 준비 단계.
"""
import argparse
import json
from pathlib import Path

import planetary_computer as pc
import rasterio
from pystac_client import Client
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds

AOI_BBOX_WGS84 = (125.87, 37.14, 126.06, 37.25)  # lon_min, lat_min, lon_max, lat_max
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"


def search_scenes(max_cloud=20, limit=20, max_items=20, tile="T52SBG", datetime=None):
    """AOI가 두 UTM 타일(T52SBG/T51SYB)에 걸쳐 있어, CRS 혼동을 피하려고
    기본은 AOI를 더 많이 덮는 T52SBG 한 타일로 고정해서 검색한다."""
    catalog = Client.open(STAC_URL)
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=AOI_BBOX_WGS84,
        datetime=datetime,
        query={
            "eo:cloud_cover": {"lt": max_cloud},
            "s2:mgrs_tile": {"eq": tile[1:]},  # "52SBG"
        },
        sortby=[{"field": "properties.datetime", "direction": "desc"}],
        limit=limit,
        max_items=max_items,
    )
    items = list(search.items())
    items.sort(key=lambda it: it.properties.get("eo:cloud_cover", 100))
    print(f"검색된 장면 수: {len(items)} (tile={tile}, datetime={datetime})")
    for it in items[:5]:
        print(f"  {it.id}  {it.properties['datetime']}  cloud={it.properties.get('eo:cloud_cover')}")
    return items


def save_aoi_clip(item, band, out_path):
    """item의 band(B04/B03/B02/B08 등)에서 AOI만 잘라 GeoTIFF로 저장."""
    href = item.assets[band].href
    signed_href = pc.sign(href)
    with rasterio.open(signed_href) as src:
        bounds_native = transform_bounds("EPSG:4326", src.crs, *AOI_BBOX_WGS84)
        window = from_bounds(*bounds_native, transform=src.transform)
        data = src.read(1, window=window)
        transform = src.window_transform(window)
        profile = src.profile.copy()
        profile.update(
            height=data.shape[0],
            width=data.shape[1],
            transform=transform,
            count=1,
            driver="GTiff",
            compress="deflate",
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(data, 1)
    print(f"저장: {out_path}  shape={data.shape}  crs={src.crs}")
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bands", default="B04", help="쉼표로 구분한 밴드 목록 (예: B04,B03,B02,B08)")
    ap.add_argument("--out", default="data/raw")
    args = ap.parse_args()
    bands = args.bands.split(",")

    # 시간차가 큰 두 시기를 각각 검색해서, 실제 다시기 정합 문제가 되도록 함
    windows = [
        "2026-08-01/2026-09-30",  # 최근 (기준영상 SkySat 촬영과 비슷한 시기)
        "2019-08-01/2019-09-30",  # 7년 전
    ]
    picked = []
    for w in windows:
        cands = search_scenes(datetime=w)
        if cands:
            picked.append(cands[0])  # 구름 가장 적은 장면
    if len(picked) < 2:
        raise SystemExit("두 시기 모두에서 장면을 찾지 못했습니다.")

    meta = []
    for it in picked:
        date = it.properties["datetime"][:10]
        tile = it.properties.get("s2:mgrs_tile", "NA")
        files = {}
        for band in bands:
            out_path = Path(args.out) / f"s2_{date}_{tile}_{band}.tif"
            save_aoi_clip(it, band, out_path)
            files[band] = str(out_path)
        meta.append(
            {
                "id": it.id,
                "datetime": it.properties["datetime"],
                "cloud_cover": it.properties.get("eo:cloud_cover"),
                "files": files,
            }
        )

    meta_path = Path(args.out) / "sentinel2_manifest.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(f"메타데이터: {meta_path}")


if __name__ == "__main__":
    main()
