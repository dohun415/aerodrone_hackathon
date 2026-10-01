"""
LEVIR-CD+ 변화탐지 벤치마크 내려받기 (HuggingFace).

왜 이 데이터셋인가
------------------
드론 해상도(2~6cm)의 공개 변화탐지 데이터셋은 사실상 없다 — UCCD·DVCD는
아직 미공개이고, 제일 가까운 Hi-UCD(0.1m)도 신청이 필요하다. 그래서
**0.5m급 LEVIR-CD+**로 먼저 시작한다. 0.5m는 회사가 준 SkySat과 거의
같은 해상도라, 지금 갖고 있는 위성 데이터로 바로 이어서 검증할 수 있다.

구성: image1(전) / image2(후) / mask(정답 변화영역), 1024x1024
      train 637쌍 / test 348쌍, 약 3.8GB

정답 마스크가 있으니 **변화탐지 성능을 F1·IoU로 정량 평가**할 수 있다 —
지금까지 정합 단계에서 해온 것(합성 벤치마크로 정답을 아는 상태에서 측정)과
같은 방식이다.

    python pipeline/fetch_levir.py
    python pipeline/fetch_levir.py --export-png --limit 50
"""
import argparse
import os
from pathlib import Path

# 한글 경로에서 생길 수 있는 문제를 피하려고 캐시는 ASCII 경로(기본값)에 둔다.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

REPO = "blanchon/LEVIR_CDPlus"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-png", action="store_true",
                    help="parquet에서 PNG로 풀어서 data/external/levir_cdplus/ 에 저장")
    ap.add_argument("--limit", type=int, default=None,
                    help="PNG로 풀 때 각 split당 최대 장수 (없으면 전체)")
    ap.add_argument("--split", default="train,test")
    args = ap.parse_args()

    from datasets import load_dataset

    print(f"다운로드/로드: {REPO}")
    ds = load_dataset(REPO)
    print()
    for name, part in ds.items():
        print(f"  {name:6} {len(part):5d} 쌍   컬럼: {list(part.features)}")

    sample = ds["train"][0]
    print(f"\n샘플 크기: image1={sample['image1'].size} "
          f"image2={sample['image2'].size} mask={sample['mask'].size}")
    print(f"모드      : image1={sample['image1'].mode} mask={sample['mask'].mode}")

    if args.export_png:
        out_root = Path("data/external/levir_cdplus")
        for name in [s.strip() for s in args.split.split(",")]:
            if name not in ds:
                continue
            part = ds[name]
            n = len(part) if args.limit is None else min(args.limit, len(part))
            for sub in ("A", "B", "label"):
                (out_root / name / sub).mkdir(parents=True, exist_ok=True)
            print(f"\n[{name}] PNG로 풀기: {n}장")
            for i in range(n):
                r = part[i]
                r["image1"].save(out_root / name / "A" / f"{i:05d}.png")
                r["image2"].save(out_root / name / "B" / f"{i:05d}.png")
                r["mask"].save(out_root / name / "label" / f"{i:05d}.png")
                if (i + 1) % 25 == 0 or i + 1 == n:
                    print(f"   {i + 1}/{n}", flush=True)
        print(f"\n저장 위치: {out_root}")

    print("\n완료")


if __name__ == "__main__":
    main()
