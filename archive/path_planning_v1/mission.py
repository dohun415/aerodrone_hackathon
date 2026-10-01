"""
전체 파이프라인을 하나로 묶는 미션 플래너.

1) 맵핑 커버리지 경로 생성
2) 비행 중 탐지되는 물체마다 궤도(orbit) 경로를 끼워 넣음 (경로 변경)
3) 맵핑이 끝나면 탐지된 전체 물체로 지자체 수거 경로 계획

실제 드론에 아직 연결되지 않았으므로(미니5프로 SDK 부재), 이 모듈은
"탐지된 물체 목록"을 입력으로 받는 시뮬레이션 모드로 동작한다. 나중에
Module 2(실시간 객체탐지)가 실제 탐지 스트림을 이 입력 형식으로 넘겨주면
그대로 연결된다.

실행하면 3D 시뮬레이션(Three.js)이 읽을 수 있는 JSON을 내보낸다.
"""
import json
import random
from dataclasses import asdict
from pathlib import Path

from coverage import Waypoint, boustrophedon_path, path_length
from orbit import DetectedObject, insert_orbits_into_coverage
from collection_route import plan_collection, summarize

FIELD = (0.0, 0.0, 160.0, 90.0)   # x0,y0,x1,y1 (m)
CRUISE_ALT = 30.0
ORBIT_ALT = 8.0
DETECTION_RADIUS = 20.0
TRUCK_CAPACITY_KG = 150.0
BASE = Waypoint(FIELD[0] - 10, FIELD[1] - 15, 0.0, "collection", "집결지(dock)")

LABELS = ["STY", "PLA", "ROP", "FIS"]
LABEL_DENSITY = {"STY": 0.02, "PLA": 0.35, "ROP": 0.40, "FIS": 0.15}  # kg/L, volume3d 모듈과 동일


def make_scenario(n_objects: int = 7, seed: int = 7) -> list[DetectedObject]:
    rng = random.Random(seed)
    x0, y0, x1, y1 = FIELD
    objs = []
    for i in range(n_objects):
        label = rng.choice(LABELS)
        size = rng.uniform(0.2, 0.9)
        volume_L = (size ** 3) * 1000 * rng.uniform(0.3, 0.6)  # 대략적 부피 근사
        weight = volume_L * LABEL_DENSITY[label]
        objs.append(DetectedObject(
            id=f"obj{i:02d}",
            x=rng.uniform(x0 + 5, x1 - 5),
            y=rng.uniform(y0 + 5, y1 - 5),
            label=label,
            size_m=size,
            weight_kg=round(weight, 2),
        ))
    return objs


def run_mission(objects: list[DetectedObject]) -> dict:
    x0, y0, x1, y1 = FIELD
    coverage = boustrophedon_path(x0, y0, x1, y1, CRUISE_ALT)
    full_path, missed = insert_orbits_into_coverage(
        coverage, objects, DETECTION_RADIUS, ORBIT_ALT, CRUISE_ALT)

    missed_ids = {o.id for o in missed}
    detected = [o for o in objects if o.id not in missed_ids]

    routes = plan_collection(detected, BASE, TRUCK_CAPACITY_KG)

    mapping_len = path_length([w for w in full_path if w.phase in ("mapping", "transit")])
    orbit_len = path_length([w for w in full_path if w.phase == "orbit"])

    collection_path: list[Waypoint] = [BASE]
    for r in routes:
        for idx in r.route_order:
            obj = r.stops[idx]
            collection_path.append(Waypoint(obj.x, obj.y, 0.0, "collection",
                                              f"{r.truck_id}: {obj.id} ({obj.label})"))
        collection_path.append(Waypoint(BASE.x, BASE.y, 0.0, "collection",
                                          f"{r.truck_id} 복귀"))

    out = {
        "field": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
        "base": asdict(BASE),
        "mapping_orbit_path": [asdict(w) for w in full_path],
        "collection_path": [asdict(w) for w in collection_path],
        "objects": [asdict(o) for o in objects],
        "missed_objects": [o.id for o in missed],
        "truck_routes": [
            {
                "truck_id": r.truck_id, "label": r.label,
                "stops": [r.stops[i].id for i in r.route_order],
                "total_weight_kg": r.total_weight_kg,
                "distance_m": r.distance_m,
            } for r in routes
        ],
        "stats": {
            "mapping_path_m": mapping_len,
            "orbit_path_m": orbit_len,
            "n_objects_detected": len(detected),
            "n_objects_missed": len(missed),
            "n_trucks": len(routes),
            "total_weight_kg": sum(o.weight_kg for o in detected),
        },
    }
    return out


def main():
    objects = make_scenario()
    result = run_mission(objects)

    print(f"맵핑 경로 길이: {result['stats']['mapping_path_m']:.0f} m")
    print(f"궤도(orbit) 추가 경로 길이: {result['stats']['orbit_path_m']:.0f} m")
    print(f"탐지된 물체: {result['stats']['n_objects_detected']} / {len(objects)}")
    print()
    routes_for_print = plan_collection(
        [o for o in objects if o.id not in result["missed_objects"]], BASE, TRUCK_CAPACITY_KG)
    print(summarize(routes_for_print))

    out_path = Path("data/mission.json")
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n시뮬레이션용 JSON 저장: {out_path}")


if __name__ == "__main__":
    main()
