"""
① 드론 시점 보정 (경사촬영 → 위성과 같은 "위에서 본" 투영으로)

배경 — 왜 필요한가
------------------
SkySat도 사실 28.9° 경사촬영이지만, 회사가 배포하는 ortho_visual은
Planet이 자체 DEM으로 **이미 정사보정**해서 위에서 똑바로 본 지도
형태로 만든 제품이다(전략 문서 1-1 "정사보정 완료"). 반면 드론
원본 사진은 이런 보정이 안 된 "사람이 비스듬히 본" 원근 사진이다.
그래서 위성 ortho영상과 드론 원본 사진을 곧바로 LightGlue/LoFTR에
넣으면, 실제로는 "다른 곳이라서"가 아니라 "같은 곳을 다른 투영으로
찍어서" 매칭이 잘 안 될 수 있다. 이걸 정합 *이전에* 없애는 게 이
스크립트의 목적이다.

두 가지 방법 (難이도·정확도 다름)
--------------------------------
1) **정석 — 다시점 SfM (OpenDroneMap)**: 겹치는 드론 사진 여러 장으로
   실제 3D 지형(DSM)을 복원해서 정사영상을 만든다. 절벽·언덕 같은
   기복변위(회의록 A2)까지 기하학적으로 정확히 보정됨. 드론 사진을
   여러 장 확보하면 이게 정답 — `OpenDroneMap`으로 별도 처리.

2) **이 스크립트 — 단일/소수 프레임 호모그래피 보정**: 드론 사진이
   한두 장뿐이거나, ODM을 돌리기 전에 빠르게 "대략 맞는지" 미리
   보고 싶을 때 쓰는 근사법. 짐벌 피치각·고도(드론 텔레메트리 —
   SRT/EXIF에서 추출, 트랙A 계획과 연결됨)를 안다고 가정하고,
   **땅이 평평하다는 전제 하에** 호모그래피 하나로 원근을 역보정해
   위에서 본 것처럼 편다.

   ⚠️ 한계: 평지·해변처럼 평평한 곳에서만 정확하다. 굴업도의
   개머리언덕·절벽처럼 높이가 있는 지형은 이 방법으로는 기복변위가
   남는다 — 그 부분은 결국 1)번(ODM)이나 DEM 기반 국소보정이
   필요하다는 걸 아래 실험에서 직접 보여준다.

이 스크립트가 하는 실험 (실제 드론 사진이 아직 없어서 합성으로 검증)
--------------------------------------------------------------
1. 위성 정사영상(이미 "위에서 본" 상태)에 사다리꼴(keystone) 원근
   왜곡을 인위적으로 줘서 "드론이 비스듬히 찍은 것처럼" 합성한다.
2. 이 왜곡을 되돌리는 호모그래피(=드론 시점 보정)를 적용한다.
3. "보정 안 한 오블리크 사진 vs 위성" 대 "보정한 사진 vs 위성"의
   정합 성능(매칭 수·인라이어 비율·RMSE)을 비교해 보정이 실제로
   도움되는지 수치로 확인한다.
4. 지형에 높낮이(언덕)를 넣은 버전도 만들어서, 평면 가정 호모그래피가
   그 부분에서는 못 고친다는 것도 같이 보여준다(한계 실증).
"""
import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import rasterio

sys.path.append("pipeline")
sys.path.append("pipeline/ai_matching")
from sift_baseline import register_sift, to_uint8
from loftr_run import register_loftr


def keystone_homography(w, h, top_margin_frac=0.22):
    """평지를 가정한 원근(사다리꼴) 왜곡의 호모그래피.
    top_margin_frac이 클수록 더 비스듬히(더 큰 피치각으로) 찍은 것에 대응.
    반환값 H는 '위성 정사영상(나딜) -> 드론이 찍었을 법한 오블리크 사진' 방향."""
    nadir_pts = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    oblique_pts = np.float32([
        [w * top_margin_frac, 0],
        [w * (1 - top_margin_frac), 0],
        [w, h],
        [0, h],
    ])
    H = cv2.getPerspectiveTransform(nadir_pts, oblique_pts)
    return H


def add_synthetic_hill(img_u8, center, radius_px, max_shift_px, direction=(0, -1)):
    """언덕(기복) 때문에 생기는 국소 기복변위를 흉내: 언덕 영역의 픽셀을
    카메라 반대 방향(여기선 화면 위쪽, 즉 오블리크 촬영에서 카메라 쪽)으로
    높이에 비례해 밀어낸다. 평면 가정 호모그래피로는 이 국소 이동을 못 고친다."""
    h, w = img_u8.shape
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xx - center[0]) ** 2 + (yy - center[1]) ** 2)
    height_profile = np.clip(1 - dist / radius_px, 0, 1) ** 2  # 가운데가 높은 완만한 언덕
    dx = direction[0] * max_shift_px * height_profile
    dy = direction[1] * max_shift_px * height_profile
    map_x = (xx + dx).astype(np.float32)
    map_y = (yy + dy).astype(np.float32)
    return cv2.remap(img_u8, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def run_registration_pair(name, img_a, img_b, gsd_m, hotspot=None, hotspot_radius=None):
    """hotspot(x,y)을 주면 매칭점이 그 안/밖일 때 인라이어 비율이 다른지도 같이 본다.
    (RANSAC은 언덕처럼 전역 모델과 안 맞는 지역의 매칭점을 '이상치'로 자동 제외하므로,
    전체 인라이어 비율·RMSE만 보면 그 지역의 실패가 가려진다 — 이걸 드러내기 위함)"""
    from metrics import reprojection_rmse
    results = {}
    for method_name, fn in [("SIFT", register_sift), ("LoFTR", register_loftr)]:
        H, pa, pb, mask, n, el = fn(img_a, img_b)
        if H is None or mask is None or mask.sum() < 4:
            results[method_name] = {"n_matches": n, "n_inliers": 0, "inlier_ratio": 0.0, "rmse_m": None}
            continue
        rmse = reprojection_rmse(pa, pb, H, mask)
        entry = {
            "n_matches": int(n),
            "n_inliers": int(mask.sum()),
            "inlier_ratio": round(float(mask.sum() / n), 3),
            "rmse_m": round(rmse * gsd_m, 3) if rmse is not None else None,
        }
        if hotspot is not None:
            dist = np.linalg.norm(pa - np.array(hotspot), axis=1)
            in_zone = dist < hotspot_radius
            m = mask.ravel().astype(bool)
            in_zone_inlier_ratio = float(m[in_zone].mean()) if in_zone.sum() > 0 else None
            out_zone_inlier_ratio = float(m[~in_zone].mean()) if (~in_zone).sum() > 0 else None
            entry["hotspot_n_matches"] = int(in_zone.sum())
            entry["hotspot_inlier_ratio"] = round(in_zone_inlier_ratio, 3) if in_zone_inlier_ratio is not None else None
            entry["outside_inlier_ratio"] = round(out_zone_inlier_ratio, 3) if out_zone_inlier_ratio is not None else None
        results[method_name] = entry
    line = f"[{name}] " + " | ".join(
        f"{k}: 매칭{v['n_matches']} 인라이어{v['n_inliers']}({v['inlier_ratio']*100:.0f}%) RMSE {v['rmse_m']}m"
        for k, v in results.items()
    )
    if hotspot is not None:
        line += "\n         언덕구역 인라이어율 vs 언덕밖 인라이어율 → " + " | ".join(
            f"{k}: {v.get('hotspot_inlier_ratio')} vs {v.get('outside_inlier_ratio')} (언덕내 매칭 {v.get('hotspot_n_matches')}개)"
            for k, v in results.items()
        )
    print(line)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="data/raw/s2_2026-09-16_52SBG_B04.tif",
                     help="위성 정사영상(이미 나딜) — '드론' 오블리크 이미지도 이걸로부터 합성")
    ap.add_argument("--gsd", type=float, default=10.0)
    ap.add_argument("--top_margin", type=float, default=0.22, help="원근 왜곡 강도(클수록 더 비스듬함)")
    args = ap.parse_args()

    with rasterio.open(args.ref) as f:
        sat_img = to_uint8(f.read(1))
    h, w = sat_img.shape

    # 1) 평지 가정 오블리크 합성 + 보정
    H = keystone_homography(w, h, args.top_margin)
    drone_oblique_flat = cv2.warpPerspective(sat_img, H, (w, h), borderMode=cv2.BORDER_REPLICATE)
    H_inv = np.linalg.inv(H)
    drone_rectified_flat = cv2.warpPerspective(drone_oblique_flat, H_inv, (w, h), borderMode=cv2.BORDER_REPLICATE)

    print(f"\n=== 실험 A: 평지 가정 (top_margin={args.top_margin}) ===")
    before_flat = run_registration_pair("보정 전 (오블리크 vs 위성)", drone_oblique_flat, sat_img, args.gsd)
    after_flat = run_registration_pair("보정 후 (시점보정 vs 위성)", drone_rectified_flat, sat_img, args.gsd)

    # 2) 언덕(기복변위) 포함 버전 — 평면 호모그래피의 한계 실증
    hill_center = (w * 0.55, h * 0.45)
    hill_radius = min(h, w) * 0.18
    hill_shift_px = 25  # 언덕 높이로 인한 최대 픽셀 변위 (기복변위 크기)

    sat_with_hill = sat_img  # 위성은 이미 정사보정된 "정답" 그대로
    drone_oblique_hill = cv2.warpPerspective(sat_img, H, (w, h), borderMode=cv2.BORDER_REPLICATE)
    drone_oblique_hill = add_synthetic_hill(drone_oblique_hill, hill_center, hill_radius, hill_shift_px)
    drone_rectified_hill = cv2.warpPerspective(drone_oblique_hill, H_inv, (w, h), borderMode=cv2.BORDER_REPLICATE)

    print(f"\n=== 실험 B: 언덕(기복변위, 최대 {hill_shift_px}px) 포함 — 평면 가정의 한계 ===")
    before_hill = run_registration_pair(
        "보정 전 (오블리크+언덕 vs 위성)", drone_oblique_hill, sat_with_hill, args.gsd,
        hotspot=hill_center, hotspot_radius=hill_radius,
    )
    after_hill = run_registration_pair(
        "보정 후 (시점보정만, DEM 없음 vs 위성)", drone_rectified_hill, sat_with_hill, args.gsd,
        hotspot=hill_center, hotspot_radius=hill_radius,
    )

    result = {
        "flat_terrain": {"before": before_flat, "after": after_flat},
        "hill_terrain": {"before": before_hill, "after": after_hill},
        "hill_shift_px_max": hill_shift_px,
        "note": "실제 드론 사진이 없어 위성 정사영상에 합성 원근왜곡을 줘서 검증. "
                "평지에서는 호모그래피 보정만으로 정합이 크게 개선되지만, 언덕(국소 기복변위)이 "
                "있으면 전역 호모그래피로는 그 지역 오차가 남는다 — 실제 절벽·언덕 지형에는 "
                "OpenDroneMap(다시점 SfM)의 DEM 기반 정사보정이 필요하다는 근거.",
    }

    Path("results").mkdir(exist_ok=True)
    Path("results/drone_view_rectify.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    # 그림 저장
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    # 한글 폰트는 OS마다 다르다(Windows 맑은 고딕 / macOS AppleGothic).
    from _compat import apply_korean_font
    apply_korean_font()

    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    axes[0, 0].imshow(sat_img, cmap="gray"); axes[0, 0].set_title("위성 정사영상 (기준)"); axes[0, 0].axis("off")
    axes[0, 1].imshow(drone_oblique_flat, cmap="gray"); axes[0, 1].set_title("합성 드론 오블리크 (평지)"); axes[0, 1].axis("off")
    axes[0, 2].imshow(drone_rectified_flat, cmap="gray"); axes[0, 2].set_title("시점 보정 후 (평지)"); axes[0, 2].axis("off")
    axes[1, 0].imshow(sat_img, cmap="gray"); axes[1, 0].set_title("위성 정사영상 (기준)"); axes[1, 0].axis("off")
    axes[1, 1].imshow(drone_oblique_hill, cmap="gray"); axes[1, 1].set_title("합성 드론 오블리크 (+언덕)"); axes[1, 1].axis("off")
    axes[1, 2].imshow(drone_rectified_hill, cmap="gray"); axes[1, 2].set_title("시점 보정 후 (+언덕, 잔차 남음)"); axes[1, 2].axis("off")
    fig.suptitle("① 드론 시점 보정: 정합 이전에 원근을 위성과 맞추기")
    fig.tight_layout()
    Path("results/figures").mkdir(parents=True, exist_ok=True)
    fig.savefig("results/figures/06_drone_view_rectify.png", dpi=140)
    print("\n그림 저장: results/figures/06_drone_view_rectify.png")
    print("결과 저장: results/drone_view_rectify.json")


if __name__ == "__main__":
    main()
