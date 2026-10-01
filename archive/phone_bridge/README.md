# phone_bridge — 웹에서 클릭 → 실제 폰 화면이 탭됨

드론 없이 먼저 검증하는 단계. 구조:

```
웹 대시보드 ──(클릭 좌표)──▶ FastAPI 서버 ──(tap 요청)──▶ WebDriverAgent(iPhone 내부) ──▶ 실제 터치
웹 대시보드 ◀──(화면 스트림)── FastAPI 서버 ◀──(반복 캡처)── iPhone
```

나중에 드론이 들어오면 `/stream`만 드론 RTMP 피드로 바꾸고, `/tap`에
"드론 영상 좌표 → 폰 화면 좌표" 변환 한 단계만 추가하면 됨 — 구조는
그대로 재사용.

## 지금 상태

- ✅ 서버(`server.py`) + 대시보드(`index.html`) 동작 확인 (기기 없이도 안 죽음, `/tap`이 WDA 없으면 502로 정상 실패)
- ⬜ 실제 iPhone 연결 — 아래 수동 단계 필요 (내가 원격으로 못 하는 부분)

## 해야 할 수동 단계 (순서대로)

### 1. iPhone을 USB 케이블로 맥에 물리 연결

지금은 Continuity Camera(무선)로만 잡혀있어서 기기 제어가 안 됨 —
케이블로 꽂고 폰 화면에 뜨는 **"이 컴퓨터를 신뢰하시겠습니까?"에 신뢰** 누르기.

확인:
```bash
idevice_id -l          # 기기 UDID가 떠야 함
ideviceinfo -k DeviceName
```

### 2. Xcode 활성화 (터미널에서 비밀번호 입력 필요 — 내가 못 함)

```bash
sudo xcode-select -s /Applications/Xcode.app
xcodebuild -version    # Xcode 16.x 나오면 성공
```

### 3. WebDriverAgent 빌드 + iPhone에 설치 (1회성)

```bash
git clone https://github.com/appium/WebDriverAgent.git
cd WebDriverAgent
./Scripts/bootstrap.sh
open WebDriverAgent.xcodeproj
```
Xcode에서:
- `WebDriverAgentRunner` 타겟 선택
- Signing & Capabilities에서 **본인 Apple ID(무료 계정도 가능)**를 Team으로 설정
- 연결된 iPhone을 destination으로 선택
- `Product → Test` (⌘U) 실행 — 이게 iPhone에 WDA를 설치하고 실행함
- 폰에서 "신뢰되지 않은 개발자" 경고가 뜨면 설정 → 일반 → VPN 및 기기 관리에서 신뢰

### 4. WDA 포트를 맥으로 포워딩 (USB 터널)

```bash
iproxy 8100 8100
```
(libimobiledevice에 포함된 도구, 이미 설치됨). 이 터미널은 계속 띄워둬야 함.

### 5. 실제 화면 해상도 확인 + 설정 반영

```bash
ideviceinfo | grep -i "ScreenWidth\|ScreenHeight\|ProductType"
```
`server.py`의 `PHONE_SCREEN_W`/`PHONE_SCREEN_H`를 WDA 기준 포인트 해상도로 맞추기
(WDA는 픽셀이 아니라 포인트 좌표를 씀 — `GET /session/<id>/window/size`로도 확인 가능).

### 6. 서버 실행 + 대시보드 접속

```bash
cd phone_bridge
source .venv/bin/activate
python server.py
```
브라우저에서 `http://localhost:8000` 접속 → 화면 클릭하면 실제 폰이 탭되는지 확인.

## 알려진 한계

- **화면 갱신 속도**: `idevicescreenshot`를 반복 호출하는 방식이라 1~2fps 수준.
  DJI Fly의 POI 탭 같은 용도엔 충분하지만, "실시간 영상"이라기엔 뚝뚝 끊김.
  더 매끄럽게 하려면 QuickTime 스타일의 진짜 화면 스트리밍(비공식, 더 복잡)으로
  나중에 교체 가능 — 지금은 동작 검증이 우선이라 가장 간단한 방법으로 구현.
- WDA 세션은 서버 재시작 시 새로 만들어짐 (전역 변수로 캐시만 함, 영속화 안 함).
