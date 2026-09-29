"""
실제 드론 영상이 아직 없어서, "구글맵과 실제 영상의 미묘한 어긋남"을
재현하기 위한 합성 벤치마크를 만든다.

방법: 실제 Sentinel-2 영상(2026-09-16)에 우리가 정확히 아는 이동+회전+
살짝의 스케일(H_true)을 인위적으로 준 뒤, 각 정합 기법이 이 H_true를
얼마나 정확히 되찾아내는지 측정한다. 정답을 알고 있으므로 "몇 m 틀렸는지"를
추측이 아니라 정확히 계산할 수 있다.

기본 왜곡 크기(대략 위성 지오로케이션 오차의 전형적 범위):
  이동 12px, -7px (10m GSD 기준 120m, -70m)
  회전 0.8도
  스케일 1.003
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import rasterio


def build_true_homography(shape, tx=12.0, ty=-7.0, rot_deg=0.8, scale=1.003):
    h, w = shape
    cx, cy = w / 2, h / 2
    theta = np.deg2rad(rot_deg)
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    # 이미지 중심 기준 회전+스케일 후 이동
    R = np.array(
        [
            [scale * cos_t, -scale * sin_t, cx - scale * cos_t * cx + scale * sin_t * cy + tx],
            [scale * sin_t, scale * cos_t, cy - scale * sin_t * cx - scale * cos_t * cy + ty],
            [0, 0, 1],
        ]
    )
    return R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/raw/s2_2026-09-16_52SBG_B04.tif")
    ap.add_argument("--out_dir", default="data/interim")
    ap.add_argument("--tx", type=float, default=12.0)
    ap.add_argument("--ty", type=float, default=-7.0)
    ap.add_argument("--rot_deg", type=float, default=0.8)
    ap.add_argument("--scale", type=float, default=1.003)
    args = ap.parse_args()

    with rasterio.open(args.src) as src:
        img = src.read(1)
        gsd = src.transform.a

    H_true = build_true_homography(img.shape, args.tx, args.ty, args.rot_deg, args.scale)
    warped = cv2.warpPerspective(img, H_true, (img.shape[1], img.shape[0]), flags=cv2.INTER_LINEAR)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "synthetic_src.npy", img)
    np.save(out_dir / "synthetic_warped.npy", warped)
    np.save(out_dir / "H_true.npy", H_true)

    meta = {
        "src": args.src,
        "gsd_m": gsd,
        "tx_px": args.tx,
        "ty_px": args.ty,
        "rot_deg": args.rot_deg,
        "scale": args.scale,
        "tx_m": round(args.tx * gsd, 2),
        "ty_m": round(args.ty * gsd, 2),
        "note": "warped = H_true(src). 정합 기법이 warped->src 변환을 추정하면 H_true의 역행렬과 비교한다.",
    }
    (out_dir / "synthetic_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print("합성 벤치마크 생성 완료:", meta)


if __name__ == "__main__":
    main()
