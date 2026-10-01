"""
변화탐지 결과를 눈으로 확인하는 그림 생성.

  11_levir_examples.png    전/후/정답/예측 나란히 (방법별)
  12_levir_shift_sweep.png 정합 오차가 커질수록 F1이 어떻게 무너지는가
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
from _compat import apply_korean_font

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

apply_korean_font()

import importlib.util
spec = importlib.util.spec_from_file_location(
    "cd", Path(__file__).resolve().parent / "07_change_detection.py")
cd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cd)

OUT = Path("results/figures")
OUT.mkdir(parents=True, exist_ok=True)


def examples(n=3, split="test", min_size=64, methods=("norm_diff", "cva")):
    rows = list(cd.load_pairs(limit=n, split=split))
    ncol = 3 + len(methods)
    fig, ax = plt.subplots(len(rows), ncol, figsize=(3.2 * ncol, 3.2 * len(rows)))
    if len(rows) == 1:
        ax = ax[None, :]
    for i, (a, b, gt) in enumerate(rows):
        ax[i, 0].imshow(a); ax[i, 0].set_ylabel(f"#{i}", fontsize=11)
        ax[i, 1].imshow(b)
        ax[i, 2].imshow(gt, cmap="gray")
        for j, m in enumerate(methods):
            pred = cd.binarize(cd.METHODS[m](a, b), min_size=min_size)
            # 맞춘 곳(녹)·놓친 곳(빨)·헛본 곳(파)을 색으로 구분
            rgb = np.zeros((*gt.shape, 3), dtype=np.float32)
            rgb[np.logical_and(pred, gt)] = (0.1, 0.9, 0.2)     # TP
            rgb[np.logical_and(~pred, gt)] = (0.95, 0.2, 0.2)   # FN 놓침
            rgb[np.logical_and(pred, ~gt)] = (0.2, 0.5, 1.0)    # FP 헛봄
            ax[i, 3 + j].imshow(rgb)
        if i == 0:
            titles = ["전 (image1)", "후 (image2)", "정답 마스크"] + \
                     [f"{m}\n녹=맞춤 빨=놓침 파=헛봄" for m in methods]
            for j, t in enumerate(titles):
                ax[i, j].set_title(t, fontsize=10)
    for a_ in ax.ravel():
        a_.set_xticks([]); a_.set_yticks([])
    fig.suptitle("LEVIR-CD+ 픽셀 단위 변화탐지 — 고전 기법 베이스라인 (학습 없음)",
                 fontsize=13)
    fig.tight_layout()
    fig.savefig(OUT / "11_levir_examples.png", dpi=120)
    plt.close(fig)
    print("saved 11_levir_examples.png")


def sweep_plot(path="results/change_detection/levir_shift_sweep.json"):
    p = Path(path)
    if not p.exists():
        print(f"건너뜀 — {p} 없음 (--shift-sweep 먼저 실행)")
        return
    d = json.loads(p.read_text(encoding="utf-8"))
    sw = d["shift_sweep"]
    shifts = sorted(int(k) for k in sw)
    methods = list(sw[str(shifts[0])].keys())

    fig, ax = plt.subplots(1, 2, figsize=(12, 4.4))
    for m in methods:
        ax[0].plot(shifts, [sw[str(s)][m]["f1"] for s in shifts], "o-", label=m)
        ax[1].plot(shifts, [sw[str(s)][m]["precision"] for s in shifts], "o-", label=m)
    ax[0].set_xlabel("정합 오차 (픽셀, 1px = 0.5m)"); ax[0].set_ylabel("F1")
    ax[0].set_title("정합이 틀어지면 변화탐지 F1이 무너진다")
    ax[1].set_xlabel("정합 오차 (픽셀)"); ax[1].set_ylabel("정밀도")
    ax[1].set_title("정밀도 — 헛본 변화(가짜)가 얼마나 느는가")
    for a_ in ax:
        a_.grid(alpha=0.3); a_.legend(); a_.set_ylim(0, None)
    fig.suptitle("정합 품질이 변화탐지에 주는 영향 (LEVIR-CD+ 정답 기준)", fontsize=13)
    fig.tight_layout()
    fig.savefig(OUT / "12_levir_shift_sweep.png", dpi=130)
    plt.close(fig)
    print("saved 12_levir_shift_sweep.png")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", type=int, default=3)
    ap.add_argument("--split", default="test")
    ap.add_argument("--min-size", type=int, default=64)
    args = ap.parse_args()
    examples(args.examples, args.split, args.min_size)
    sweep_plot()
