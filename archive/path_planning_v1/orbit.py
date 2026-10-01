"""
2단계: 객체 부피 측정용 최소 궤도(orbit) 경로.

커버리지 비행 중 물체가 탐지되면, 그 지점에서 경로를 살짝 벗어나
물체 주위를 한 바퀴 돌며 photogrammetry(3D 복원)에 필요한 멀티뷰
사진을 찍고, 원래 경로로 복귀한다. "최소한의 경로"라는 요구사항을
반영해 다음 두 가지를 최소화한다:
 - 이탈 거리 (커버리지 경로 위 가장 가까운 지점에서 물체까지)
 - 궤도 자체의 길이 (필요한 뷰 개수만큼만 점을 찍음, 과도한 중복 비행 없음)
"""
import math
from dataclasses import dataclass

from coverage import Waypoint


@dataclass
class DetectedObject:
    id: str
    x: float
    y: float
    label: str          # STY / PLA / ROP / FIS
    size_m: float        # 대략적인 물체 지름(m) — 탐지 바운딩박스로부터 추정
    weight_kg: float = 0.0  # 3D 모듈 결과가 채워주는 값 (시뮬레이션에서는 랜덤 부여)


def min_views_for_object(size_m: float) -> int:
    """물체가 클수록 photogrammetry 품질을 위해 더 많은 뷰가 필요하지만,
    작은 물체는 6~8장으로도 충분하다 (volume3d 모듈 검증에서 20장 중
    23장 등록으로도 +20% 오차 수준이 나왔으므로, 실전에서는 여유를 두어
    10~12장을 기본값으로 한다)."""
    if size_m < 0.3:
        return 8
    if size_m < 0.8:
        return 10
    return 14


def orbit_radius(size_m: float, safety_margin_m: float = 1.0) -> float:
    return max(size_m / 2 + safety_margin_m, 1.5)


def orbit_waypoints(obj: DetectedObject, orbit_altitude_m: float) -> list[Waypoint]:
    radius = orbit_radius(obj.size_m)
    n = min_views_for_object(obj.size_m)
    pts = []
    for i in range(n + 1):  # +1: 시작점으로 돌아와 궤도를 닫음
        theta = 2 * math.pi * i / n
        x = obj.x + radius * math.cos(theta)
        y = obj.y + radius * math.sin(theta)
        pts.append(Waypoint(x, y, orbit_altitude_m, "orbit", f"{obj.id} view {i}"))
    return pts


def nearest_point_on_segment(px, py, ax, ay, bx, by):
    """점 (px,py)에서 선분 (a-b)에 내린 수선의 발과, 선분 내 비율 t."""
    abx, aby = bx - ax, by - ay
    len2 = abx * abx + aby * aby
    if len2 < 1e-9:
        return ax, ay, 0.0
    t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / len2))
    return ax + t * abx, ay + t * aby, t


def insert_orbits_into_coverage(coverage: list[Waypoint], objects: list[DetectedObject],
                                 detection_radius_m: float, orbit_altitude_m: float,
                                 cruise_altitude_m: float) -> list[Waypoint]:
    """커버리지 경로의 각 구간(segment)마다, 그 구간 근처(detection_radius
    이내)에서 탐지되는 물체를 찾아 '구간 위 가장 가까운 지점 -> 하강 ->
    궤도 비행 -> 재상승 -> 원래 구간 재개' 순으로 경로에 끼워 넣는다.
    물체마다 가장 가까운 구간 하나에서만 한 번 처리한다(중복 방지).
    """
    remaining = {o.id: o for o in objects}
    result: list[Waypoint] = []

    for seg_idx, (a, b) in enumerate(zip(coverage, coverage[1:])):
        result.append(a)
        # 이 구간에서 처리할 물체들을 구간 위 투영점 기준 정렬
        hits = []
        for obj in list(remaining.values()):
            nx, ny, t = nearest_point_on_segment(obj.x, obj.y, a.x, a.y, b.x, b.y)
            d = math.dist((obj.x, obj.y), (nx, ny))
            if d <= detection_radius_m:
                hits.append((t, nx, ny, obj))
        hits.sort(key=lambda h: h[0])

        for t, nx, ny, obj in hits:
            del remaining[obj.id]
            branch_point = Waypoint(nx, ny, a.z, "mapping", f"detour to {obj.id}")
            result.append(branch_point)
            result.append(Waypoint(obj.x, obj.y, orbit_altitude_m, "transit",
                                     f"descend for {obj.id}"))
            result.extend(orbit_waypoints(obj, orbit_altitude_m))
            result.append(Waypoint(nx, ny, cruise_altitude_m, "transit",
                                     f"resume after {obj.id}"))

    result.append(coverage[-1])

    if remaining:
        # detection_radius 밖에 있었던(스쳐 지나가지 못한) 물체는 이번
        # 패스에서 못 찍은 것으로 남는다 — mission.py가 이후 처리
        pass
    return result, list(remaining.values())
