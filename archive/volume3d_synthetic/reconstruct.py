"""
입력: 물체 주위를 빙 돈 사진 폴더 (드론이 한 바퀴 돌며 찍은 영상에서
추출한 프레임, 또는 make_synthetic_object.py가 만든 합성 사진)
출력: 희소 포인트클라우드(.ply) + 카메라 포즈 (COLMAP sparse 모델)

pycolmap의 자동 파이프라인(특징점 추출 -> 매칭 -> 증분 SfM)을 그대로 사용.
GPU 없이 CPU에서도 동작.
"""
import shutil
import sys
from pathlib import Path

import pycolmap


def reconstruct(image_dir: Path, work_dir: Path) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    db_path = work_dir / "database.db"
    sparse_dir = work_dir / "sparse"
    sparse_dir.mkdir(exist_ok=True)

    if db_path.exists():
        db_path.unlink()

    print(f"[1/3] 특징점 추출: {image_dir}")
    pycolmap.extract_features(database_path=db_path, image_path=image_dir)

    print("[2/3] 특징점 매칭 (전체 쌍 비교 — 사진 수가 적을 때 적합)")
    pycolmap.match_exhaustive(database_path=db_path)

    print("[3/3] 증분 SfM 복원")
    maps = pycolmap.incremental_mapping(database_path=db_path, image_path=image_dir,
                                         output_path=sparse_dir)
    if not maps:
        raise RuntimeError("SfM 복원 실패: 모델이 생성되지 않음 (특징점/매칭 부족일 가능성)")

    best_id = max(maps, key=lambda k: maps[k].num_reg_images())
    rec = maps[best_id]
    print(f"등록된 카메라: {rec.num_reg_images()} / {len(list(image_dir.glob('*')))}")
    print(f"3D 포인트 수: {rec.num_points3D()}")

    model_dir = work_dir / "model"
    if model_dir.exists():
        shutil.rmtree(model_dir)
    model_dir.mkdir()
    rec.write(model_dir)

    ply_path = work_dir / "points.ply"
    rec.export_PLY(ply_path)
    print(f"포인트클라우드 저장: {ply_path}")
    return ply_path


if __name__ == "__main__":
    image_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/synthetic_box/images")
    work_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/synthetic_box/colmap")
    reconstruct(image_dir, work_dir)
