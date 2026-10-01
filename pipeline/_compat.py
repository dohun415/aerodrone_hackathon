"""
플랫폼 호환 헬퍼 (Windows / macOS / Linux 공용).

이 저장소는 원래 macOS에서 개발돼서 두 가지가 하드코딩돼 있었다:
  1) matplotlib 한글 폰트 "AppleGothic"  → Windows/Linux에 없음
  2) LoFTR 실행 장치 "mps"(Apple GPU)    → Windows의 NVIDIA CUDA를 못 씀

이 모듈은 그 두 가지를 실행 환경에 맞게 자동으로 골라준다. macOS에서
돌리면 예전과 똑같이 AppleGothic·mps를 쓰므로 팀원 환경은 그대로다.
"""
import sys

# 한글 폰트 후보 — 앞에서부터 "실제로 설치돼 있는 것"을 고른다.
#   Windows: 맑은 고딕(기본 내장), 굴림 / macOS: AppleGothic
#   Linux:   나눔고딕, Noto Sans CJK
_KOREAN_FONT_CANDIDATES = [
    "Malgun Gothic",      # Windows 기본 한글 폰트
    "AppleGothic",        # macOS
    "NanumGothic",
    "Noto Sans CJK KR",
    "Gulim",
    "Batang",
]


def apply_korean_font():
    """matplotlib에 이 환경에서 쓸 수 있는 한글 폰트를 설정한다.

    반환: 실제로 선택된 폰트 이름 (하나도 못 찾으면 None).
    """
    import matplotlib
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((f for f in _KOREAN_FONT_CANDIDATES if f in available), None)

    if chosen:
        matplotlib.rcParams["font.family"] = chosen
    else:
        print(
            "[경고] 한글 폰트를 찾지 못했습니다 — 그림의 한글이 □□□로 보일 수 있습니다.\n"
            "        Windows라면 보통 '맑은 고딕'이 기본 설치돼 있습니다. "
            "Linux라면 fonts-nanum 설치를 권합니다.",
            file=sys.stderr,
        )
    # 한글 폰트는 유니코드 마이너스 글리프가 없는 경우가 많아 축 눈금이 깨진다.
    matplotlib.rcParams["axes.unicode_minus"] = False
    return chosen


def pick_torch_device():
    """이 환경에서 가장 빠른 torch 장치를 고른다: CUDA > MPS > CPU.

    Windows + NVIDIA(예: RTX 4060)에서는 "cuda", macOS Apple Silicon에서는
    "mps", 둘 다 없으면 "cpu".
    """
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def enable_utf8_stdout():
    """Windows 콘솔(기본 cp949)에서 이모지(🟢🟡🔴) 출력 시
    UnicodeEncodeError로 죽는 것을 막는다. cp949에 없는 글자는
    UTF-8로 그대로 내보낸다."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def _is_ascii(p) -> bool:
    return str(p).isascii()


def ensure_ascii_proj_data(verbose=True):
    r"""Windows에서 저장소가 '한글이 든 경로'에 있을 때 생기는 PROJ 문제를 해결한다.

    증상:
        Warning 1: PROJ: proj_create_from_database: Cannot find proj.db
        Warning 1: The definition of projected CRS EPSG:32652 ... is not the
                   same as the one from the EPSG registry

    원인:
        이 저장소를 예를 들어 `C:\Users\user\Desktop\드론\...` 에 두면
        GDAL이 번들해 온 PROJ 데이터(proj.db)의 경로에도 한글이 들어간다.
        Windows용 PROJ는 이 경로를 열 때 유니코드를 제대로 처리하지 못해서
        proj.db를 "없는 것"으로 취급한다. 그러면 EPSG 정의를 DB에서 못 읽고
        GeoTIFF 키에 적힌 값으로만 좌표계를 세우기 때문에, 재투영이 조용히
        부정확해질 수 있다 — 경고라서 그냥 넘어가기 쉽지만 정합 파이프라인
        에서는 무시하면 안 되는 종류의 경고다.

    해결:
        PROJ 데이터를 ASCII로만 된 경로에 한 번 복사해 두고, PROJ_LIB /
        PROJ_DATA가 그쪽을 보게 한다. osgeo는 이 환경변수가 이미 설정돼
        있으면 덮어쓰지 않으므로, **`from osgeo import gdal` 이나
        `import arosics` 보다 먼저** 호출해야 한다.

    (근본 해결책은 저장소를 `C:\dev\aerodrone_hackathon` 처럼 영문 경로로
     옮기는 것이다. 그러면 이 함수는 아무것도 하지 않고 그냥 지나간다.)

    반환: 실제로 사용하게 된 PROJ 데이터 경로 (조치 불필요/불가 시 None)
    """
    import os
    import shutil
    import tempfile
    from importlib.util import find_spec
    from pathlib import Path

    if not sys.platform.startswith("win"):
        return None

    # 이미 누가 ASCII 경로로 지정해 뒀으면 그대로 둔다.
    existing = os.environ.get("PROJ_LIB") or os.environ.get("PROJ_DATA")
    if existing and _is_ascii(existing) and (Path(existing) / "proj.db").exists():
        return existing

    # osgeo를 import하지 않고 위치만 알아낸다 (import하면 PROJ_LIB이 먼저 박힌다).
    spec = find_spec("osgeo")
    if spec is None or not spec.origin:
        return None
    src = Path(spec.origin).parent / "data" / "proj"
    if not (src / "proj.db").exists():
        return None

    # 원래 경로가 이미 ASCII면 복사할 필요 없이 그대로 쓴다.
    if _is_ascii(src):
        os.environ.setdefault("PROJ_LIB", str(src))
        os.environ.setdefault("PROJ_DATA", str(src))
        return str(src)

    # 한글 경로 -> ASCII 캐시 위치로 복사
    candidates = [os.environ.get("LOCALAPPDATA"), tempfile.gettempdir(), r"C:\ProgramData"]
    base = next((c for c in candidates if c and _is_ascii(c)), None)
    if base is None:
        print(
            "[경고] PROJ 데이터를 복사할 ASCII 경로를 찾지 못했습니다. "
            r"저장소를 영문 경로(예: C:\dev\aerodrone_hackathon)로 옮기세요.",
            file=sys.stderr,
        )
        return None

    dst = Path(base) / "aerodrone_proj_data"
    try:
        if not (dst / "proj.db").exists():
            if verbose:
                print(f"[PROJ] 경로에 비ASCII 문자가 있어 PROJ 데이터를 복사합니다:\n"
                      f"       {src}\n    -> {dst}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst, dirs_exist_ok=True)
    except OSError as e:
        print(f"[경고] PROJ 데이터 복사 실패({e}). "
              "저장소를 영문 경로로 옮기면 해결됩니다.", file=sys.stderr)
        return None

    os.environ["PROJ_LIB"] = str(dst)
    os.environ["PROJ_DATA"] = str(dst)
    return str(dst)


def ensure_ssl_certs(verbose=False):
    """Windows에서 모델 가중치 다운로드가 SSL 오류로 실패하는 것을 막는다.

    증상 (④단계 LoFTR 첫 실행):
        urllib.error.URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED]
        certificate verify failed: unable to get local issuer certificate>

    원인:
        kornia는 LoFTR 사전학습 가중치를 cmp.felk.cvut.cz(체코 공대)에서
        받는데, 이 서버가 HTTPS로 리다이렉트하면서 쓰는 CA 체인이 Windows
        기본 인증서 저장소에는 없다. macOS/Linux에서는 되는데 Windows에서만
        막히는 이유가 이것. (pip는 certifi 번들을 쓰기 때문에 멀쩡하다.)

    해결:
        Python 표준 ssl이 참고하는 SSL_CERT_FILE을 certifi 번들로 지정한다.
        `ssl.create_default_context()`가 호출 시점에 이 환경변수를 읽으므로
        다운로드보다 먼저 호출하기만 하면 된다.
    """
    import os

    if os.environ.get("SSL_CERT_FILE"):
        return os.environ["SSL_CERT_FILE"]
    try:
        import certifi
    except ImportError:
        return None

    bundle = certifi.where()
    os.environ["SSL_CERT_FILE"] = bundle
    os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
    if verbose:
        print(f"[SSL] 인증서 번들을 certifi로 지정: {bundle}")
    return bundle
