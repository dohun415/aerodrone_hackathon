"""
고전 기법 베이스라인: SIFT + BFMatcher(ratio test) + RANSAC 호모그래피.
노션 조사에 이미 있던 "1) 고전" 방법을 그대로 구현.
"""
import time

import cv2
import numpy as np


def to_uint8(img):
    img = img.astype(np.float32)
    lo, hi = np.percentile(img, 1), np.percentile(img, 99)
    img = np.clip((img - lo) / (hi - lo + 1e-6), 0, 1)
    return (img * 255).astype(np.uint8)


def register_sift(img_src, img_dst, ratio=0.75, ransac_thresh=3.0):
    """img_src를 img_dst에 맞추는 호모그래피 H를 추정.
    반환: H, pts_src(인라이어 전 전체), pts_dst, mask(인라이어), n_matches, elapsed_s
    """
    t0 = time.time()
    a, b = to_uint8(img_src), to_uint8(img_dst)

    sift = cv2.SIFT_create()
    kp1, des1 = sift.detectAndCompute(a, None)
    kp2, des2 = sift.detectAndCompute(b, None)

    if des1 is None or des2 is None or len(des1) < 4 or len(des2) < 4:
        return None, None, None, None, 0, time.time() - t0

    bf = cv2.BFMatcher()
    knn = bf.knnMatch(des1, des2, k=2)
    good = [m for m, n in knn if m.distance < ratio * n.distance]

    if len(good) < 4:
        return None, None, None, None, len(good), time.time() - t0

    pts_src = np.float32([kp1[m.queryIdx].pt for m in good])
    pts_dst = np.float32([kp2[m.trainIdx].pt for m in good])

    H, mask = cv2.findHomography(pts_src, pts_dst, cv2.USAC_MAGSAC, ransac_thresh)
    elapsed = time.time() - t0
    return H, pts_src, pts_dst, mask, len(good), elapsed


if __name__ == "__main__":
    import argparse
    import json
    import sys
    from pathlib import Path

    import rasterio

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from metrics import reprojection_rmse, summarize_matches

    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    ap.add_argument("--dst")
    ap.add_argument("--gsd", type=float, default=10.0)
    args = ap.parse_args()

    with rasterio.open(args.src) as s, rasterio.open(args.dst) as d:
        img_src, img_dst = s.read(1), d.read(1)

    H, pts_src, pts_dst, mask, n_matches, elapsed = register_sift(img_src, img_dst)
    n_inliers = int(mask.sum()) if mask is not None else 0
    rmse = reprojection_rmse(pts_src, pts_dst, H, mask) if H is not None else None
    result = summarize_matches(n_matches, n_inliers, rmse, args.gsd, elapsed, "SIFT+RANSAC")
    print(json.dumps(result, ensure_ascii=False, indent=2))
