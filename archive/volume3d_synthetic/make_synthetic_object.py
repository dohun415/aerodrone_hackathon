"""
실제 드론으로 쓰레기 주위를 돈 사진이 아직 없어서, "정답 부피를 아는"
합성 물체를 만들고 그 주위를 도는 가상 카메라로 사진을 찍는다.
(이전에 이 프로젝트 전체에서 썼던 방식과 동일한 방법론 —
실제 데이터 전에 정답을 아는 합성 데이터로 파이프라인 자체를 검증)

물체: 스티로폼 상자를 흉내낸 직육면체(가로×세로×높이, 단위 m).
표면에 체커보드 무늬를 넣는 이유: SfM(구조화 모션)은 특징점을 매칭해서
3D를 복원하는데, 민무늬 표면은 매칭할 특징점이 없어 복원이 실패한다.

렌더링은 Open3D의 OffscreenRenderer(Filament)가 이 macOS 환경에서
"EGL Headless is not supported on this platform" 오류로 아예 쓸 수
없어서, 직접 만든 간단한 OpenCV 기반 투영/텍스처 워핑 렌더러를 쓴다
(상자는 볼록체라 face painter's algorithm으로 충분히 정확하게 그려짐).
"""
import json
from pathlib import Path

import cv2
import numpy as np

OUT_DIR = Path("data/synthetic_box")
BOX_SIZE = (0.40, 0.25, 0.20)  # m: 가로(x), 세로(y), 높이(z)
N_VIEWS = 32
IMG_W, IMG_H = 960, 720
FOV_DEG = 55.0


def speckle_texture(size=512, seed=0):
    """특징점 매칭용 무작위 반점 텍스처 (BGR).

    체커보드처럼 반복되는 무늬는 칸들이 서로 구별이 안 돼서 SfM
    매칭이 모호해지고 복원이 실패한다 (실제로 체커보드로 시도했더니
    32장 중 2장만 등록되는 참사가 남). 무작위 반점은 지역마다 고유한
    패턴이라 각 특징점이 서로 뚜렷하게 구별된다.
    """
    rng = np.random.default_rng(seed)
    img = np.full((size, size, 3), 235, dtype=np.uint8)
    for _ in range(900):
        x, y = rng.integers(0, size, 2)
        r = rng.integers(4, 18)
        color = tuple(int(c) for c in rng.integers(0, 200, 3))
        cv2.circle(img, (int(x), int(y)), int(r), color, -1)
    cv2.line(img, (0, 0), (size, size), (0, 0, 255), 4)
    cv2.line(img, (0, size - 1), (size - 1, 0), (0, 255, 0), 4)
    return img


def box_vertices(size):
    w, h, d = size
    x, y, z = w / 2, h / 2, d / 2
    return np.array([
        [-x, -y, -z], [x, -y, -z], [x, y, -z], [-x, y, -z],  # bottom (z-)
        [-x, -y, z], [x, -y, z], [x, y, z], [-x, y, z],      # top (z+)
    ], dtype=np.float64)


# 각 면: (정점 인덱스 4개, 바깥 방향 법선) — 정점은 바깥에서 볼 때 반시계
FACES = [
    ([0, 1, 2, 3], [0, 0, -1]),   # bottom
    ([4, 7, 6, 5], [0, 0, 1]),    # top
    ([0, 4, 5, 1], [0, -1, 0]),   # front (-y)
    ([2, 6, 7, 3], [0, 1, 0]),    # back (+y)
    ([1, 5, 6, 2], [1, 0, 0]),    # right (+x)
    ([0, 3, 7, 4], [-1, 0, 0]),   # left (-x)
]


def look_at(eye, target, up=(0, 0, 1)):
    """OpenCV 카메라 관례: x=오른쪽, y=아래, z=전방(장면 쪽)."""
    eye, target, up = np.array(eye, float), np.array(target, float), np.array(up, float)
    z = (target - eye); z /= np.linalg.norm(z)
    x = np.cross(z, up); x /= np.linalg.norm(x)
    y = np.cross(z, x); y /= np.linalg.norm(y)
    R = np.stack([x, y, z], axis=0)
    t = -R @ eye
    return R, t


def intrinsic_matrix(w, h, fov_deg):
    f = 0.5 * w / np.tan(np.deg2rad(fov_deg) / 2)
    return np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], dtype=np.float64)


def render_view(verts_world, K, R, t, texture, canvas_size=(IMG_W, IMG_H), bg=(210, 210, 210)):
    w, h = canvas_size
    canvas = np.full((h, w, 3), bg, dtype=np.uint8)

    verts_cam = (R @ verts_world.T).T + t  # (8,3)
    eye_world = -R.T @ t

    visible = []
    for idx, normal in FACES:
        center = verts_world[idx].mean(axis=0)
        view_dir = eye_world - center
        if np.dot(view_dir, normal) <= 0:
            continue  # back-face cull
        depth = verts_cam[idx, 2].mean()
        visible.append((depth, idx))

    visible.sort(key=lambda t_: t_[0])  # far (큰 z, 카메라 뒤는 이미 컬링됨 -> 가까운게 작은 값) 순서 주의
    # OpenCV 카메라 좌표계는 z가 카메라 전방이 아니라 우리가 world->cam 변환에서 임의 정의했으므로
    # painter's algorithm: depth 값이 "카메라로부터 먼 정도"를 반영하도록 verts_cam[...,2] 사용,
    # 큰 값(=더 앞쪽, 카메라에 가까움) 먼저 그릴지 확인 위해 아래서 proj 시 z>0만 사용.
    visible.sort(key=lambda t_: -t_[0])

    th, tw = texture.shape[:2]
    src_pts = np.array([[0, th - 1], [tw - 1, th - 1], [tw - 1, 0], [0, 0]], dtype=np.float32)

    for depth, idx in visible:
        pts_cam = verts_cam[idx]
        if np.any(pts_cam[:, 2] <= 0.01):
            continue  # 카메라 뒤/너무 가까움
        proj = (K @ pts_cam.T).T
        proj = proj[:, :2] / proj[:, 2:3]
        dst_pts = proj.astype(np.float32)

        H_mat = cv2.getPerspectiveTransform(src_pts, dst_pts)
        warped = cv2.warpPerspective(texture, H_mat, (w, h), flags=cv2.INTER_LINEAR,
                                      borderMode=cv2.BORDER_TRANSPARENT)
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillConvexPoly(mask, dst_pts.astype(np.int32), 255)
        canvas[mask > 0] = warped[mask > 0]

    return canvas


def render_orbit(size, out_dir, n_views=N_VIEWS, radius=0.75, height=0.18):
    out_dir.mkdir(parents=True, exist_ok=True)
    verts = box_vertices(size)
    K = intrinsic_matrix(IMG_W, IMG_H, FOV_DEG)
    texture = speckle_texture()

    cams = []
    for i in range(n_views):
        theta = 2 * np.pi * i / n_views
        eye = [radius * np.cos(theta), radius * np.sin(theta), height]
        R, t = look_at(eye, [0, 0, 0])
        img = render_view(verts, K, R, t, texture)
        fname = f"view_{i:03d}.png"
        cv2.imwrite(str(out_dir / fname), img)
        cams.append({"file": fname, "eye": eye})
    return K, cams


def main():
    true_volume = BOX_SIZE[0] * BOX_SIZE[1] * BOX_SIZE[2]
    print(f"합성 물체 생성: {BOX_SIZE[0]}m x {BOX_SIZE[1]}m x {BOX_SIZE[2]}m = 정답 부피 {true_volume*1000:.2f} L")

    K, cams = render_orbit(BOX_SIZE, OUT_DIR / "images")

    meta = {
        "box_size_m": BOX_SIZE,
        "true_volume_m3": true_volume,
        "true_volume_L": true_volume * 1000,
        "n_views": len(cams),
        "intrinsic": {"width": IMG_W, "height": IMG_H, "fx": K[0, 0], "fy": K[1, 1],
                       "cx": K[0, 2], "cy": K[1, 2]},
        "cameras": cams,
    }
    (OUT_DIR / "ground_truth.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"사진 {len(cams)}장 저장: {OUT_DIR/'images'}")
    print(f"정답 기록: {OUT_DIR/'ground_truth.json'}")


if __name__ == "__main__":
    main()
