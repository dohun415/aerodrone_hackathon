"""
폰 화면 미러링 + 원격 탭 브릿지 (macOS 기본 기능 버전)

Xcode·WebDriverAgent·ADB·추가 하드웨어 전부 불필요. macOS의
"iPhone 미러링"(Sequoia+ 기본 앱) 창을 화면 캡처하고, 그 창 좌표를
cliclick으로 클릭하면 실제 폰 터치로 전달된다는 걸 직접 검증함.

사전 준비 (1회성, 전부 사람이 GUI로):
1. 맥에서 "iPhone 미러링" 앱 실행 → 폰 잠그고 "연결" 클릭
2. 시스템 설정 → 개인정보 보호 및 보안 → 화면 기록 / 손쉬운 사용
   → 이 서버를 실행하는 앱(터미널 등) 허용
3. brew install cliclick

두 가지 화면:
- /stream      : 폰 화면 전체 (상태바·DJI Fly UI 포함) — 디버그/보정용
- /drone_view  : 그 중 "드론 영상이 실제로 나오는 영역"만 잘라서 확대 —
                 대시보드 메인 화면으로 쓰는 것. DRONE_VIEW_CROP으로
                 잘라낼 영역을 지정한다(전체 화면 대비 0~1 비율).

좌표 변환 2단계:
  대시보드 클릭(드론뷰 기준 0~1)
    → DRONE_VIEW_CROP 적용해서 "전체 폰 화면 기준 0~1"로 환산
    → 미러링 창 위치+크기를 곱해서 "맥 화면 절대좌표"로 환산
    → cliclick

실제 드론 화면(DJI Fly의 비행 화면)을 보면서 DRONE_VIEW_CROP 값을
눈대중으로 보정하면 된다 — 기본값은 상태바/하단 메뉴를 대략 제외한
값으로 잡아뒀다.
"""
import asyncio
import io
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from PIL import Image

app = FastAPI()

MIRROR_PROCESS_NAME = "iPhone Mirroring"
SCREENSHOT_TMP = Path("/tmp/phone_bridge_frame.png")

# 폰 화면 전체 중 "드론 영상이 실제로 나오는 영역" (x0, y0, x1, y1), 0~1 비율.
# DJI Fly 비행 화면을 보면서 상태바/상단바/하단 컨트롤바를 뺀 영역으로 맞추면 됨.
# 지금은 기본값(대략 추정) — 실제 비행 화면 캡처해서 조정 필요.
DRONE_VIEW_CROP = (0.0, 0.08, 1.0, 0.85)


def get_mirror_window_bounds() -> Optional[Tuple[int, int, int, int]]:
    script = f'''
    tell application "System Events"
        tell process "{MIRROR_PROCESS_NAME}"
            set winPos to position of window 1
            set winSize to size of window 1
            return (item 1 of winPos as string) & "," & (item 2 of winPos as string) & "," & (item 1 of winSize as string) & "," & (item 2 of winSize as string)
        end tell
    end tell
    '''
    try:
        out = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=5, check=True
        ).stdout.strip()
        x, y, w, h = map(int, out.split(","))
        return x, y, w, h
    except Exception as e:
        print(f"[get_mirror_window_bounds] 실패: {e}")
        return None


def bring_mirror_to_front():
    subprocess.run(
        ["osascript", "-e", f'tell application "{MIRROR_PROCESS_NAME}" to activate'],
        capture_output=True, timeout=5,
    )


def grab_full_frame_bytes() -> Optional[bytes]:
    bounds = get_mirror_window_bounds()
    if not bounds:
        return None
    x, y, w, h = bounds
    try:
        subprocess.run(
            ["screencapture", "-x", f"-R{x},{y},{w},{h}", str(SCREENSHOT_TMP)],
            check=True, capture_output=True, timeout=5,
        )
        return SCREENSHOT_TMP.read_bytes()
    except Exception as e:
        print(f"[grab_full_frame_bytes] 실패: {e}")
        return None


def crop_to_drone_view(png_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(png_bytes))
    w, h = img.size
    x0, y0, x1, y1 = DRONE_VIEW_CROP
    box = (int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))
    cropped = img.crop(box)
    out = io.BytesIO()
    cropped.save(out, format="PNG")
    return out.getvalue()


async def _mjpeg(frame_fn):
    boundary = b"--frame"
    while True:
        raw = grab_full_frame_bytes()
        if raw:
            frame = frame_fn(raw) if frame_fn else raw
            yield boundary + b"\r\nContent-Type: image/png\r\n\r\n" + frame + b"\r\n"
        await asyncio.sleep(0.5)


@app.get("/stream")
async def stream():
    """폰 화면 전체 (디버그·좌표 보정용)."""
    bring_mirror_to_front()
    return StreamingResponse(_mjpeg(None), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/drone_view")
async def drone_view():
    """드론 영상 영역만 잘라서 확대 — 대시보드 메인 화면."""
    bring_mirror_to_front()
    return StreamingResponse(_mjpeg(crop_to_drone_view), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/window_bounds")
async def window_bounds():
    bounds = get_mirror_window_bounds()
    if not bounds:
        return JSONResponse({"ok": False, "error": "미러링 창을 찾을 수 없음"}, status_code=502)
    x, y, w, h = bounds
    return {"ok": True, "x": x, "y": y, "width": w, "height": h, "drone_crop": DRONE_VIEW_CROP}


def _do_tap(rel_x_full: float, rel_y_full: float):
    """폰 화면 전체 기준 0~1 좌표를 맥 절대좌표로 바꿔 cliclick."""
    bounds = get_mirror_window_bounds()
    if not bounds:
        return None, "미러링 창을 찾을 수 없음"
    x, y, w, h = bounds
    abs_x = round(x + rel_x_full * w)
    abs_y = round(y + rel_y_full * h)
    try:
        subprocess.run(["cliclick", f"c:{abs_x},{abs_y}"], check=True, capture_output=True, timeout=5)
        return (abs_x, abs_y), None
    except Exception as e:
        return None, str(e)


@app.post("/tap")
async def tap(request: Request):
    """폰 화면 전체(/stream) 기준 상대좌표로 탭. body: {"rel_x":0~1, "rel_y":0~1}"""
    body = await request.json()
    result, err = _do_tap(body["rel_x"], body["rel_y"])
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=502)
    return {"ok": True, "x": result[0], "y": result[1]}


@app.post("/drone_tap")
async def drone_tap(request: Request):
    """드론 영상 영역(/drone_view) 기준 상대좌표로 탭.
    DRONE_VIEW_CROP을 적용해서 전체 화면 기준 좌표로 먼저 환산한다."""
    body = await request.json()
    rx, ry = body["rel_x"], body["rel_y"]
    x0, y0, x1, y1 = DRONE_VIEW_CROP
    full_rel_x = x0 + rx * (x1 - x0)
    full_rel_y = y0 + ry * (y1 - y0)
    result, err = _do_tap(full_rel_x, full_rel_y)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=502)
    return {"ok": True, "x": result[0], "y": result[1], "full_rel": [full_rel_x, full_rel_y]}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return Path(__file__).with_name("index.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
