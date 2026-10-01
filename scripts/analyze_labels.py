"""
기업 1차 데이터(MGD_쓰레기.json) 분석.

핵심 발견: weight_kg가 실측값이 아니라 "area_sqm × 재질별 고정 계수"로
단순 계산된 값이다 (아래에서 재질별 weight/area 비율의 분산이 거의 0임을
직접 확인). 이게 바로 선행연구(Andriolo 2024)가 한계로 지적한
"W3: 면적 × 가정한 두께 × 밀도" 방식과 같은 구조 — 즉 이 weight_kg는
우리가 3D로 개선해서 넘어서야 할 "기존 방법 베이스라인"이지,
실측 정답(GT)이 아니다.
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL_PATH = ROOT / "data/company/MGD_labels.json"


def load_features():
    data = json.loads(LABEL_PATH.read_text(encoding="utf-8"))
    return data["features"]


def main():
    feats = load_features()
    by_mat = defaultdict(list)
    for f in feats:
        by_mat[f["properties"]["material_code"]].append(f["properties"])

    print(f"총 {len(feats)}건, 재질 {len(by_mat)}종\n")

    report = {"n_total": len(feats), "materials": {}}
    print(f"{'재질':6} {'개수':>4} {'area(m²) 범위':>18} {'weight/area 평균':>16} {'분산(최대-최소)':>14}")
    for mat, items in sorted(by_mat.items()):
        areas = [i["area_sqm"] for i in items]
        ratios = [i["weight_kg"] / i["area_sqm"] for i in items]
        spread = max(ratios) - min(ratios)
        print(f"{mat:6} {len(items):>4} {min(areas):>8.2f}~{max(areas):<8.2f} "
              f"{sum(ratios)/len(ratios):>16.5f} {spread:>14.6f}")
        report["materials"][mat] = {
            "n": len(items),
            "area_min": min(areas), "area_max": max(areas),
            "weight_per_area_mean_kg_per_sqm": round(sum(ratios) / len(ratios), 6),
            "weight_per_area_spread": round(spread, 8),
        }

    print(
        "\n[결론] weight/area 비율의 분산(spread)이 사실상 0에 가깝다 "
        "→ weight_kg = area_sqm × 재질별 고정 상수. 즉 이 데이터의 '무게'는 "
        "면적만으로 계산된 추정치이지 실측값이 아니다.\n"
        "→ 우리의 3D 복원(DSM 기반 실제 부피) 결과가 이 고정 계수 방식보다 "
        "개별 물체마다 다른 실제 두께를 반영해 더 정확해야 한다는 게 "
        "이 과제의 핵심 논거가 된다. (노션 문서 Andriolo 2024 W3 비판과 정확히 일치)"
    )

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / "label_analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("\n저장: results/label_analysis.json")


if __name__ == "__main__":
    main()
