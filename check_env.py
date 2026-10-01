r"""
설치 검증 — 파이프라인을 돌리기 전에 6단계가 각각 필요한 것들이
이 환경에 제대로 깔렸는지 한 번에 확인한다.

    .\.venv\Scripts\python.exe check_env.py
"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "pipeline"))
from _compat import apply_korean_font, enable_utf8_stdout, pick_torch_device

enable_utf8_stdout()

# (모듈명, 쓰이는 단계, 없으면 치명적인가)
CHECKS = [
    ("rasterio",            "00 데이터 확보 / 전 단계 GeoTIFF 입출력", True),
    ("pystac_client",       "00 Sentinel-2 검색",                      True),
    ("planetary_computer",  "00 Sentinel-2 서명",                      True),
    ("cv2",                 "01/04 SIFT·호모그래피",                   True),
    ("skimage",             "02 phase_cross_correlation, 03 Otsu",     True),
    ("osgeo.gdal",          "02 AROSICS의 GDAL 바인딩",                False),
    ("arosics",             "02 전역 이동 보정",                       False),
    ("torch",               "04 LoFTR 백엔드",                         True),
    ("kornia",              "04 LoFTR",                                True),
    ("itk",                 "05 국소 보정(elastix)",                   False),
    ("matplotlib",          "그림 생성",                               True),
    ("torchvision",         "07/08 변화탐지 (transformers 의존)",      False),
    ("datasets",            "07 LEVIR-CD+ 내려받기",                   False),
    ("transformers",        "08 AdaptFormer 변화탐지 모델",            False),
    ("einops",              "08 AdaptFormer 모델 코드",                False),
]

def main():
    print(f"Python {sys.version.split()[0]}  ({sys.executable})\n")

    fail_hard = []
    for name, stage, required in CHECKS:
        try:
            mod = importlib.import_module(name)
            ver = getattr(mod, "__version__", "")
            print(f"  [OK]   {name:<20} {ver:<12} {stage}")
        except Exception as e:
            tag = "[없음]" if not required else "[실패]"
            print(f"  {tag} {name:<20} {'':<12} {stage}")
            print(f"         -> {type(e).__name__}: {e}")
            if required:
                fail_hard.append(name)

    # GPU
    print()
    try:
        import torch
        dev = pick_torch_device()
        print(f"  LoFTR 실행 장치: {dev}")
        if dev == "cuda":
            print(f"  GPU: {torch.cuda.get_device_name(0)}  (torch {torch.__version__})")
        elif dev == "cpu":
            print("  (GPU 미사용 — LoFTR가 느립니다. NVIDIA GPU가 있다면 "
                  "setup_windows.ps1을 다시 실행해 CUDA 빌드를 설치하세요.)")
    except Exception as e:
        print(f"  torch 확인 실패: {e}")

    # 한글 폰트
    font = apply_korean_font()
    print(f"  matplotlib 한글 폰트: {font or '못 찾음 (그림의 한글이 깨집니다)'}")

    # 데이터
    raw = Path("data/raw")
    tifs = sorted(raw.glob("*.tif")) if raw.exists() else []
    print(f"  data/raw GeoTIFF: {len(tifs)}개")
    if not tifs:
        print("  (없으면 `python pipeline/00_fetch_data.py --bands B04,B03,B02,B08` 로 내려받으세요.)")

    print()
    if fail_hard:
        print(f"필수 패키지 누락: {', '.join(fail_hard)} — setup_windows.ps1 을 다시 실행하세요.")
        return 1
    print("필수 패키지 모두 정상.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
