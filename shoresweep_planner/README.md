# ShoreSweep Planner — 해안쓰레기 수거 계획 프로그램 (드론대장 붕붕이)

2026 항공·드론 산업 수요 기반 해커톤. **ShoreSweep Planner** 는 기업이 준 드론 라벨(지도 위 쓰레기 위치·재질·면적)과 정사영상으로
**작업자용 수거 계획**(구역·순서·마대·시간·인원·일정)을 만든다. 결과 HTML 은 그 자체가 계산기라서
인원·시간·종류·이동 방식을 바꾸면 브라우저 안에서 즉시 다시 계산된다.

```
기업 라벨(GeoJSON) + 정사영상 축소본
→ 무게 추정 (면적 × 채움률 × 두께 × 겉보기 밀도, 최소/대표/최대)
→ 정사영상 색으로 물·숲·맨땅 격자(10 m) → 물체·출발지 사이 최단경로 (물 불가, 숲 ×3, 보트 모드는 물 ×0.5)
→ 150 m 안 물체를 한 구역으로 → 구역 순회 (최단 이동 / 무게 우선)
→ 구역별 마대·작업 시간·2인 운반 표시 → 운반 방식 (현장 적치 / 들고 이동) → 하루 작업시간으로 일차 분할
→ 수거계획.html (인터랙티브) · 수거계획_지도.png (인쇄) · 수거계획.xlsx · csv · plan.json
```

## 빠른 시작 (Windows, VS Code)

```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python run.py                 :: input/ 의 자료로 outputs/plan/수거계획.html 생성 → 브라우저 자동 열림
pytest tests -q
```

옵션이 필요하면:
```bat
python scripts\17_collection_plan.py --workers 4 --hours 6 --travel boat --carry carry --objective weight
python scripts\17_collection_plan.py --codes ROP,FIS --min-kg 1 --weight company
python scripts\17_collection_plan.py --input 다른현장폴더 --out outputs\다른현장 --depot 126.11,37.17 --depot-name 선착장
python scripts\17_collection_plan.py --help
```

## 폴더 구조

```
run.py                        실행 (VS Code ▶)
input/                        기업 자료를 넣는 곳 — input/README.md 참고
  labels.json                 기업 GeoJSON 라벨 (필수)
  crops/*.jpg                 물체 사진 (선택)
  ortho/overview.jpg + .jgw   정사영상 축소본 + 월드파일, 또는 GeoTIFF (선택: 지형·드론 영상 오버레이)
  config.json                 현장 이름 · 출발지 · 좌표계 (선택)
litter3d/
  classes.py                  쓰레기 클래스, 겉보기 밀도표 (출처/가정값 표시)
  plan.py                     마대·톤백·트럭 적재량, NIOSH 23 kg
  terrain.py                  정사영상 색 → 물·숲·맨땅 격자 → 8방향 최단경로 (걷기 환산 거리, 보트 모드)
  collect.py                  무게 추정 → 구역 → 순회 최적화 → 운반 방식 → 일차 분할 → xlsx/csv/json
  collect_report.py           인터랙티브 HTML (브라우저 안 다익스트라·재계산, ★ 출발지 끌기) + 인쇄용 PNG
  assets/leaflet.css          공개 링크용 HTML 에 인라인되는 지도 스타일
scripts/17_collection_plan.py 명령줄 버전 (run.py 가 이것을 부름)
tools/extract_company_data.py (선택) ECW 원본 정사영상 → input/ortho/overview.jpg + .jgw (GDAL/QGIS 필요)
tests/test_collect.py         테스트 (실제 데이터 없이 실행 가능)
outputs/                      결과 (git 제외)
```

## 결과 파일 (outputs/plan)

| 파일 | 내용 |
|---|---|
| 수거계획.html | 지도(위성 + 드론 정사영상 + 지형 경로 + 번호) · 설정 패널 · 작업 순서 카드(사진) · 준비물 · 표. 조건을 바꾸면 즉시 재계산 |
| 수거계획_공개용.html | 같은 페이지의 인터넷 링크(claude.ai 아티팩트 등) 용 변형. 외부 지도 타일 대신 드론 영상만, 인쇄·내려받기 없음 |
| 수거계획_지도.png | 인쇄용 지도 (기본 설정 기준) |
| 수거계획.xlsx · zones.csv · objects.csv · plan.json · summary.md | 표·데이터 (기본 설정 기준) |
| 지형분류.png | 물(파랑)·숲(초록)·맨땅(흰색) 격자 확인용 |

## 숫자의 신뢰도

- **출처 있음**: EPS 밀도 11–32 kg/m³ (Wikipedia Polystyrene), 개당 평균무게 (Andriolo et al. 2024), NIOSH 23 kg.
- **가정값**: 라벨 사각형 안 채움률·두께, 속 빈 플라스틱·로프·그물 겉보기 밀도, 걷기 속도, 작업 시간, 마대·운반 적재량,
  숲·보트 통행 배수, 승·하선 비용. `collect.py`·`terrain.py`·`classes.py` 에 "가정값" 으로 표시돼 있고 HTML 하단에도 적혀 있다.
- 기업 제공 무게(weight_kg) 는 면적 × 재질별 고정계수(스티로폼 0.012, 로프·어구 0.024, 플라스틱 0.020 kg/m²) 로 보여
  실측이 아니다. 계획은 우리 추정값을 쓰고 기업값은 참고로 함께 보여 준다 (`--weight company` 로 바꿀 수 있음).
- 결과는 검출 누락을 반영하지 않은 **최소 추정치**다. 현장에서 라벨에 없는 쓰레기도 함께 수거한다.

## 문갑도 결과 (2026-10-01, 기본값 2명·4시간·도보·현장 적치)

42개 → 13구역, 대표 101 kg (범위 15–1,328), 마대 61장, 지형 경로 10.8 km, 5.6시간 → 2일.
보트 지원 9.6 km·5.2시간, 4명·6시간이면 1일.

## 핵심 근거

- 국내 해양쓰레기 수거량 5년(2020–2024) 64만 9,749톤 중 해안쓰레기 50만 1,517톤(약 77 %) — 해양수산부 국회 제출자료, 뉴시스 2025-09-24
- 수거 현장은 무게(톤) 단위로 움직이지만 드론 연구는 개수·면적만 보고 — Andriolo & Gonçalves (2024)
- 무게를 알면 적절한 장비와 적재 차량으로 청소를 계획할 수 있다 — Andriolo et al. (2024)
- 격자 지도로 결과를 표준화 — Gonçalves et al. (2022)
