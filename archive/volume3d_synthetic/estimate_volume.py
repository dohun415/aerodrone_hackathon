"""
입력: reconstruct.py가 만든 COLMAP sparse 모델(카메라 포즈 + 포인트클라우드)
출력: 부피(L) + 재질별 추정 무게(kg)

핵심 문제 — 스케일: 사진만으로 하는 SfM 복원은 "상대적인" 3D 구조만
복원하고, 실제 크기(미터 단위)는 알 수 없다 (사진 한 장 확대/축소해도
기하학적으로 구별 불가능하기 때문). 그래서 실제 파이프라인에서는
Module 1에서 기록하는 드론의 GPS/IMU 궤적으로 카메라 이동 거리를
알아내 스케일을 고정한다. 이 검증에서는 그 역할을 합성 데이터 생성 시
기록해 둔 "진짜 카메라 위치"가 대신한다: COLMAP이 추정한 카메라 간
거리와 진짜 카메라 간 거리의 비율로 스케일 배율을 구해 포인트클라우드
전체에 곱한다.

부피: 포인트클라우드의 convex hull(볼록 껍질) 부피로 근사한다.
쓰레기(상자, 통, 덩어리 등 대부분 오목하지 않은 형태)에는 합리적인
근사이며, 희소 포인트클라우드에서도 안정적으로 계산 가능하다는 장점.
"""
import json
import sys
from pathlib import Path

import numpy as np
import open3d as o3d
import pycolmap

# 재질별 "겉보기 밀도" (kg/L) — 압축되지 않은 상태로 둥둥 떠 있거나
# 바닥에 놓인 해양쓰레기 기준. 스티로폼은 내부가 거의 공기라 실제
# 폴리스티렌 밀도(1.05 kg/L)가 아니라 발포체 겉보기밀도를 쓴다.
MATERIAL_DENSITY_KG_PER_L = {
    "STY": 0.02,   # 스티로폼(발포) 부표/상자
    "PLA": 0.35,   # 플라스틱 용기류 (속이 빈 경우 많음)
    "ROP": 0.40,   # 로프/줄 뭉치
    "FIS": 0.15,   # 폐어망
}


def recover_scale(rec: pycolmap.Reconstruction, cams_meta: list[dict]) -> float:
    """COLMAP 추정 카메라 간 거리 vs 진짜 카메라 간 거리로 스케일 배율 계산."""
    true_by_name = {c["file"]: np.array(c["eye"]) for c in cams_meta}

    names, est_centers = [], []
    for image_id, image in rec.images.items():
        name = image.name
        if name in true_by_name:
            names.append(name)
            est_centers.append(np.array(image.projection_center()))
    if len(names) < 2:
        raise RuntimeError("스케일 계산 불가: 등록된 카메라가 2개 미만")

    ratios = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            true_d = np.linalg.norm(true_by_name[names[i]] - true_by_name[names[j]])
            est_d = np.linalg.norm(est_centers[i] - est_centers[j])
            if est_d > 1e-6 and true_d > 1e-6:
                ratios.append(true_d / est_d)
    scale = float(np.median(ratios))
    print(f"스케일 배율 추정: {scale:.4f} (카메라 쌍 {len(ratios)}개 중앙값)")
    return scale


def convex_hull_volume(points: np.ndarray) -> tuple[float, o3d.geometry.TriangleMesh]:
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)
    # SfM은 잘못 매칭된 특징점 때문에 물체에서 멀리 떨어진 이상점을
    # 종종 만든다. 이상점 하나가 convex hull 부피를 크게 부풀리므로
    # 통계적 이상점 제거를 먼저 적용한다.
    pcd_clean, _ = pcd.remove_statistical_outlier(nb_neighbors=16, std_ratio=1.5)
    print(f"이상점 제거: {len(pcd.points)} -> {len(pcd_clean.points)}")
    hull, _ = pcd_clean.compute_convex_hull()
    hull.compute_vertex_normals()
    volume = hull.get_volume()
    return volume, hull


def main():
    work_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/synthetic_box")
    model_dir = work_dir / "colmap" / "model"
    gt_path = work_dir / "ground_truth.json"

    rec = pycolmap.Reconstruction(model_dir)
    gt = json.loads(gt_path.read_text())

    scale = recover_scale(rec, gt["cameras"])

    points = np.array([p.xyz for p in rec.points3D.values()])
    print(f"포인트 수: {len(points)}")

    raw_volume_m3, hull = convex_hull_volume(points)
    volume_m3 = raw_volume_m3 * (scale ** 3)
    volume_L = volume_m3 * 1000

    print(f"\n복원된 convex hull 부피 (스케일 보정 전, 임의 단위³): {raw_volume_m3:.6f}")
    print(f"스케일 보정 후 부피: {volume_m3:.5f} m³ = {volume_L:.2f} L")

    if "true_volume_L" in gt:
        true_L = gt["true_volume_L"]
        err_pct = (volume_L - true_L) / true_L * 100
        print(f"정답 부피: {true_L:.2f} L  |  오차: {err_pct:+.1f}%")

    print("\n재질별 추정 무게:")
    for mat, density in MATERIAL_DENSITY_KG_PER_L.items():
        print(f"  {mat}: {volume_L * density:.3f} kg  (밀도 {density} kg/L 가정)")

    out_mesh = work_dir / "colmap" / "hull_scaled.ply"
    hull_scaled = o3d.geometry.TriangleMesh(hull)
    hull_scaled.vertices = o3d.utility.Vector3dVector(np.asarray(hull.vertices) * scale)
    o3d.io.write_triangle_mesh(str(out_mesh), hull_scaled)
    print(f"\nconvex hull 메시 저장: {out_mesh}")


if __name__ == "__main__":
    main()
