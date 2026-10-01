"""
⑦-2 딥러닝 변화탐지 — 사전학습 AdaptFormer (LEVIR-CD 학습 가중치)

⑦단계 고전 기법이 F1 0.136에서 막힌 이유는 계절·조명 변화를 "변화"로
오인하기 때문이다(`results/figures/11_levir_examples.png` 참고). 그건
밝기·색만 보고는 원리적으로 못 푸는 문제라, **무엇이 의미 있는 변화인지
학습한 모델**이 필요하다.

여기서는 HuggingFace에 공개된 `deepang/adaptformer-LEVIR-CD`
(12.5M 파라미터, LEVIR-CD 학습 완료)를 **추가 학습 없이** 붙여서,
같은 데이터·같은 지표로 고전 기법과 나란히 비교한다.

타일 처리를 하는 이유
--------------------
이 모델의 전처리기는 입력을 **256x256으로 축소**한다. LEVIR-CD+ 영상은
1024x1024라 그대로 넣으면 4배 축소되어 작은 건물이 뭉개진다. 그래서
1024를 256짜리 타일 16장으로 잘라 각각 추론하고 다시 이어붙인다
(`--mode tile`). 비교용으로 통째 축소하는 경로도 남겨뒀다(`--mode resize`).

    python pipeline/08_change_detection_dl.py --limit 100
    python pipeline/08_change_detection_dl.py --limit 100 --shift-sweep 0,1,2,4,8
"""
import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

_HERE = Path(__file__).resolve().parent
sys.path.append(str(_HERE))
from _compat import enable_utf8_stdout, pick_torch_device

enable_utf8_stdout()

# 07은 숫자로 시작해서 일반 import가 안 된다 — 파일 경로로 직접 읽는다.
_spec = importlib.util.spec_from_file_location("cd07", _HERE / "07_change_detection.py")
cd07 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cd07)

REPO = "deepang/adaptformer-LEVIR-CD"
# 전처리기 설정에서 확인한 ImageNet 표준 정규화 (preprocessor_config.json)
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def load_model(device):
    from transformers import AutoModel
    model = AutoModel.from_pretrained(REPO, trust_remote_code=True)
    model.eval().to(device)
    n = sum(p.numel() for p in model.parameters())
    print(f"모델   : {REPO}  ({n / 1e6:.1f}M 파라미터)  장치={device}")
    return model


def normalize_batch(imgs):
    """uint8 RGB 타일 목록 -> (N,3,H,W) 정규화 텐서."""
    x = np.stack(imgs).astype(np.float32) / 255.0
    x = (x - MEAN) / STD
    return torch.from_numpy(x).permute(0, 3, 1, 2).contiguous()


def tiles_of(img, ts):
    """이미지를 ts x ts 타일로 자른다 (좌상단 좌표와 함께)."""
    h, w = img.shape[:2]
    for y in range(0, h, ts):
        for x in range(0, w, ts):
            yield y, x, img[y:y + ts, x:x + ts]


@torch.no_grad()
def predict_tile(model, a, b, device, tile=256, batch=16):
    """1024 영상을 타일로 잘라 추론하고 다시 이어붙여 변화 확률맵을 만든다."""
    h, w = a.shape[:2]
    prob = np.zeros((h, w), dtype=np.float32)
    coords, ta, tb = [], [], []

    def flush():
        if not coords:
            return
        xa = normalize_batch(ta).to(device)
        xb = normalize_batch(tb).to(device)
        out = model(pixel_valuesA=xa, pixel_valuesB=xb)
        logits = out.logits if hasattr(out, "logits") else out[0]
        # 모델이 타일보다 작은 해상도로 뱉으면 원래 타일 크기로 되돌린다
        if logits.shape[-2:] != (ta[0].shape[0], ta[0].shape[1]):
            logits = F.interpolate(logits, size=ta[0].shape[:2],
                                   mode="bilinear", align_corners=False)
        p = torch.softmax(logits, dim=1)[:, 1].cpu().numpy()
        for (y, x), pi in zip(coords, p):
            prob[y:y + pi.shape[0], x:x + pi.shape[1]] = pi
        coords.clear(); ta.clear(); tb.clear()

    for (y, x, pa), (_, _, pb) in zip(tiles_of(a, tile), tiles_of(b, tile)):
        coords.append((y, x)); ta.append(pa); tb.append(pb)
        if len(coords) >= batch:
            flush()
    flush()
    return prob


@torch.no_grad()
def predict_resize(model, a, b, device, size=256):
    """비교용: 영상 전체를 한 번에 축소해서 추론 (모델 기본 전처리와 동일)."""
    import cv2
    h, w = a.shape[:2]
    ra = cv2.resize(a, (size, size), interpolation=cv2.INTER_AREA)
    rb = cv2.resize(b, (size, size), interpolation=cv2.INTER_AREA)
    xa = normalize_batch([ra]).to(device)
    xb = normalize_batch([rb]).to(device)
    out = model(pixel_valuesA=xa, pixel_valuesB=xb)
    logits = out.logits if hasattr(out, "logits") else out[0]
    logits = F.interpolate(logits, size=(h, w), mode="bilinear", align_corners=False)
    return torch.softmax(logits, dim=1)[0, 1].cpu().numpy()


def evaluate(model, device, limit, split, shift, mode, tile, thresh, min_size):
    from skimage.morphology import remove_small_objects
    acc = cd07.Accumulator()
    t0, n = time.time(), 0
    for a, b, gt in cd07.load_pairs(limit, split):
        b_used = cd07.shift_image(b, shift)
        if mode == "tile":
            prob = predict_tile(model, a, b_used, device, tile=tile)
        else:
            prob = predict_resize(model, a, b_used, device, size=tile)
        pred = prob > thresh
        if min_size > 0 and pred.any():
            pred = remove_small_objects(pred, min_size=min_size)
        acc.add(pred, gt)
        n += 1
        if n % 25 == 0:
            print(f"    {n}장 처리...", flush=True)
    return acc.result(), n, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--split", default="test")
    ap.add_argument("--mode", default="tile", choices=["tile", "resize"])
    ap.add_argument("--tile", type=int, default=256)
    ap.add_argument("--thresh", type=float, default=0.5)
    ap.add_argument("--min-size", type=int, default=0,
                    help="이보다 작은 덩어리 제거 (딥러닝은 보통 0으로 충분)")
    ap.add_argument("--shift", type=int, default=0)
    ap.add_argument("--shift-sweep", default=None)
    ap.add_argument("--out", default="results/change_detection")
    args = ap.parse_args()

    device = pick_torch_device()
    model = load_model(device)
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    print(f"데이터 : LEVIR-CD+ {args.split} (최대 {args.limit}장)")
    print(f"방식   : {args.mode} (타일 {args.tile}), 임계값 {args.thresh}\n")

    if args.shift_sweep:
        sweep = {}
        for sh in [int(s) for s in args.shift_sweep.split(",")]:
            print(f"=== 정합 오차 {sh}px ===")
            r, n, el = evaluate(model, device, args.limit, args.split, sh,
                                args.mode, args.tile, args.thresh, args.min_size)
            print(f"  F1={r['f1']:.4f}  IoU={r['iou']:.4f}  "
                  f"정밀도={r['precision']:.4f}  재현율={r['recall']:.4f}  ({el:.0f}s)\n")
            sweep[str(sh)] = r
        payload = {"model": REPO, "mode": args.mode, "n": args.limit,
                   "shift_sweep": sweep}
        path = out_dir / "levir_dl_shift_sweep.json"
    else:
        r, n, el = evaluate(model, device, args.limit, args.split, args.shift,
                            args.mode, args.tile, args.thresh, args.min_size)
        print(f"{'지표':<12}{'값':>10}")
        print("-" * 24)
        for k in ("f1", "iou", "precision", "recall", "pred_change_pct", "gt_change_pct"):
            print(f"{k:<12}{r[k]:>10.4f}")
        print(f"\n({n}장, {el:.1f}s, 장당 {el / max(n,1):.2f}s)")
        payload = {"model": REPO, "mode": args.mode, "n": n, "shift_px": args.shift,
                   "thresh": args.thresh, "results": r}
        path = out_dir / f"levir_dl_{args.mode}.json"

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8", newline="\n")
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
