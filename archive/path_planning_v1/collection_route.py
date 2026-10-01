"""
3단계: 지자체 수거 경로 계획.

매핑+궤도 비행이 끝나 모든 쓰레기의 위치·종류·무게를 알고 나면,
① 종류별로 모아서 트럭에 실을지 묶음을 정하고(분리수거 요구사항),
② 각 묶음 내에서 최단 경로(TSP 근사: 최근접 이웃 + 2-opt)를 구하고,
③ 트럭 적재 용량을 넘으면 트럭을 추가 배차한다.
"""
import math
from dataclasses import dataclass

from orbit import DetectedObject


@dataclass
class TruckRoute:
    truck_id: str
    label: str
    stops: list[DetectedObject]
    total_weight_kg: float
    route_order: list[int]   # stops 리스트 내 방문 순서 인덱스
    distance_m: float


def _dist(a: DetectedObject, b: DetectedObject) -> float:
    return math.dist((a.x, a.y), (b.x, b.y))


def _nearest_neighbor_route(base, points: list[DetectedObject]) -> list[int]:
    unvisited = list(range(len(points)))
    order = []
    cur = base
    while unvisited:
        nxt = min(unvisited, key=lambda i: math.dist((cur.x, cur.y), (points[i].x, points[i].y)))
        order.append(nxt)
        unvisited.remove(nxt)
        cur = points[nxt]
    return order


def _route_distance(base, points, order) -> float:
    total = 0.0
    cur = base
    for i in order:
        total += math.dist((cur.x, cur.y), (points[i].x, points[i].y))
        cur = points[i]
    return total


def _two_opt(base, points: list[DetectedObject], order: list[int]) -> list[int]:
    improved = True
    best = order[:]
    best_d = _route_distance(base, points, best)
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                d = _route_distance(base, points, cand)
                if d < best_d - 1e-9:
                    best, best_d = cand, d
                    improved = True
    return best


def _solve_route(base, points: list[DetectedObject]) -> tuple[list[int], float]:
    if not points:
        return [], 0.0
    order = _nearest_neighbor_route(base, points)
    order = _two_opt(base, points, order)
    return order, _route_distance(base, points, order)


def plan_collection(objects: list[DetectedObject], base, truck_capacity_kg: float,
                     group_by_label: bool = True) -> list[TruckRoute]:
    """종류별로 트럭을 나누고, 용량을 넘으면 같은 종류 트럭을 추가 배차.
    방문 순서는 그룹 내에서 최근접이웃+2-opt로 최적화.
    """
    groups: dict[str, list[DetectedObject]] = {}
    key_fn = (lambda o: o.label) if group_by_label else (lambda o: "ALL")
    for obj in objects:
        groups.setdefault(key_fn(obj), []).append(obj)

    routes: list[TruckRoute] = []
    for label, items in groups.items():
        order, _ = _solve_route(base, items)
        ordered_items = [items[i] for i in order]

        truck_idx = 1
        bucket: list[DetectedObject] = []
        bucket_weight = 0.0

        def flush():
            nonlocal truck_idx, bucket, bucket_weight
            if not bucket:
                return
            sub_order, dist = _solve_route(base, bucket)
            routes.append(TruckRoute(
                truck_id=f"{label}-{truck_idx:02d}",
                label=label,
                stops=bucket,
                total_weight_kg=bucket_weight,
                route_order=sub_order,
                distance_m=dist,
            ))
            truck_idx += 1
            bucket = []
            bucket_weight = 0.0

        for obj in ordered_items:
            if bucket and bucket_weight + obj.weight_kg > truck_capacity_kg:
                flush()
            bucket.append(obj)
            bucket_weight += obj.weight_kg
        flush()

    return routes


def summarize(routes: list[TruckRoute]) -> str:
    lines = [f"총 트럭 {len(routes)}대 필요"]
    for r in routes:
        lines.append(f"  {r.truck_id} ({r.label}): {len(r.stops)}곳, "
                      f"{r.total_weight_kg:.1f}kg, 이동거리 {r.distance_m:.0f}m")
    return "\n".join(lines)
