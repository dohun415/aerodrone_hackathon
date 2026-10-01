# Windows 실행 가이드

이 저장소는 원래 macOS에서 개발됐다. 이 문서는 **Windows에서 그대로
돌리기 위해 무엇이 막혔고 어떻게 풀었는지**를 기록한 것이다.
정합 로직 자체는 하나도 바꾸지 않았다 — 결과 숫자가 macOS와 같은지
전 단계를 실제로 돌려 대조했다(아래 [검증](#검증-macos-결과와-대조) 참고).

## 빠른 시작

```powershell
# 1) 설치 (Python 3.12 필요. 10~20분, PyTorch CUDA 다운로드가 대부분)
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1

# 2) 파이프라인 전체 실행
.\run_all.ps1
```

개별 단계만 돌리고 싶으면 원본 README의 명령을 쓰되, `python` 대신
가상환경의 인터프리터를 지정하고 **저장소 루트에서** 실행한다
(스크립트들이 `data/`·`results/`를 상대경로로 쓴다):

```powershell
$env:PYTHONUTF8 = "1"          # ⑥단계 이모지 출력에 필요
.\.venv\Scripts\python.exe pipeline\03_stable_mask.py --date 2026-09-16 --tile 52SBG
```

설치가 제대로 됐는지만 확인하려면:

```powershell
.\.venv\Scripts\python.exe check_env.py
```

---

## Windows에서 막혔던 것 6가지

### 1. GDAL — `pip install arosics`가 안 된다 ⭐ 최대 난관

②단계 AROSICS는 GDAL 파이썬 바인딩을 요구하는데, PyPI의 `gdal`은
**소스 배포(sdist)만** 있다. 즉 Windows에서는 C++ 컴파일러와 GDAL C
라이브러리가 있어야 빌드되는데, 둘 다 없으면 설치가 실패한다.
(macOS에서 `brew install gdal`로 풀었던 그 문제의 Windows 버전.)

**해결**: Christoph Gohlke의
[geospatial-wheels](https://github.com/cgohlke/geospatial-wheels)에서
미리 빌드된 `gdal-3.13.3-cp312-cp312-win_amd64.whl`을 받아 설치한다.
Windows 지리공간 패키지의 사실상 표준 배포처다. `setup_windows.ps1`이
현재 Python 버전에 맞는 wheel을 자동으로 골라 받는다.

> conda를 쓴다면 `conda install -c conda-forge gdal arosics`가 더
> 간단하다. 이 환경엔 conda가 없어서 pip + wheel 경로를 택했다.

rasterio(자체 GDAL 3.9.3 번들)와 이 GDAL 3.13.3을 한 venv에 같이 두면
DLL이 충돌할 수 있는데, 실제로 확인해보니 둘 다 정상 동작했다
(`pip check`도 통과).

### 2. PyTorch가 CPU 전용으로 깔린다

PyPI의 Windows용 `torch`는 **CPU 빌드**다(리눅스와 달리 CUDA가 안
들어있다). 그냥 `pip install -r requirements.txt` 하면 이 PC의
RTX 4060을 못 쓴다.

**해결**: NVIDIA GPU가 감지되면 PyTorch 공식 CUDA 인덱스에서 설치한다.

```powershell
pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu128
```

추가로 `pipeline/ai_matching/loftr_run.py`가 장치를 **`"mps"`(Apple
GPU)로 하드코딩**하고 있어서, Windows에서는 무조건 CPU로 떨어졌다.
`CUDA > MPS > CPU` 순으로 자동 선택하도록 고쳤다 — macOS에서는
예전과 똑같이 `mps`를 쓴다.

### 3. 한글 경로 때문에 좌표계가 조용히 틀어진다 ⚠️

이 저장소가 `C:\Users\user\Desktop\드론\...` 에 있어서 GDAL이 번들한
PROJ 데이터 경로에도 한글이 들어갔다. Windows용 PROJ는 이 경로를 열 때
유니코드를 제대로 처리하지 못해 `proj.db`를 **없는 것으로 취급**한다:

```
Warning 1: PROJ: proj_create_from_database: Cannot find proj.db
Warning 1: The definition of projected CRS EPSG:32652 ... is not the same
           as the one from the EPSG registry
```

에러가 아니라 **경고**라서 그냥 지나치기 쉽지만, EPSG 정의를 DB에서
못 읽고 GeoTIFF 키 값만으로 좌표계를 세운다는 뜻이라 재투영이 조용히
부정확해질 수 있다. 정합 파이프라인에서는 무시하면 안 되는 종류다.

**해결**: `pipeline/_compat.py`의 `ensure_ascii_proj_data()`가 PROJ
데이터를 ASCII 경로(`%LOCALAPPDATA%\aerodrone_proj_data`)로 한 번
복사하고 `PROJ_LIB`/`PROJ_DATA`가 그쪽을 보게 한다. `osgeo` import
**전에** 호출해야 해서 ②단계 맨 위에서 부른다.

> 근본 해결책은 저장소를 `C:\dev\aerodrone_hackathon` 같은 영문 경로로
> 옮기는 것이다. 그러면 이 함수는 아무 일도 하지 않고 지나간다.

### 4. LoFTR 가중치 다운로드가 SSL 오류로 죽는다

④단계 LoFTR 첫 실행에서:

```
URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED]
          certificate verify failed: unable to get local issuer certificate>
```

kornia는 LoFTR 사전학습 가중치를 체코 공대 서버(`cmp.felk.cvut.cz`)에서
받는데, 이 서버가 HTTPS로 리다이렉트하면서 쓰는 CA 체인이 **Windows
기본 인증서 저장소에는 없다**. macOS/Linux에서는 되는데 Windows에서만
막히는 이유가 이것이다. (pip는 certifi 번들을 쓰므로 멀쩡하다.)

**해결**: `ensure_ssl_certs()`가 `SSL_CERT_FILE`을 certifi 번들로
지정한다. 표준 `ssl`이 호출 시점에 이 환경변수를 읽으므로, 다운로드보다
먼저 부르기만 하면 된다.

### 5. cp949 인코딩 — 이모지에서 죽고 JSON이 깨진다

Windows 기본 인코딩은 cp949다. 그래서:

- ⑥단계가 출력하는 판정 이모지(🟢🟡🔴)는 cp949에 없어서
  `UnicodeEncodeError`로 죽는다.
- `write_text()`/`read_text()`가 인코딩 없이 쓰여 있어서, 결과 JSON이
  UTF-8이 아닌 cp949로 저장되고 맥에서 읽으면 깨진다.

**해결**: 모든 파일 입출력(12곳)에 `encoding="utf-8"`을 명시했고,
⑥단계는 `enable_utf8_stdout()`으로 콘솔 출력도 UTF-8로 돌린다.
`run_all.ps1`은 추가로 `PYTHONUTF8=1`을 세팅한다.

덤으로 `newline="\n"`도 지정했다. 안 그러면 Windows에서 돌릴 때마다
결과 JSON이 CRLF로 저장돼서, 내용은 똑같은데 **파일 전체가 바뀐 것처럼**
git diff에 뜬다. 맥 팀원과 같이 작업할 때 충돌 나기 딱 좋다.
(`.gitattributes`도 같은 이유로 추가했다.)

### 6. matplotlib 한글 폰트

`matplotlib.rcParams["font.family"] = "AppleGothic"` 이 4개 파일에
하드코딩돼 있었다. Windows엔 이 폰트가 없어서 그림의 한글이 전부
□□□로 나온다.

**해결**: `apply_korean_font()`가 설치된 폰트 중에서 고른다
(Windows 맑은 고딕 → macOS AppleGothic → Linux 나눔고딕 순).
**macOS 팀원 환경은 그대로 AppleGothic을 쓴다.**

---

## 그 밖에 고친 것

- **`pipeline/visualize.py`의 기존 버그** (Windows와 무관):
  `from baselines.sift_baseline import ...` 인데 폴더 이름은
  `ai_matching`이다. 폴더를 이름 바꾸면서 이 파일만 안 고친 것으로
  보인다 — 어느 OS에서든 `ModuleNotFoundError`로 죽는다. 고쳤다.
- **`.ps1` 파일은 UTF-8 BOM으로 저장**해야 한다. Windows PowerShell
  5.1은 BOM이 없으면 .ps1을 cp949로 읽어서, 한글 주석이 깨지며 파서
  에러가 난다.

## 새로 추가된 파일

| 파일 | 용도 |
|---|---|
| `setup_windows.ps1` | 설치 자동화 (venv → 핵심 라이브러리 → GDAL wheel → arosics → torch/kornia → itk) |
| `run_all.ps1` | 파이프라인 6단계 전체 실행 |
| `check_env.py` | 단계별로 필요한 패키지·GPU·한글폰트·데이터가 준비됐는지 점검 |
| `requirements-windows.txt` | Windows용 핵심 의존성 (원본과 다른 이유를 주석에 적어둠) |
| `pipeline/_compat.py` | 위 1·3·4·6번을 처리하는 플랫폼 호환 헬퍼 |
| `.gitattributes` | 개행 LF 통일 (맥/윈도우 혼용 시 diff 오염 방지) |

---

## 검증 — macOS 결과와 대조

Windows에서 전 단계를 실제로 돌려 원본 README에 기록된 숫자와 맞춰봤다.

| 단계 | 지표 | README(macOS) | Windows 실행 결과 |
|---|---|---|---|
| ② 전역보정 | AROSICS (영상 중앙) | 실패 | 실패 (동일) |
| ② 전역보정 | AROSICS (섬 위) | dx -4.4m, dy -8.6m, 85.2% | dx **-4.43m**, dy **-8.58m**, **85.15%** |
| ③ 마스킹 | NDWI vs RGB IoU | 0.33 | **0.3317** |
| ④ 정합(실제) | SIFT 인라이어 / RMSE | 32% / 4.2m | **32%** / **4.24m** |
| ④ 정합(실제) | LoFTR 인라이어 / RMSE | 76% / 14.2m | **75.9%** / **14.16m** |
| ④ 합성벤치 | SIFT 복원오차 | 0.51m | **0.506m** |
| ④ 합성벤치 | LoFTR 복원오차 | 1.19m | **1.225m** |
| ⑤ 국소보정 | 잔차 std | 0.1909 → 0.1906 | 0.1909 → **0.1903** |
| ⑥ 품질검증 | LoD (SIFT / LoFTR) | 23.9m / 35.3m | **23.9m** / **34.5m** |
| 시연 ④ | 10px 어긋남 가짜변화 | 23.4% → 0.0% | **23.39% → 0.00%** |
| ①' 시점보정 | 평지 SIFT RMSE | 5.13m → 2.68m | **5.13m → 2.67m** |
| ①' 시점보정 | 언덕 안/밖 인라이어율 | 47% / 95% (SIFT) | **44.8% / 94.7%** |

LoFTR·RANSAC은 난수를 쓰고 `itk-elastix`는 버전에 따라 미세하게 달라서
소수점 아래가 조금씩 다르지만, **결론이 바뀌는 차이는 없다.**

---

## 문제 해결

**`setup_windows.ps1`이 실행 자체가 안 될 때**
PowerShell 실행 정책 때문이다. `powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1`로 실행한다.

**`py -3.12`가 없다고 할 때**
[python.org](https://www.python.org/downloads/)에서 Python 3.12 설치.
`py -0p`로 설치된 버전을 확인할 수 있다. (3.13+는 GDAL/itk wheel이 아직
없을 수 있어 3.12를 권장한다.)

**GDAL wheel 자동 다운로드가 실패할 때**
[geospatial-wheels 릴리스](https://github.com/cgohlke/geospatial-wheels/releases)에서
`gdal-*-cp312-cp312-win_amd64.whl`을 직접 받아서:
```powershell
.\.venv\Scripts\python.exe -m pip install <받은파일.whl>
```

**GPU를 안 쓰는 것 같을 때**
`check_env.py`가 `LoFTR 실행 장치: cpu`로 나오면 CPU 빌드가 깔린 것이다.
`powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1 -Recreate`로
다시 설치한다. (GPU 없이도 동작은 한다 — LoFTR가 느릴 뿐이다.)

**`Cannot find proj.db` 경고가 계속 뜰 때**
저장소를 영문 경로(`C:\dev\aerodrone_hackathon`)로 옮기는 게 가장 확실하다.

**처음부터 다시 깔고 싶을 때**
```powershell
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1 -Recreate
```
