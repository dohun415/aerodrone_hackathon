# aerodrone_hackathon

이 저장소에는 두 갈래의 작업이 있다.

| 갈래 | 위치 | 내용 |
|---|---|---|
| **ShoreSweep Planner** (이 브랜치에서 추가) | [`shoresweep_planner/`](shoresweep_planner/) | 기업 드론 라벨 + 정사영상 → 작업자용 해안쓰레기 **수거 계획** (인터랙티브 HTML) |
| Task4_verify 정합 파이프라인 | `pipeline/`, `data/`, `results/` | 위성·드론 영상 정합 실험 → 문서: [docs/README_task4_verify.md](docs/README_task4_verify.md) |

---

## ShoreSweep Planner — 해안쓰레기 수거 계획 프로그램

기업이 준 드론 라벨(GeoJSON: 쓰레기 위치·재질·면적)과 정사영상으로 **작업자용 수거 계획**(구역·순서·마대·시간·인원·일정)을 만든다.
결과 `수거계획.html` 은 그 자체가 계산기라서, 인원·하루 작업시간·수거 종류·이동 방식(도보/보트)·운반 방식·무게 기준을 바꾸거나
지도의 ★ 출발지를 끌면 브라우저 안에서 지형 최단경로부터 즉시 다시 계산된다.

```
기업 라벨(GeoJSON) + 정사영상 축소본
→ 무게 추정 (면적 × 채움률 × 두께 × 겉보기 밀도, 최소/대표/최대; 기업값 병기)
→ 정사영상 색으로 물·숲·맨땅 격자(10 m) → 물체·출발지 사이 최단경로 (물 불가, 숲 ×3, 보트 모드는 물 ×0.5)
→ 150 m 안 물체를 한 구역으로 → 구역 순회 (최단 이동 / 무게 우선)
→ 구역별 마대·작업 시간·2인 운반(NIOSH 23 kg) → 운반 방식 (현장 적치 / 들고 이동) → 하루 작업시간으로 일차 분할
→ 수거계획.html (인터랙티브) · 수거계획_지도.png (인쇄) · 수거계획.xlsx · csv · plan.json · 지형분류.png
```

### 실행

```bat
cd shoresweep_planner
pip install -r requirements.txt
python run.py            :: input/ 자료 → outputs/plan/수거계획.html (브라우저 자동 열림)
pytest tests -q          :: 테스트 8개
```

옵션 예: `python scripts\17_collection_plan.py --workers 4 --hours 6 --travel boat --carry carry --objective weight`

### 입력 자료 넣는 곳

`shoresweep_planner/input/` 에 넣는다 ([input/README.md](shoresweep_planner/input/README.md)).
기업 배포 자료(labels.json, crops/, 정사영상)는 공개 저장소라 올리지 않았으니 팀 드라이브에서 받아 넣으면 된다.

```
input/
  labels.json                 기업 GeoJSON 라벨 (필수)
  crops/*.jpg                 물체 사진 (선택)
  ortho/overview.jpg + .jgw   정사영상 축소본 + 월드파일, 또는 GeoTIFF (선택: 지형·드론 영상 오버레이)
  config.json                 현장 이름 · 출발지 · 좌표계 (선택, 문갑도 기본값 포함)
```

### 폴더

```
shoresweep_planner/
  run.py                        실행 (VS Code ▶)
  litter3d/classes.py           쓰레기 클래스, 겉보기 밀도표 (출처/가정값 표시)
  litter3d/plan.py              마대·톤백 적재량, NIOSH 23 kg
  litter3d/terrain.py           정사영상 색 → 물·숲·맨땅 격자 → 최단경로 (도보/보트)
  litter3d/collect.py           무게 추정 → 구역 → 순회 최적화 → 운반 방식 → 일차 분할 → xlsx/csv/json
  litter3d/collect_report.py    인터랙티브 HTML (브라우저 안 재계산) + 인쇄용 PNG
  scripts/17_collection_plan.py 명령줄 버전
  tools/extract_company_data.py (선택) ECW 원본 정사영상 → overview.jpg + .jgw (GDAL/QGIS 필요)
  tests/test_collect.py
```

### 문갑도 결과 (2026-10-01, 기본값 2명·4시간·도보·현장 적치)

42개 → 13구역, 대표 101 kg (범위 15–1,328), 마대 61장, 지형 경로 10.8 km, 5.6시간 → 2일. 보트 지원 9.6 km·5.2시간, 4명·6시간이면 1일.
기업 제공 무게 합은 1.3 kg(면적 × 고정계수로 보임) 이라 참고값으로만 쓴다. 숫자의 출처·가정값 구분은 [shoresweep_planner/README.md](shoresweep_planner/README.md) 참고.
