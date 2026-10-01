# Task4_verify — 정합 파이프라인 실행 기록

팀 노션의
[「회의 정리 — 정합 실패 요인·해결·기준 & 시연 파이프라인」](https://app.notion.com/p/3eadbb7a73b1811c9c7afdb1dc84aa06)과
[「과제4 — 기업 배포자료 분석 & 프로젝트 전략」](https://app.notion.com/p/4-3e3dbb7a73b1819b976bee87cc15d242)에서
확정한 **6단계 정합 파이프라인**을 실제로 하나씩 돌려보고, 무엇이
되고 무엇이 안 되는지, 숫자로 기록한다. 팀원 누구나 이 저장소를
그대로 재현할 수 있게 각 단계를 독립 스크립트로 나눴다.

> ⚠️ **중요한 전제**: 아직 회사가 배포한 실제 SkySat 굴업도 영상
> 파일(`ortho_visual`, STAC 메타데이터)을 이 작업 환경에서 확보하지
> 못했다. 그래서 이 저장소의 모든 실험은 **공개 Sentinel-2 데이터로
> 파이프라인 자체의 타당성을 먼저 검증**한 것이다. 실제 SkySat
> 파일을 받으면 `pipeline/00_fetch_data.py` 대신 그 파일을 입력으로
> 넣기만 하면 나머지 단계는 그대로 적용된다. (전략 문서에 "출처:
> 기업 배포 자료/ 폴더"라고 돼 있으니, 이 폴더를 공유해주면 바로
> 이어서 실제 데이터로 재실행하겠음.)

## 이 문서를 보는 법

각 절이 파이프라인 한 단계에 대응한다. **무엇을 검증하려 했는지 →
어떻게 했는지(오픈소스/방법) → 실제로 돌린 결과 → 이게 무슨
의미인지** 순서로 적었다. 재현 명령어는 각 절 끝에 있다.

```
pipeline/
├─ 00_fetch_data.py            # 데이터 확보
├─ 01_drone_view_rectify.py    # ①' 드론 시점 보정 (경사→나딜 근사)
├─ 02_global_shift.py          # ② 전역 이동 보정
├─ 03_stable_mask.py           # ③ 수면·모래 마스킹
├─ ai_matching/                # ④ AI 정밀정합
│  ├─ sift_baseline.py         #    - 베이스라인(고전)
│  └─ loftr_run.py             #    - AI(딥러닝 조밀매칭)
├─ 05_local_correction.py      # ⑤ 국소 보정
├─ 06_quality_report.py        # ⑥ 품질 검증 (합격 기준 판정 + LoD)
├─ shift_sweep_demo.py         # 시연 화면 ④ "어긋남 슬라이더"
├─ make_synthetic_pair.py      # 정답을 아는 합성 벤치마크 생성
├─ run_synthetic_bench.py      # 합성 벤치마크 실행
├─ visualize.py                # 결과 그림 생성
└─ metrics.py                  # 공통 지표 계산
```

숫자로 "①좌표통일"에 해당하는 별도 스크립트는 없다 — `00_fetch_data.py`가
AOI를 모두 같은 좌표계(EPSG:32652)·같은 그리드로 받아오기 때문에
이 단계가 데이터 수집에 자연스럽게 포함돼 있다(아래 1절 참고).

---

## 0. 데이터 확보 — `00_fetch_data.py`

**검증할 것**: 계정 없이, 코드 몇 줄로 우리 대상지(굴업도 인근
125.87–126.06°E, 37.14–37.25°N) 위성영상을 실제로 받을 수 있는가.

**방법**: Microsoft Planetary Computer STAC API(`pystac-client` +
`planetary-computer`)로 Sentinel-2 L2A를 검색하고, `rasterio`의
윈도우 read로 AOI만 잘라 GeoTIFF로 저장. 시간차가 큰 두 시기
(**2019-09-18** vs **2026-09-16**, 7년차)를 각각 받아 RGB+NIR
4밴드를 확보.

**결과**: 성공. 두 시기 모두 구름 0% 근처 장면을 자동으로 찾아
1275×1726 픽셀(10m GSD) GeoTIFF로 저장됨 (`data/raw/`, 19MB).

**의미**: 회사가 준 SkySat 외에도, 이종 시기·이종 센서 비교용
"플랜B" 데이터를 확보하는 절차 자체가 자동화·재현 가능하다는 것을
확인. 전략 문서의 "5-1. 2번째 시기 영상 — 최우선" 항목 중
Sentinel-2 경로가 즉시 실행 가능함을 실증.

```bash
python pipeline/00_fetch_data.py --bands B04,B03,B02,B08
```

---

## ① 좌표·해상도 통일

`00_fetch_data.py`의 `save_aoi_clip()`이 `rasterio.warp.transform_bounds` +
윈도우 read로 이미 모든 장면을 하나의 좌표계(EPSG:32652)·격자에
맞춰 저장한다. 회사 실데이터(SkySat 0.5m)가 오면 `gdalwarp -t_srs
-tr`로 Sentinel-2(10m) 격자에 맞추거나 그 반대로 리샘플링하는
단계가 별도로 필요 — 아직 실행 못 함 (SkySat 파일 없음).

---

## ①' 드론 시점 보정 — `01_drone_view_rectify.py`

**문제의식**: 위성(SkySat)도 28.9° 경사촬영이지만 Planet이 자체
DEM으로 이미 정사보정해서 "위에서 본" 형태(`ortho_visual`)로
배포한다. 반면 드론 원본 사진은 이런 보정이 안 된 원근(perspective)
사진이라, 위성 정사영상과 드론 사진을 곧바로 LightGlue/LoFTR에
넣으면 "다른 곳이라서"가 아니라 "투영 방식이 달라서" 매칭이 잘 안
될 위험이 있다. **그래서 정합 전에 드론 사진을 위성과 같은 투영
(나딜/정사)으로 먼저 맞추는 전처리 단계**를 검증했다.

**두 가지 경로**:
1. **정석**: 겹치는 드론 사진 여러 장 → OpenDroneMap(SfM)으로 실제
   DSM을 복원해 정사영상 생성. 절벽·언덕의 기복변위까지 기하학적으로
   정확히 보정됨. 드론 사진을 여러 장 확보하면 이게 정답.
2. **이 스크립트(근사)**: 사진이 한두 장뿐이거나 ODM 돌리기 전에
   빠르게 확인하고 싶을 때, 드론 텔레메트리(짐벌 피치각·고도 — 트랙A
   SRT/EXIF 추출 계획과 연결됨)로 호모그래피 하나를 계산해 평면
   가정 하에 원근을 되돌린다. **평지에서만 정확**하고, 높이가 있는
   지형(개머리언덕·절벽)에는 기복변위가 남는다는 게 아래 실험의
   핵심 발견.

**검증 방법**: 아직 실제 드론 사진이 없어서, 위성 정사영상(이미
나딜)에 사다리꼴(keystone) 원근왜곡을 인위적으로 줘서 "드론이
찍었을 법한 오블리크 사진"을 합성 → 보정 전/후로 SIFT·LoFTR 정합
성능을 비교. 언덕이 있는 경우도 별도로 합성해서 한계를 확인.

**결과**:

| 시나리오 | 상태 | SIFT 인라이어 | SIFT RMSE | LoFTR 인라이어 | LoFTR RMSE |
|---|---|---|---|---|---|
| 평지 | 보정 전 | 99% | 5.13m | 97% | 11.61m |
| 평지 | **보정 후** | 100% | **2.68m** | 100% | **2.73m** |
| 언덕 포함 | 보정 전 | 82% | 9.50m | 91% | 12.72m |
| 언덕 포함 | 보정 후 | 89% | 7.62m | 96% | 4.21m |

**언덕 구역만 따로 보면** (전체 RANSAC 인라이어 비율에는 안 잡히는 부분):

| | SIFT | LoFTR |
|---|---|---|
| 언덕 안 인라이어율 (보정 후) | **47%** | **68%** |
| 언덕 밖 인라이어율 (보정 후) | 95% | 98% |

![드론 시점 보정](results/figures/06_drone_view_rectify.png)

**의미**: 평지에서는 시점 보정이 확실히 도움된다 — RMSE가 절반
가까이 줄었다. 그런데 전체 인라이어 비율만 보면 평지든 언덕이든
"보정 후 89~100%"로 꽤 좋아 보인다 — **이게 함정**이다. RANSAC은
전역 모델(호모그래피 하나)과 안 맞는 언덕 지역의 매칭점을 그냥
이상치로 버려버리기 때문에, 전체 통계에는 언덕에서의 실패가
가려진다. 언덕 구역만 따로 떼어 보면 인라이어율이 47~68%로 뚝
떨어져서 언덕 밖(95~98%)과 뚜렷하게 차이 난다 — **보정 후에도
남는다.**

이건 두 가지를 동시에 증명한다: ① 평면 가정 호모그래피 보정은
실제로 정합을 개선한다(평지에서), ② 그러나 굴업도의 개머리언덕·
절벽 같은 진짜 기복이 있는 지형에는 이 방법만으로는 부족하고,
**전역 RMSE만 보고하면 이 실패를 놓친다** — 회의록 "4장 지형별
정합 기준"이 지형마다 오차를 따로 집계해야 한다고 한 이유를 다시
한번 실증. 실제 언덕 지역은 결국 OpenDroneMap의 DEM 기반 정사보정
(또는 ⑤ 국소보정)이 맡아야 한다는 역할 분담이 명확해졌다.

```bash
python pipeline/01_drone_view_rectify.py --top_margin 0.22
```

> 🔧 **수정(2026-09-30)**: 위 실험은 "위성은 이미 완벽하게 정사보정된
> 기준"이라고 가정했는데, 이건 틀렸다. Planet 공식 사양서를 확인해보니
> SkySat 정사보정도 Intermap/NED/SRTM 같은 **외부 DEM(해상도 30~90m)**을
> 쓴다 — 촬영은 한 번(고정 각도)이어도 되는 이유가 "여러 각도로 찍어서
> 3D를 복원"하는 게 아니라 "이미 있는 지형 데이터를 가져다 쓰기"
> 때문이다. 문제는 이 DEM 해상도가 굴업해수욕장(폭 40m)보다 훨씬
> 성겨서, **위성 쪽도 절벽·언덕 부분엔 미보정 잔차가 남아있을 수
> 있다.** 게다가 드론은 ODM으로 완전히 독립된 자체 DSM을 만드는데,
> 이게 위성이 쓴 DEM과 다르면 둘 다 "각자는 정사보정됐다"고 해도
> 합쳤을 때 어긋난다. 더 일관된 방법: 드론·위성 양쪽에 **같은 외부
> DEM**(국토지리정보원 DEM — 전략 문서 5-2에 이미 있음)을 쓰는 것.
> 드론은 자체 DSM 대신 GPS·짐벌 자세 + 이 공유 DEM으로 직접
> 정사보정(위성의 RPC+DEM 방식과 동일한 원리)하고, 가능하면 Planet이
> 별도 제공하는 RPC로 SkySat 자체를 이 더 정밀한 국내 DEM으로
> 재정사보정하는 것도 고려할 만하다. 그래도 DEM 해상도·정확도
> 한계로 잔차는 남으므로, 결국 ⑤국소보정·⑥품질검증(LoD)이 이
> 잔차를 측정·처리하는 안전망 역할을 한다 — 회의록 "①줄이기→②재기→
> ③견디기" 구조가 애초에 이 가정 위에 설계된 것.

---

## ② 전역 이동 보정 — `02_global_shift.py`

**검증할 것**: 회의록의 "AROSICS Global"(GCR 0.17에서 오는 절대측위
오차 제거)을 실제로 돌릴 수 있는가.

**처음엔 막혔던 것 → 해결**: 이 macOS 환경은 Homebrew 자체가 깨져
있었다(`freetype`·`fontconfig`·`little-cms2`의 `/opt/homebrew/opt/*`가
심볼릭 링크가 아니라 이전 설치에서 남은 고아 디렉터리 상태 —
아마 예전에 비정상 종료된 brew 작업의 잔재). 그래서 `brew install
gdal`이 링크 단계에서 연쇄 실패했고, `pip install arosics`도
`gdal-config`를 못 찾아 설치가 안 됐다.

**해결 방법** (이 저장소·정합 로직과는 무관한, 이 컴퓨터의 Homebrew
자체를 고친 것):
```bash
# 고아 디렉터리(심볼릭 링크 아님)를 찾아서 지우고 재연결
for d in /opt/homebrew/opt/*; do
  [ -e "$d" ] && [ ! -L "$d" ] && echo "$d"
done
rm -rf /opt/homebrew/opt/freetype /opt/homebrew/opt/fontconfig /opt/homebrew/opt/little-cms2
brew link --overwrite freetype fontconfig little-cms2 numpy
brew install gdal   # 이제 끝까지 성공
pip install arosics # gdal-config를 찾아서 정상 설치
```

**결과 — 진짜 AROSICS로 재실행**:

| 실행 위치 | 결과 |
|---|---|
| 영상 중앙(기본값) | ❌ `No match found in the given window` |
| **섬(육지) 위치** (③단계 마스크로 찾은 좌표) | ✅ dx **-4.4m**, dy **-8.6m**, 신뢰도 **85.2%** |
| phase_cross_correlation (교차검증) | dx -3.8m, dy 9.4m |

**의미**: 이미지 중앙에서 AROSICS가 실패한 것 자체가 중요한
발견이다 — 우리 AOI는 98.8%가 바다(③단계 참고)라서 기본 매칭
윈도우가 특징점 없는 물 위에 놓이면 전역보정조차 안 된다. 매칭
윈도우를 섬 위로 옮기자마자 신뢰도 85%로 성공했고, 그 결과가
독립적인 다른 방법(phase_cross_correlation)과도 방향·크기가
비슷하게 나와 서로 교차검증됐다. **회의록 "4장 지형별 정합
기준"(안정 지형에서 기준점을 뽑아야 한다)이 이론이 아니라 실제로
전역보정 성공 여부를 가르는 조건이라는 걸 직접 확인**한 셈.
또한 두 방법이 준 절대 이동량(4~9m)은 Sentinel-2 L2A 공식 규격
정확도(<12m) 이내라서, 이 두 장면은 원래도 잘 정렬돼 있었다는
뜻이기도 하다 — ⑤단계 결과와도 일관됨.

```bash
# wp_x, wp_y는 육지 중심 map좌표 (03_stable_mask.py 실행 후 알 수 있음)
python pipeline/02_global_shift.py \
  --ref data/raw/s2_2019-09-18_52SBG_B04.tif \
  --mov data/raw/s2_2026-09-16_52SBG_B04.tif \
  --wp_x 232210.74 --wp_y 4119811.13
```

---

## ③ 수면·모래 마스킹 — `03_stable_mask.py`

**검증할 것**: 전략 문서의 제약① — "SkySat ortho_visual은 RGB뿐,
NIR이 없어 NDWI를 못 쓴다"가 실제로 얼마나 심각한 문제인지.

**방법**: 우리 Sentinel-2 데이터는 NIR(B08)이 있으므로, NDWI
마스크를 "정답"으로 두고, **NIR 없이 RGB만으로** 물을 추정하는
간단한 대안(HSV 채도 + Blue-Red 우세도, Otsu 자동 임계값)을 만들어
IoU로 직접 비교.

**결과**:

| 방법 | 물로 판정된 비율 | NDWI 대비 IoU |
|---|---|---|
| NDWI (NIR 사용, 정답) | 98.8% | — |
| RGB-only (회사 데이터와 동일 조건) | 32.8% | **0.33** |

![마스킹 비교](results/figures/04_mask_ndwi_vs_rgb.png)

**의미**: IoU 0.33은 낮다 — 시각적으로도 RGB-only 결과는 섬
윤곽을 제대로 못 잡고 노이즈가 많다. **전략 문서가 이미 내린 결론
("RGB 입력 딥러닝 수륙분할이 사실상 유일한 경로")이 옳다는 걸 직접
숫자로 확인**했다. 단순 색상 임계값으로는 부족하고, CAID
데이터셋으로 사전학습한 분할 모델이 필요하다는 근거가 생김.

```bash
python pipeline/03_stable_mask.py --date 2026-09-16 --tile 52SBG
```

---

## ④ AI 정밀정합 — `ai_matching/sift_baseline.py`, `loftr_run.py`

**검증할 것**: 필수요구사항 2번(정합)의 핵심. 텍스처가 적은
해안·수면에서 고전 기법(SIFT)과 딥러닝 조밀매칭(LoFTR)이 실제로
얼마나 차이 나는가.

### 실험 1 — 실제 다시기 (2019 vs 2026)

| 기법 | 매칭 수 | 인라이어 비율 | RMSE |
|---|---|---|---|
| SIFT+RANSAC | 25 | 32% | 4.2 m |
| LoFTR (kornia) | 144 | **76%** | 14.2 m |

### 실험 2 — 합성 벤치마크 (정답을 아는 상태, 120m/-70m 이동 + 0.8° 회전)

| 기법 | 인라이어 비율 | 복원 오차(평균) |
|---|---|---|
| SIFT+RANSAC | 100% | **0.51 m** |
| LoFTR (kornia) | 100% | 1.19 m |

**의미**: 텍스처 적은 실제 해안 장면에서는 LoFTR이 압도적으로
안정적(인라이어 76% vs 32%). 반대로 텍스처가 완전히 같은 합성
데이터에서는 SIFT가 더 정밀(0.51m vs 1.19m) — **"AI가 항상
좋다"가 아니라 "언제 어떤 기법을 쓸지"가 진짜 설계 포인트**라는
걸 두 실험을 나란히 놓고서야 알 수 있었다. LightGlue(회의록에서
"실무 1순위"로 지정)는 아직 미실행 — 다음 단계.

```bash
python pipeline/ai_matching/sift_baseline.py --src data/raw/s2_2019-09-18_52SBG_B04.tif --dst data/raw/s2_2026-09-16_52SBG_B04.tif
python pipeline/ai_matching/loftr_run.py --src data/raw/s2_2019-09-18_52SBG_B04.tif --dst data/raw/s2_2026-09-16_52SBG_B04.tif
python pipeline/make_synthetic_pair.py && python pipeline/run_synthetic_bench.py
```

---

## ⑤ 국소 보정 — `05_local_correction.py`

**검증할 것**: 회의록의 "AROSICS Local / Elastix"(기복변위처럼
영역마다 다르게 어긋나는 것을 격자 단위로 펴는 것)를 실제로 돌릴
수 있는가.

**방법**: AROSICS는 이제 설치돼 있지만(②단계 참고), AROSICS
Local은 격자 전체에 촘촘한 tie point가 필요해서 우리처럼 98.8%가
바다인 장면엔 안 맞다 — 대신 `itk-elastix`(순수 pip)로 B-스플라인
비강체 정합을 실행해 같은 역할을 확인했다.

**결과**: 보정 전후 잔차 표준편차가 0.1909 → 0.1906 (**0.1%만
감소**).

**의미**: 처음엔 "왜 거의 안 줄었지"라고 생각했지만, ②의 결과와
같이 놓고 보면 앞뒤가 맞는다 — 애초에 Sentinel-2 L2A는 이미 잘
정렬된 공식 산출물이라 격자 단위로 더 짤 게 거의 없다. 남은
잔차는 주로 **7년간의 실제 지표 변화**이지 정합 오차가 아니라는
뜻. (경사촬영 SkySat처럼 진짜 기복변위가 있는 데이터에서 이 국소
보정이 얼마나 효과 있는지는, 실제 SkySat 파일이 있어야 제대로
검증 가능.)

```bash
python pipeline/05_local_correction.py
```

---

## ⑥ 품질 검증 — `06_quality_report.py`

**검증할 것**: 회의록 "4-2. 정합 합격 기준" 표(RMSE, 인라이어
비율, 매칭점 공간분포 4분면)를 코드로 그대로 구현하고, LoD(최소
탐지 한계, `1.96×√(σ정합²+σ추출²)`)를 계산할 수 있는가.

**결과** (실제 2019 vs 2026 페어):

| 지표 | SIFT+RANSAC | LoFTR |
|---|---|---|
| RMSE | 0.70px 🟢 | 1.50px 🟡 |
| 인라이어 비율 | 35% 🟡 | 76.1% 🟢 |
| 4분면 분포 | TL0·TR4·BL0·BR10 🔴 | TL0·TR13·BL9·BR80 🔴 |
| **LoD** | **23.9 m** | **35.3 m** |

**의미**: 두 기법 모두 매칭점이 한쪽(BR, 섬이 있는 구역)에 쏠려서
**4분면 분포 기준은 실패**로 나왔다 — 이건 버그가 아니라, 이
AOI가 거의 다 바다라서 매칭 가능한 지점이 섬 하나뿐이기 때문. **회의록의
"지형별 정합 기준"(구조물·암반 우선, 수면·모래 제외)이 왜 필요한지
정확히 이 실패 사례가 보여준다** — 안정 지형이 부족한 장면에서는
합격 기준 자체를 지형 비율에 맞게 조정하거나, 안정 지형이 있는
타일을 골라야 한다는 실무적 결론.

```bash
python pipeline/06_quality_report.py
```

---

## 시연 화면 ④ "어긋남 슬라이더" ⭐ — `shift_sweep_demo.py`

회의록이 **가장 중요한 시연**으로 꼽은 화면. "지도 영상과 실제
사진이 미묘하게 어긋나 있어 AI가 정확히 판별하기 어렵다"는 기업의
문제를 그대로 재현해서 우리 파이프라인이 그 문제를 실제로 푸는지
보여준다.

**방법**: 진짜 변화가 없는 같은 영상에 인위적으로 0~10px 이동을
주고, **① 기존 방식(정합 없이 바로 비교)** vs **② 우리 방식(SIFT로
먼저 정합 후 비교)**의 "가짜 변화 면적 비율"을 비교.

**결과**:

![어긋남 슬라이더](results/figures/05_shift_sweep.png)

| 어긋남 | 기존 방식 가짜 변화 | 우리 방식 가짜 변화 |
|---|---|---|
| 0px | 0.0% | 0.0% |
| 5px | 16.9% | **0.0%** |
| 10px | 23.4% | **0.0%** |

**의미**: 기존 방식은 어긋남이 커질수록 가짜 변화가 선형적으로
폭증(0→23%)하지만, 우리 방식은 10px(≈100m)까지 밀어도 **가짜
변화가 전혀 생기지 않는다**. 이게 정확히 기업이 말한 "구글맵과
실제 사진의 미묘한 어긋남으로 AI가 정확히 판별하기 어렵다"는 문제
그 자체이고, 우리가 그걸 풀었다는 걸 숫자와 그래프로 보여주는
가장 강한 한 장.

```bash
python pipeline/shift_sweep_demo.py
```

---

## 현재 상황 요약 (2026-09-30 기준)

| 파이프라인 단계 | 상태 | 비고 |
|---|---|---|
| 데이터 확보 | ✅ 완료 | Sentinel-2 실증, SkySat 실파일 대기 |
| ① 좌표 통일 | ✅ 완료 | fetch 단계에 내장 |
| ①' 드론 시점 보정 | ✅ 완료(합성 검증) | 평지 개선 확인, 언덕 잔차 한계도 확인 — 실제 드론 사진 없음 |
| ② 전역 보정 | ✅ 완료 | 진짜 AROSICS 성공(섬 위치, 신뢰도 85%) + phase_cross_correlation 교차검증 |
| ③ 마스킹 | ✅ 완료 | NDWI vs RGB-only IoU 0.33 확인 |
| ④ AI 정밀정합 | 🟡 부분 완료 | SIFT·LoFTR 완료, LightGlue 미실행 |
| ⑤ 국소 보정 | ✅ 완료(대안 도구) | AROSICS Local은 우리 AOI(바다多)에 부적합, itk-elastix 사용 |
| ⑥ 품질 검증 | ✅ 완료 | 합격기준 표 + LoD 구현 |
| 시연 화면 ④ | ✅ 완료 | 핵심 결과, 그대로 발표 슬라이드로 사용 가능 |
| 시연 화면 ①②③⑤ | ⬜ 미착수 | Streamlit/Gradio 대시보드로 통합 필요 |
| 테이블 모형 시연 | ⬜ 미착수 | 물리적 모형 제작은 팀 작업 |
| 실제 SkySat 데이터 | ⬜ 미확보 | 기업 배포자료 폴더 공유 필요 |

## 다음에 할 일 (우선순위순)

1. **실제 SkySat 굴업도 파일 확보** — 있으면 이 파이프라인 전체를 그대로 재실행
2. LightGlue 추가 (kornia에 이미 있음, `ai_matching/lightglue_run.py`로 SIFT/LoFTR와 같은 패턴으로 추가하면 됨)
3. 시연 화면 ①②③ Streamlit 대시보드로 통합 (회의록 5-4)
4. 지형별(구조물/암반/평지/산지) 자동 분류 — 지금은 물/비물 이진 마스킹까지만 구현
5. ~~AROSICS 설치~~ — ✅ 해결됨 (Homebrew 고아 디렉터리 정리 후 정상 설치, ②단계 참고)
6. 드론 텔레메트리(SRT/EXIF 짐벌 피치각·고도) 추출 스크립트 — 실제
   드론 영상이 생기면 `01_drone_view_rectify.py`가 지금은 임의로
   가정하는 원근왜곡 강도(`--top_margin`) 대신 진짜 촬영 각도로
   호모그래피를 계산하도록 연결
7. 실제 드론 사진(여러 장) 확보 후 OpenDroneMap으로 진짜 DSM 기반
   정사영상 생성 — ①'단계가 예측한 "언덕에서는 한계가 있다"는 걸
   실제 지형으로도 확인

## 빠른 재현 (처음부터)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python pipeline/00_fetch_data.py --bands B04,B03,B02,B08
python pipeline/01_drone_view_rectify.py
python pipeline/02_global_shift.py
python pipeline/03_stable_mask.py
python pipeline/ai_matching/sift_baseline.py --src data/raw/s2_2019-09-18_52SBG_B04.tif --dst data/raw/s2_2026-09-16_52SBG_B04.tif
python pipeline/ai_matching/loftr_run.py --src data/raw/s2_2019-09-18_52SBG_B04.tif --dst data/raw/s2_2026-09-16_52SBG_B04.tif
python pipeline/05_local_correction.py
python pipeline/06_quality_report.py
python pipeline/make_synthetic_pair.py && python pipeline/run_synthetic_bench.py
python pipeline/shift_sweep_demo.py
python pipeline/visualize.py
```

## 사용한 오픈소스 (라이선스)

| 이름 | 용도 | 라이선스 |
|---|---|---|
| [rasterio](https://rasterio.readthedocs.io/) | GeoTIFF 읽기/쓰기, 좌표 변환 | BSD-3-Clause |
| [pystac-client](https://github.com/stac-utils/pystac-client) / [planetary-computer](https://github.com/microsoft/planetary-computer-sdk-for-python) | Sentinel-2 검색·다운로드 | Apache-2.0 / MIT |
| [AROSICS](https://github.com/GFZ/arosics) | 전역 이동 보정(②) | Apache-2.0 |
| [scikit-image](https://scikit-image.org/) | phase_cross_correlation(② 교차검증), Otsu(③) | BSD-3-Clause |
| [OpenCV](https://opencv.org/) | SIFT, RANSAC 호모그래피 | Apache-2.0 |
| [kornia](https://github.com/kornia/kornia) (LoFTR) | 딥러닝 조밀 매칭 | Apache-2.0 |
| [itk-elastix](https://github.com/InsightSoftwareConsortium/ITKElastix) | B-스플라인 국소 보정(⑤) | Apache-2.0 |
| [PyTorch](https://pytorch.org/) | kornia 백엔드 | BSD-3-Clause |

**Homebrew 이슈 해결됨** — 이전 버전 README는 이 macOS 환경의 Homebrew가
깨져 있어(`freetype`/`fontconfig`/`little-cms2` 고아 디렉터리) AROSICS
설치가 불가능하다고 기록했었다. 고아 디렉터리를 지우고 재연결한 뒤
`brew install gdal`이 정상 완료됐고, AROSICS도 정상 설치돼 ②단계는
이제 대안 도구가 아니라 정합 참고자료 페이지가 추천한 1순위 도구를
그대로 쓴다.

## 데이터 출처

Sentinel-2 L2A, ESA Copernicus, [Microsoft Planetary Computer](https://planetarycomputer.microsoft.com/) 경유 배포.
실제 회사 배포자료(Planet SkySat, 굴업도, 2026-08-17)는 아직 미반영.
