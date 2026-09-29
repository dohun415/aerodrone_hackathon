"""
합성 벤치마크 실행: 정답 변환(H_true)을 아는 상태에서
SIFT와 LoFTR이 그 변환을 얼마나 정확히 복원하는지 측정.

"구글맵과 실제 영상의 미묘한 어긋남"을 실제 드론 데이터 없이도
정량적으로 재현/검증하기 위한 실험.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).resolve().parent))
from baselines.sift_baseline import register_sift
from learned.loftr_run import register_loftr
from metrics import reprojection_rmse, summarize_matches, known_transform_error


def main():
    interim = Path("data/interim")
    src = np.load(interim / "synthetic_src.npy")
    warped = np.load(interim / "synthetic_warped.npy")
    H_true = np.load(interim / "H_true.npy")
    meta = json.loads((interim / "synthetic_meta.json").read_text())
    gsd = meta["gsd_m"]

    h, w = src.shape
    corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)

    print(f"정답: 이동=({meta['tx_px']}px,{meta['ty_px']}px) = ({meta['tx_m']}m,{meta['ty_m']}m), "
          f"회전={meta['rot_deg']}도, 스케일={meta['scale']}")
    print("과제: warped -> src로 정합해서 H_true의 역행렬을 복원하는지 측정\n")

    results = []
    for name, fn in [("SIFT+RANSAC", register_sift), ("LoFTR(kornia)", register_loftr)]:
        H_est, pts_a, pts_b, mask, n_matches, elapsed = fn(warped, src)
        if H_est is None:
            print(f"[{name}] 매칭 실패 (매칭 수 부족)")
            continue
        n_inliers = int(mask.sum())
        rmse = reprojection_rmse(pts_a, pts_b, H_est, mask)
        base = summarize_matches(n_matches, n_inliers, rmse, gsd, elapsed, name)

        # H_est(warped->src) 는 H_true의 역변환과 같아야 함
        H_true_inv = np.linalg.inv(H_true)
        recon = known_transform_error(H_est, H_true_inv, corners, gsd)
        base.update(recon)
        results.append(base)
        print(f"[{name}] 매칭 {n_matches} / 인라이어 {n_inliers} "
              f"({base['inlier_ratio']*100:.0f}%) | 복원오차 평균 {recon['corner_err_m_mean']}m "
              f"(최대 {recon['corner_err_m_max']}m) | {elapsed:.2f}s")

    out = Path("results")
    out.mkdir(exist_ok=True)
    (out / "synthetic_benchmark.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n저장: results/synthetic_benchmark.json")


if __name__ == "__main__":
    main()
