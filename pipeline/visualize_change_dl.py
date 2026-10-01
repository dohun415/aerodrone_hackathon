"""
13_levir_classic_vs_dl.png — 고전 기법 vs 사전학습 딥러닝 나란히 비교.

⑦단계에서 고전 기법이 F1 0.136에 그친 이유(계절·조명 변화를 전부 변화로
오인)와, ⑦-2 딥러닝이 F1 0.792로 올라간 차이를 한 장으로 보여준다.
"""
import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.append(str(_HERE))
from _compat import apply_korean_font, pick_torch_device

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

apply_korean_font()


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, _HERE / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


cd07 = _load("cd07", "07_change_detection.py")
dl08 = _load("dl08", "08_change_detection_dl.py")

OUT = Path("results/figures")
OUT.mkdir(parents=True, exist_ok=True)


def tp_fp_fn_rgb(pred, gt):
    """맞춤(녹)·놓침(빨)·헛봄(파)로 칠한 RGB."""
    rgb = np.zeros((*gt.shape, 3), dtype=np.float32)
    rgb[np.logical_and(pred, gt)] = (0.10, 0.90, 0.25)
    rgb[np.logical_and(~pred, gt)] = (0.95, 0.20, 0.20)
    rgb[np.logical_and(pred, ~gt)] = (0.20, 0.50, 1.00)
    return rgb


def f1_of(pred, gt):
    tp = np.logical_and(pred, gt).sum()
    fp = np.logical_and(pred, ~gt).sum()
    fn = np.logical_and(~pred, gt).sum()
    return 2 * tp / max(2 * tp + fp + fn, 1)


def main(n=3, split="test"):
    device = pick_torch_device()
    model = dl08.load_model(device)

    rows = list(cd07.load_pairs(limit=n, split=split))
    ncol = 5
    fig, ax = plt.subplots(len(rows), ncol, figsize=(3.3 * ncol, 3.4 * len(rows)))
    if len(rows) == 1:
        ax = ax[None, :]

    for i, (a, b, gt) in enumerate(rows):
        pred_c = cd07.binarize(cd07.METHODS["cva"](a, b), min_size=64)
        prob = dl08.predict_tile(model, a, b, device, tile=256)
        pred_d = prob > 0.5

        ax[i, 0].imshow(a)
        ax[i, 1].imshow(b)
        ax[i, 2].imshow(gt, cmap="gray")
        ax[i, 3].imshow(tp_fp_fn_rgb(pred_c, gt))
        ax[i, 4].imshow(tp_fp_fn_rgb(pred_d, gt))
        ax[i, 3].set_xlabel(f"F1 = {f1_of(pred_c, gt):.3f}", fontsize=11, color="#b00")
        ax[i, 4].set_xlabel(f"F1 = {f1_of(pred_d, gt):.3f}", fontsize=11, color="#070")
        if i == 0:
            for j, t in enumerate(["전 (image1)", "후 (image2)", "정답 마스크",
                                   "고전 기법 (cva)\n전체 F1 0.136",
                                   "딥러닝 AdaptFormer\n전체 F1 0.792"]):
                ax[i, j].set_title(t, fontsize=11)

    for a_ in ax.ravel():
        a_.set_xticks([]); a_.set_yticks([])
    fig.suptitle("픽셀 단위 변화탐지 — 고전 기법 vs 사전학습 딥러닝  "
                 "(녹=맞춤, 빨=놓침, 파=헛봄)", fontsize=14)
    fig.tight_layout()
    fig.savefig(OUT / "13_levir_classic_vs_dl.png", dpi=120)
    print("saved 13_levir_classic_vs_dl.png")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
