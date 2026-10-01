# aerodrone_hackathon — 해안쓰레기 드론 조사 · 무게 추정 · 수거계획

지자체가 해안쓰레기를 치우려면 **어디에, 얼마나(무게), 몇 대의 트럭과 몇 명이**
필요한지 미리 알아야 한다. 위성은 광역은 보지만 작은 쓰레기와 부피를 못 보고,
기업이 지금 쓰는 무게(면적 × 고정계수)는 실제보다 수십 배 작게 나온다.
이 레포는 그 사이를 드론과 소프트웨어로 메운다.

## 전체 흐름

```
① 어디를 날지 고르기      위성/과거 조사로 쓰레기 밀집 구간에 우선순위 (C)
   → 배터리 예산 안에서 우선 구간을 도는 경로       path_planning/hotspot_route.py
② 고른 구간을 전수 촬영    지그재그 커버리지 경로 (A)  path_planning/coverage.py
③ 탐지 · 위치 · 3D · 무게  영상 → 픽셀광선 위치 → 부피 → 무게(대표/최대)   litter/
④ 수거 작업계획           구역 · 순서 · 마대 · 인원 · 일정 대시보드       shoresweep_planner/
```

검증 도구: 정량 시뮬레이터 `litter/sim_ortho.py`(재현율·비행거리),
실제 비행 다이나믹스 확인 `ros_sim/`(PX4 SITL), 밀집 구간 근거 `hotspot/`.

## 폴더 구성과 출처

```
path_planning/        ①② 핫스팟 우선 경로 + 커버리지 경로
hotspot/              ①  밀집 구간 근거 실험
litter/               ③  탐지·위치·3D·무게 + 정량 시뮬레이터     (coastal 브랜치 원본)
shoresweep_planner/   ④  수거계획 대시보드                     (shoresweep 브랜치 원본)
ros_sim/              검증: 경로를 PX4 SITL로 비행
docs/                 인수인계·결과 문서, 발표 그림              (coastal 브랜치 원본)
scripts/              기업 라벨 분석
data/company/         기업 1차 데이터 (git 제외)
```

| 폴더 | 역할 | 출처 |
|---|---|---|
| `path_planning/` | ① 핫스팟 우선 경로(오리엔티어링), ② 커버리지 경로 | 이 레포 |
| `hotspot/` | 밀집 구간이 실제로 존재하고 시간이 지나도 유지되는지 검증 (하와이 항공조사, NOAA MDMAP) | 이 레포 |
| `litter/` | ③ 탐지·위치·3D 부피·무게 8단계 파이프라인 + 정량 시뮬레이터 | `origin/feature/coastal-litter-pipeline` |
| `shoresweep_planner/` | ④ 수거계획 인터랙티브 대시보드 (지형 최단경로 포함) | `origin/feature/shoresweep-planner` |
| `ros_sim/` | 경로가 실제 비행 컨트롤러로 날 수 있는지 PX4 SITL로 확인 | 이 레포 |
| `docs/` | 인수인계·결과정리·방향정리 문서, 발표 그림 | `origin/feature/coastal-litter-pipeline` |
| `scripts/analyze_labels.py` | 기업 라벨의 `weight_kg`가 면적×고정계수임을 확인 | 이 레포 |
| `data/company/` | 기업 1차 데이터(문갑도). **git 제외** — 팀 공유 폴더에서 받아 둔다 | 기업 제공 |

`litter/`, `docs/`, `shoresweep_planner/`는 각 브랜치의 파일을 **구조·내용 그대로**
가져온 것이다(포크 아님). 수정이 필요하면 원 브랜치에서 고치고 다시 가져온다.
예외로 `docs/핫스팟_우선경로_발표정리.md`는 브랜치에 없는 이 레포 쪽 문서다.

### 범위에서 뺀 이전 작업

비행 중 이탈·선회 경로(2차 비행), 웹 클릭 → 폰 탭 브릿지, 합성 상자 3D 부피 검증은
이번 방향에서 제외해 삭제했다. 필요하면 커밋 `ef84d02`의 `archive/`에서 꺼낼 수 있다.

## 실행

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# ③ 탐지~수거계획 8단계 (실데이터 전 합성 데이터로 확인)
python -m litter synth --out data/litter_synth
python -m litter run --images data/litter_synth/images --labels data/litter_synth/labels_coco.json \
  --weights data/litter_synth/weights.csv --telemetry data/litter_synth/telemetry.csv \
  --dsm data/litter_synth/dsm.tif --eval --out results/litter_synth_run

# ④ 수거계획 대시보드
cd shoresweep_planner && python run.py && python -m pytest tests -q
```

GPU·학습 가중치·원본 영상이 필요한 단계(YOLO 학습, COLMAP 조밀복원, SAM2)는
`docs/HANDOFF_세션인수인계.md`의 경로와 명령을 따른다.

### 이 레포에서 확인한 실행 결과 (2026-10-02)

- `shoresweep_planner` 테스트 **9개 전부 통과**
- `litter run --eval` 합성 데이터(물체 150) **8단계 전체 정상 종료**
  - 위치 오차 중앙값: 드론 GPS 23.2 m → 화면 중앙 17.9 m → **픽셀광선 2.0 m**
  - 무게 물체오차 중앙값: 개수×14g 96% → 학습 2D+3D **30%**, ≥23 kg 탐지 100%
- `hotspot_route` 동작 확인 (임의 40구간, 전체 순회의 30% 예산으로 가치 27% 방문)

## 선행 데이터 분석 (문갑도 1차 데이터)

배치는 `litter/`(인수인계 문서 2장)가 기대하는 경로를 따른다.

| 경로 | 내용 |
|---|---|
| `data/company/MGD_labels.json` | GeoJSON 42건 — 재질·면적·`weight_kg` (원본 이름 `MGD_쓰레기.json`) |
| `data/company/ortho/7_2_문갑도.ecw` | 정사영상 771 MB, 3.02 cm/px. 이 맥 환경에선 못 열었고, coastal 브랜치에서 Windows QGIS GDAL로 `MGD.tif` 변환에 성공함 |
| `data/company/crops/` | 쓰레기 1건당 크롭 42장 |

**`weight_kg`는 실측이 아니라 면적 × 재질별 고정계수다** (`scripts/analyze_labels.py`).

| 재질 | 개수 | weight/area (kg/m²) | 분산 |
|---|---|---|---|
| STY(스티로폼) | 37 | 0.01199 | 거의 0 |
| ROP(로프) | 3 | 0.02400 | 거의 0 |
| FIS(어망) | 1 | 0.02400 | — |
| PLA(플라스틱) | 1 | 0.02000 | — |

이 값으로 수거계획을 짜면 문갑도 42건이 **1.3 kg**, 겉보기밀도로 계산하면
**101 kg**이 나온다 (`shoresweep_planner/README.md`). 이게 이 프로젝트의 출발점이다.

또 크롭은 정사영상 한 장에서 자른 패치라 시차가 없어서 이 데이터만으로는
3D 복원이 안 된다. 3D 부피는 자체 드론 영상(송도 0007·0010)으로 검증했다.

```bash
python3 scripts/analyze_labels.py
```
