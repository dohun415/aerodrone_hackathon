"""
모든 정합 실험이 공통으로 쓰는 지표 계산 함수.
- 매칭 개수 / 인라이어 비율
- 픽셀 RMSE, 미터 RMSE (GSD를 곱해서 환산)
- 합성 벤치마크에서는 "진짜 정답 변환"과 추정 변환의 차이도 계산
"""
import numpy as np
import cv2


def reprojection_rmse(pts_src, pts_dst, H, mask=None):
    """H로 pts_src를 옮겼을 때 pts_dst와 얼마나 떨어지는지 픽셀 RMSE."""
    if mask is not None:
        pts_src = pts_src[mask.ravel().astype(bool)]
        pts_dst = pts_dst[mask.ravel().astype(bool)]
    if len(pts_src) == 0:
        return None
    pts_src_h = cv2.perspectiveTransform(pts_src.reshape(-1, 1, 2), H).reshape(-1, 2)
    err = np.linalg.norm(pts_src_h - pts_dst, axis=1)
    return float(np.sqrt(np.mean(err**2)))


def summarize_matches(n_matches, n_inliers, rmse_px, gsd_m, elapsed_s, method):
    return {
        "method": method,
        "n_matches": int(n_matches),
        "n_inliers": int(n_inliers),
        "inlier_ratio": round(n_inliers / n_matches, 4) if n_matches else None,
        "rmse_px": round(rmse_px, 3) if rmse_px is not None else None,
        "rmse_m": round(rmse_px * gsd_m, 3) if rmse_px is not None else None,
        "elapsed_s": round(elapsed_s, 3),
    }


def known_transform_error(H_est, H_true, corners, gsd_m):
    """합성 벤치마크 전용: 이미지 네 모서리를 H_est와 H_true로 각각 옮겨서
    두 결과가 얼마나 다른지(=복원 오차)를 픽셀/미터로 계산."""
    c = corners.reshape(-1, 1, 2).astype(np.float32)
    est = cv2.perspectiveTransform(c, H_est).reshape(-1, 2)
    true = cv2.perspectiveTransform(c, H_true).reshape(-1, 2)
    err_px = np.linalg.norm(est - true, axis=1)
    return {
        "corner_err_px_mean": round(float(err_px.mean()), 3),
        "corner_err_px_max": round(float(err_px.max()), 3),
        "corner_err_m_mean": round(float(err_px.mean() * gsd_m), 3),
        "corner_err_m_max": round(float(err_px.max() * gsd_m), 3),
    }
