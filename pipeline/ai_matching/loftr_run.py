"""
kornia의 LoFTR(Detector-free dense matching)로 두 영상을 정합.
노션 조사의 "2) AI: LightGlue/LoFTR" 항목을 실제로 실행.
"""
import time

import cv2
import numpy as np
import torch
import kornia.feature as KF

import sys
from pathlib import Path

# _compat는 pipeline/ 에 있다 (이 파일은 pipeline/ai_matching/).
sys.path.append(str(Path(__file__).resolve().parents[1]))
from _compat import ensure_ssl_certs, pick_torch_device

# LoFTR 사전학습 가중치를 받는 서버의 CA가 Windows 기본 인증서
# 저장소에 없어서 첫 실행이 SSL 오류로 죽는다 — certifi 번들을 쓰게 한다.
ensure_ssl_certs()

# 원래는 "mps"(Apple GPU) 고정이었다 — Windows의 NVIDIA GPU를 쓰려면
# CUDA를 먼저 확인해야 한다. CUDA > MPS > CPU 순으로 자동 선택.
_DEVICE = pick_torch_device()
_MATCHER = None


def _get_matcher():
    global _MATCHER
    if _MATCHER is None:
        _MATCHER = KF.LoFTR(pretrained="outdoor").to(_DEVICE).eval()
    return _MATCHER


def to_uint8(img):
    img = img.astype(np.float32)
    lo, hi = np.percentile(img, 1), np.percentile(img, 99)
    img = np.clip((img - lo) / (hi - lo + 1e-6), 0, 1)
    return (img * 255).astype(np.uint8)


def _to_tensor(img_u8, max_side=800):
    h, w = img_u8.shape
    scale = min(1.0, max_side / max(h, w))
    new_hw = (int(w * scale), int(h * scale))
    # LoFTR는 8의 배수 크기를 선호
    new_w = (new_hw[0] // 8) * 8
    new_h = (new_hw[1] // 8) * 8
    resized = cv2.resize(img_u8, (new_w, new_h))
    t = torch.from_numpy(resized).float()[None, None] / 255.0
    return t.to(_DEVICE), (w / new_w, h / new_h)  # 원본 좌표로 되돌릴 배율


def register_loftr(img_src, img_dst, conf_thresh=0.5, max_side=800, ransac_thresh=3.0):
    t0 = time.time()
    a, b = to_uint8(img_src), to_uint8(img_dst)
    ta, scale_a = _to_tensor(a, max_side)
    tb, scale_b = _to_tensor(b, max_side)

    matcher = _get_matcher()
    with torch.no_grad():
        out = matcher({"image0": ta, "image1": tb})

    mkpts0 = out["keypoints0"].cpu().numpy()
    mkpts1 = out["keypoints1"].cpu().numpy()
    conf = out["confidence"].cpu().numpy()

    keep = conf > conf_thresh
    mkpts0, mkpts1 = mkpts0[keep], mkpts1[keep]

    # 리사이즈했던 좌표를 원본 해상도로 복원
    mkpts0 = mkpts0 * np.array(scale_a)
    mkpts1 = mkpts1 * np.array(scale_b)

    if len(mkpts0) < 4:
        return None, mkpts0, mkpts1, None, len(mkpts0), time.time() - t0

    H, mask = cv2.findHomography(mkpts0, mkpts1, cv2.USAC_MAGSAC, ransac_thresh)
    elapsed = time.time() - t0
    return H, mkpts0, mkpts1, mask, len(mkpts0), elapsed


if __name__ == "__main__":
    import argparse
    import json

    import rasterio

    from metrics import reprojection_rmse, summarize_matches

    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    ap.add_argument("--dst")
    ap.add_argument("--gsd", type=float, default=10.0)
    args = ap.parse_args()

    with rasterio.open(args.src) as s, rasterio.open(args.dst) as d:
        img_src, img_dst = s.read(1), d.read(1)

    H, pts_src, pts_dst, mask, n_matches, elapsed = register_loftr(img_src, img_dst)
    n_inliers = int(mask.sum()) if mask is not None else 0
    rmse = reprojection_rmse(pts_src, pts_dst, H, mask) if H is not None else None
    result = summarize_matches(n_matches, n_inliers, rmse, args.gsd, elapsed, "LoFTR(kornia)")
    print(json.dumps(result, ensure_ascii=False, indent=2))
