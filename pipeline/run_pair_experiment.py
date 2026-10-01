"""
임의의 "두 영상 페어"를 ①'②③④⑤⑥ 단계에 통째로 넣고, 결과를
results/<label>/ 아래에 모아주는 러너.

왜 필요한가
-----------
기존 스크립트들은 결과를 전부 `results/*.json` 한 곳에 쓴다. 그래서
다른 페어로 다시 돌리면 이전 실험 결과를 덮어써 버린다. 지금까지의
README 숫자는 전부 "Sentinel 2019 vs 2026" 페어에서 나온 것이라
이걸 보존한 채로 새 페어를 돌려야 한다.

이 러너는 각 단계를 실행한 뒤 생성된 JSON·그림을 `results/<label>/`
로 옮겨서 페어별로 분리 보관한다. ④단계(SIFT/LoFTR)는 원래 파일로
저장하지 않고 stdout에만 출력하므로, 여기서 받아 저장한다.

사용 예
-------
    python pipeline/run_pair_experiment.py \
        --ref data/raw/s2_2026-08-12_51SYB_B04.tif \
        --mov data/raw/s2_2026-09-16_52SBG_B04.tif \
        --label gulupdo_2026-08-12_vs_2026-09-16 \
        --mask-date 2026-08-12 --mask-tile 51SYB

SkySat 실데이터가 들어오면 --ref 만 그 파일로 바꿔서 그대로 쓰면 된다.
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
RESULTS = ROOT / "results"

# 각 단계가 만들어내는 산출물 (단계 실행 후 <label>/ 로 옮긴다)
ARTIFACTS = {
    "01": ["drone_view_rectify.json", "figures/06_drone_view_rectify.png"],
    "02": ["global_shift.json"],
    "03": ["mask_comparison.json", "figures/04_mask_ndwi_vs_rgb.png"],
    "05": ["local_correction.json"],
    "06": ["quality_report.json"],
}


def run(label, cmd, capture=False):
    """한 단계 실행. capture=True면 stdout을 문자열로 돌려준다."""
    print(f"\n{'=' * 64}")
    print(f"  {label}")
    print(f"{'=' * 64}")
    print(f"$ {' '.join(str(c) for c in cmd)}\n", flush=True)
    t0 = time.time()
    if capture:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        print(p.stdout)
        if p.stderr.strip():
            print("[stderr]", p.stderr[-2000:], file=sys.stderr)
    else:
        p = subprocess.run(cmd, cwd=ROOT, text=True, encoding="utf-8", errors="replace")
    dt = time.time() - t0
    ok = p.returncode == 0
    print(f"  -> {'성공' if ok else '실패(코드 %d)' % p.returncode}  ({dt:.1f}s)", flush=True)
    return ok, (p.stdout if capture else None)


def backup(names):
    """단계를 돌리기 전에, 기존 results/ 산출물을 임시로 떠 둔다.

    각 단계 스크립트는 결과를 results/ 루트에 고정 파일명으로 쓴다.
    그대로 두면 기존 실험(README의 Sentinel 2019 vs 2026 숫자)의
    결과 파일이 덮어써지고, stash()가 그걸 가져가 버린다.
    실행 전에 원본을 떠 두고 stash() 뒤에 되돌려 놓는다.
    """
    saved = {}
    for n in names:
        src = RESULTS / n
        if src.exists():
            saved[n] = src.read_bytes()
    return saved


def stash(out_dir: Path, names, saved=None):
    """단계가 만든 산출물을 results/<label>/ 로 옮기고,
    기존 실험 결과가 있었다면 results/ 루트에 원상복구한다."""
    for n in names:
        src = RESULTS / n
        if not src.exists():
            continue
        dst = out_dir / Path(n).name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        print(f"     보관: {dst.relative_to(ROOT)}")
    for n, blob in (saved or {}).items():
        target = RESULTS / n
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        print(f"     복원: results/{n} (기존 실험 결과)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="기준 영상 (①'②⑤⑥의 ref/fixed)")
    ap.add_argument("--mov", required=True, help="대상 영상")
    ap.add_argument("--label", required=True, help="results/<label>/ 에 저장")
    ap.add_argument("--gsd", type=float, default=10.0)
    ap.add_argument("--wp_x", type=float, default=232210.74, help="②단계 AROSICS 매칭 윈도우 중심 X (육지)")
    ap.add_argument("--wp_y", type=float, default=4119811.13)
    ap.add_argument("--mask-date", default=None, help="③단계용 날짜 (없으면 건너뜀)")
    ap.add_argument("--mask-tile", default=None)
    ap.add_argument("--top_margin", type=float, default=0.22)
    ap.add_argument("--skip", default="", help="건너뛸 단계 (쉼표: 01,02,03,04,05,06)")
    args = ap.parse_args()

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    out_dir = RESULTS / args.label
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"페어 실험: {args.label}")
    print(f"  ref(기준) : {args.ref}")
    print(f"  mov(대상) : {args.mov}")
    print(f"  결과 저장 : results/{args.label}/")

    summary = {"label": args.label, "ref": args.ref, "mov": args.mov, "steps": {}}

    # ①' 드론 시점 보정 — ref 영상 하나로 합성 오블리크를 만들어 검증
    if "01" not in skip:
        saved = backup(ARTIFACTS["01"])
        ok, _ = run("①' 드론 시점 보정 (합성 오블리크 vs 위성)",
                    [PY, "pipeline/01_drone_view_rectify.py",
                     "--ref", args.ref, "--gsd", str(args.gsd),
                     "--top_margin", str(args.top_margin)])
        summary["steps"]["01_drone_view_rectify"] = ok
        stash(out_dir, ARTIFACTS["01"], saved)

    # ② 전역 이동 보정
    if "02" not in skip:
        saved = backup(ARTIFACTS["02"])
        ok, _ = run("② 전역 이동 보정 (AROSICS + phase_cross_correlation)",
                    [PY, "pipeline/02_global_shift.py",
                     "--ref", args.ref, "--mov", args.mov, "--gsd", str(args.gsd),
                     "--wp_x", str(args.wp_x), "--wp_y", str(args.wp_y)])
        summary["steps"]["02_global_shift"] = ok
        stash(out_dir, ARTIFACTS["02"], saved)

    # ③ 수면·모래 마스킹 (밴드 4종이 다 있어야 함)
    if "03" not in skip and args.mask_date:
        saved = backup(ARTIFACTS["03"])
        ok, _ = run("③ 수면·모래 마스킹 (NDWI vs RGB-only)",
                    [PY, "pipeline/03_stable_mask.py",
                     "--date", args.mask_date, "--tile", args.mask_tile])
        summary["steps"]["03_stable_mask"] = ok
        stash(out_dir, ARTIFACTS["03"], saved)

    # ④ AI 정밀정합 — stdout으로만 출력되므로 받아서 저장
    if "04" not in skip:
        matching = {}
        for name, script in [("SIFT+RANSAC", "pipeline/ai_matching/sift_baseline.py"),
                             ("LoFTR(kornia)", "pipeline/ai_matching/loftr_run.py")]:
            ok, out = run(f"④ AI 정밀정합 — {name}",
                          [PY, script, "--src", args.ref, "--dst", args.mov,
                           "--gsd", str(args.gsd)], capture=True)
            if ok and out:
                try:
                    matching[name] = json.loads(out[out.index("{"):out.rindex("}") + 1])
                except (ValueError, json.JSONDecodeError) as e:
                    matching[name] = {"error": f"출력 파싱 실패: {e}"}
            else:
                matching[name] = {"error": "실행 실패"}
        (out_dir / "ai_matching.json").write_text(
            json.dumps(matching, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        print(f"     보관: results/{args.label}/ai_matching.json")
        summary["steps"]["04_ai_matching"] = all("error" not in v for v in matching.values())

    # ⑤ 국소 보정
    if "05" not in skip:
        saved = backup(ARTIFACTS["05"])
        ok, _ = run("⑤ 국소 보정 (itk-elastix B-스플라인)",
                    [PY, "pipeline/05_local_correction.py",
                     "--fixed", args.ref, "--moving", args.mov])
        summary["steps"]["05_local_correction"] = ok
        stash(out_dir, ARTIFACTS["05"], saved)

    # ⑥ 품질 검증
    if "06" not in skip:
        saved = backup(ARTIFACTS["06"])
        ok, _ = run("⑥ 품질 검증 (합격 기준 + LoD)",
                    [PY, "pipeline/06_quality_report.py",
                     "--ref", args.ref, "--mov", args.mov, "--gsd", str(args.gsd)])
        summary["steps"]["06_quality_report"] = ok
        stash(out_dir, ARTIFACTS["06"], saved)

    (out_dir / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    print(f"\n{'=' * 64}")
    failed = [k for k, v in summary["steps"].items() if not v]
    if failed:
        print(f"  실패한 단계: {', '.join(failed)}")
    else:
        print("  전체 단계 성공")
    print(f"  결과: results/{args.label}/")
    print(f"{'=' * 64}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
