"""
⑦ 픽셀 단위 변화탐지 — 정답 마스크로 정량 평가

과제 4 요구사항 3번("정합된 시계열 자료를 활용한 픽셀·객체 단위 변화탐지
알고리즘 구현")의 픽셀 단위 부분.

지금까지(①~⑥)는 전부 "두 영상을 정확히 포개는" 작업이었다. 여기서부터는
포개진 영상에서 **실제로 뭐가 변했는지** 찾는다.

왜 LEVIR-CD+로 하는가
---------------------
정답 마스크(사람이 라벨링한 변화 영역)가 있어서 **F1·IoU로 정량 평가**가
된다. 지금까지 정합 단계에서 합성 벤치마크로 "정답을 아는 상태"를 만들어
측정해 온 것과 같은 방식이다. 해상도 0.5m는 회사 SkySat과 거의 같다.

구현한 방법 (전부 학습 불필요 — 고전 기법 베이스라인)
--------------------------------------------------
  abs_diff   : 흑백 변환 후 밝기 차 절댓값 + Otsu 자동 임계값
  norm_diff  : 영상별로 밝기를 먼저 정규화한 뒤 차분
               (촬영 시기·센서가 다르면 전체 밝기가 통째로 달라지는데,
                그걸 "변화"로 오인하는 걸 막는다)
  cva        : Change Vector Analysis — RGB 3채널을 벡터로 보고
               두 시기 벡터의 거리를 변화량으로 쓴다 (색 변화까지 잡음)

이건 **딥러닝 없이 어디까지 되는지**를 먼저 재두는 것이다. 이 숫자가
있어야 나중에 딥러닝을 붙였을 때 "얼마나 좋아졌는지"를 말할 수 있다.

핵심 실험: 정합이 틀어지면 변화탐지가 어떻게 무너지는가
-----------------------------------------------------
`--shift N` 을 주면 두 번째 영상을 일부러 N픽셀 밀어서 평가한다.
LEVIR-CD+는 이미 정합된 데이터라, 밀기 전후를 비교하면 **①~⑥ 정합
파이프라인이 왜 필요한지**를 정답 기반 F1으로 보여줄 수 있다.

    python pipeline/07_change_detection.py --limit 100
    python pipeline/07_change_detection.py --limit 100 --shift-sweep 0,2,4,6,8
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).resolve().parent))
from _compat import enable_utf8_stdout

enable_utf8_stdout()

import cv2
from skimage.filters import threshold_otsu
from skimage.morphology import remove_small_objects


# ----------------------------------------------------------------- 전처리
def to_gray(img):
    return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)


def normalize(img):
    """영상별 1~99 퍼센타일 스트레치.

    두 시기 영상은 태양고도·대기·센서 이득이 달라 전체 밝기가 통째로
    다른 경우가 많다. 그대로 빼면 화면 전체가 '변화'로 나오므로,
    각 영상을 같은 기준으로 펴준 뒤 비교한다."""
    img = img.astype(np.float32)
    lo, hi = np.percentile(img, 1), np.percentile(img, 99)
    return np.clip((img - lo) / (hi - lo + 1e-6), 0, 1)


# ------------------------------------------------------------- 변화 점수
def score_abs_diff(a, b):
    """가장 단순한 방법: 흑백으로 바꿔 밝기 차 절댓값."""
    return np.abs(to_gray(a) - to_gray(b))


def score_norm_diff(a, b):
    """영상별 정규화 후 차분 — 전역 밝기 차이에 강하다."""
    return np.abs(normalize(to_gray(a)) - normalize(to_gray(b)))


def score_cva(a, b):
    """Change Vector Analysis: RGB를 벡터로 보고 두 시기 벡터 사이 거리.
    흑백 차분과 달리 '밝기는 같은데 색이 바뀐' 변화도 잡는다."""
    fa = np.dstack([normalize(a[:, :, c]) for c in range(3)])
    fb = np.dstack([normalize(b[:, :, c]) for c in range(3)])
    return np.sqrt(((fa - fb) ** 2).sum(axis=2))


METHODS = {
    "abs_diff": score_abs_diff,
    "norm_diff": score_norm_diff,
    "cva": score_cva,
}


# ------------------------------------------------------------- 이진화
def binarize(score, min_size=64):
    """Otsu 자동 임계값으로 변화/비변화를 가르고, 자잘한 점을 제거한다.

    min_size 미만의 덩어리는 대부분 노이즈(그림자 가장자리, 정합 잔차)라
    빼는 편이 F1이 올라간다. 0.5m 해상도에서 64화소 = 약 16m².
    """
    finite = score[np.isfinite(score)]
    if finite.size == 0 or finite.max() <= finite.min():
        return np.zeros(score.shape, dtype=bool)
    thr = threshold_otsu(finite)
    mask = score > thr
    if min_size > 0 and mask.any():
        mask = remove_small_objects(mask, min_size=min_size)
    return mask


# ------------------------------------------------------------- 평가지표
class Accumulator:
    """여러 장에 걸쳐 TP/FP/FN을 누적한다.

    장마다 F1을 내서 평균내면 '변화가 거의 없는 장'에서 F1이 0이나 1로
    튀어 전체 평균이 왜곡된다. 그래서 전 장의 화소를 합쳐 한 번에
    계산하는 방식(global/micro)을 쓴다 — 변화탐지 논문의 표준."""

    def __init__(self):
        self.tp = self.fp = self.fn = self.tn = 0

    def add(self, pred, gt):
        self.tp += int(np.logical_and(pred, gt).sum())
        self.fp += int(np.logical_and(pred, ~gt).sum())
        self.fn += int(np.logical_and(~pred, gt).sum())
        self.tn += int(np.logical_and(~pred, ~gt).sum())

    def result(self):
        tp, fp, fn, tn = self.tp, self.fp, self.fn, self.tn
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        iou = tp / (tp + fp + fn) if tp + fp + fn else 0.0
        return {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "iou": round(iou, 4),
            "accuracy": round((tp + tn) / max(tp + tn + fp + fn, 1), 4),
            "pred_change_pct": round(100 * (tp + fp) / max(tp + tn + fp + fn, 1), 2),
            "gt_change_pct": round(100 * (tp + fn) / max(tp + tn + fp + fn, 1), 2),
        }


# --------------------------------------------------------------- 데이터
def to_bool_mask(m):
    """정답 마스크를 bool로.

    ⚠️ 이 데이터셋의 마스크는 **0/1** 값이다 (0/255가 아님). 흔히 쓰는
    `m > 127` 로 이진화하면 전부 False가 되어 정답 변화 비율이 0%로 나오고,
    F1이 전부 0으로 찍힌다. `> 0` 이면 0/1·0/255 둘 다 올바르게 처리된다."""
    return np.asarray(m) > 0


def load_pairs(limit=None, split="test"):
    """PNG로 풀어놨으면 그걸 쓰고, 없으면 HuggingFace에서 바로 읽는다."""
    png_root = Path("data/external/levir_cdplus") / split
    if (png_root / "A").exists():
        files = sorted((png_root / "A").glob("*.png"))
        if limit:
            files = files[:limit]
        for f in files:
            a = cv2.cvtColor(cv2.imread(str(f)), cv2.COLOR_BGR2RGB)
            b = cv2.cvtColor(cv2.imread(str(png_root / "B" / f.name)), cv2.COLOR_BGR2RGB)
            m = cv2.imread(str(png_root / "label" / f.name), cv2.IMREAD_GRAYSCALE)
            yield a, b, to_bool_mask(m)
        return

    from datasets import load_dataset
    ds = load_dataset("blanchon/LEVIR_CDPlus", split=split)
    n = len(ds) if limit is None else min(limit, len(ds))
    for i in range(n):
        r = ds[i]
        a = np.array(r["image1"].convert("RGB"))
        b = np.array(r["image2"].convert("RGB"))
        yield a, b, to_bool_mask(np.array(r["mask"].convert("L")))


def shift_image(img, dx):
    """정합이 틀어진 상황을 흉내내려고 영상을 dx 화소만큼 민다."""
    if dx == 0:
        return img
    return np.roll(np.roll(img, dx, axis=0), dx, axis=1)


# ----------------------------------------------------------------- main
def evaluate(limit, split, shift, min_size, methods):
    accs = {m: Accumulator() for m in methods}
    t0 = time.time()
    n = 0
    for a, b, gt in load_pairs(limit, split):
        b_used = shift_image(b, shift)
        for m in methods:
            pred = binarize(METHODS[m](a, b_used), min_size=min_size)
            accs[m].add(pred, gt)
        n += 1
        if n % 25 == 0:
            print(f"    {n}장 처리...", flush=True)
    return {m: accs[m].result() for m in methods}, n, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100, help="평가에 쓸 장 수")
    ap.add_argument("--split", default="test")
    ap.add_argument("--min-size", type=int, default=64,
                    help="이보다 작은 덩어리는 노이즈로 제거 (0이면 끔)")
    ap.add_argument("--methods", default="abs_diff,norm_diff,cva")
    ap.add_argument("--shift", type=int, default=0, help="두 번째 영상을 N화소 밀어서 평가")
    ap.add_argument("--shift-sweep", default=None,
                    help="쉼표로 구분한 이동량 목록 (예: 0,2,4,6,8) — 정합 민감도 실험")
    ap.add_argument("--out", default="results/change_detection")
    args = ap.parse_args()

    methods = [m.strip() for m in args.methods.split(",") if m.strip() in METHODS]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"데이터 : LEVIR-CD+ {args.split} (최대 {args.limit}장, 1024x1024, 0.5m)")
    print(f"방법   : {', '.join(methods)}")
    print(f"노이즈 제거: {args.min_size}화소 미만 덩어리 삭제\n")

    if args.shift_sweep:
        shifts = [int(s) for s in args.shift_sweep.split(",")]
        sweep = {}
        for sh in shifts:
            print(f"=== 정합 오차 {sh}px ===")
            res, n, el = evaluate(args.limit, args.split, sh, args.min_size, methods)
            for m in methods:
                r = res[m]
                print(f"  {m:10} F1={r['f1']:.4f}  IoU={r['iou']:.4f}  "
                      f"정밀도={r['precision']:.4f}  재현율={r['recall']:.4f}")
            sweep[str(sh)] = res
            print(f"  ({n}장, {el:.1f}s)\n")
        payload = {"dataset": "LEVIR-CD+", "split": args.split, "n": args.limit,
                   "min_size": args.min_size, "shift_sweep": sweep,
                   "note": "두 번째 영상을 N화소 밀어서 정합 오차가 변화탐지에 주는 "
                           "영향을 정답 마스크 기준 F1으로 측정. 0.5m 해상도라 "
                           "1px = 0.5m."}
        path = out_dir / "levir_shift_sweep.json"
    else:
        res, n, el = evaluate(args.limit, args.split, args.shift, args.min_size, methods)
        print(f"{'방법':<12}{'F1':>8}{'IoU':>8}{'정밀도':>9}{'재현율':>9}{'예측변화%':>11}")
        print("-" * 58)
        for m in methods:
            r = res[m]
            print(f"{m:<12}{r['f1']:>8.4f}{r['iou']:>8.4f}{r['precision']:>9.4f}"
                  f"{r['recall']:>9.4f}{r['pred_change_pct']:>11.2f}")
        print(f"\n정답 변화 비율: {res[methods[0]]['gt_change_pct']:.2f}%")
        print(f"({n}장, {el:.1f}s)")
        payload = {"dataset": "LEVIR-CD+", "split": args.split, "n": n,
                   "shift_px": args.shift, "min_size": args.min_size, "results": res}
        path = out_dir / "levir_baseline.json"

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8", newline="\n")
    print(f"\n저장: {path}")


if __name__ == "__main__":
    main()
