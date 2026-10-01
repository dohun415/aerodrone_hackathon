"""
폰 화면 미러링 + 원격 탭 브릿지.

구조:
  웹 대시보드 ── (클릭 좌표) ──▶ 이 서버 ── (WDA tap 요청) ──▶ WebDriverAgent(iPhone 위에서 실행) ──▶ 실제 탭
  웹 대시보드 ◀── (MJPEG 스트림) ── 이 서버 ◀── (idevicescreenshot 반복 호출) ── iPhone

나중에 드론이 생기면: 이 서버의 /stream을 드론 RTMP 피드로 바꾸고,
/tap에 들어오는 좌표를 "드론 영상 좌표 → 폰 화면 좌표" 변환만 추가하면
구조는 그대로 재사용된다 (사용자가 설명한 "추후 드론 주소 꽂기" 단계).
"""
import asyncio
import io
import subprocess
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

app = FastAPI()

# ── 설정 (환경에 맞게 조정) ─────────────────────────────────
WDA_URL = "http://localhost:8100"  # iproxy로 iPhone의 WDA 포트를 로컬로 포워딩한 주소
PHONE_SCREEN_W = 1170  # iPhone 실제 화면 해상도(포인트 단위, WDA 기준) — 기종에 맞게 수정
PHONE_SCREEN_H = 2532
SCREENSHOT_TMP = Path("/tmp/phone_bridge_frame.png")

_wda_session_id = None


# ── 화면 스트림 (idevicescreenshot 반복 호출 → MJPEG) ──────
def grab_frame() -> Optional[bytes]:
    """idevicescreenshot으로 현재 폰 화면 한 장을 찍어 바이트로 반환.
    기기가 USB로 연결·신뢰되어 있어야 동작한다."""
    try:
        subprocess.run(
            ["idevicescreenshot", str(SCREENSHOT_TMP)],
            check=True, capture_output=True, timeout=5,
        )
        return SCREENSHOT_TMP.read_bytes()
    except Exception as e:
        print(f"[grab_frame] 실패: {e}")
        return None


async def mjpeg_generator():
    boundary = b"--frame"
    while True:
        frame = grab_frame()
        if frame:
            yield (
                boundary + b"\r\n"
                b"Content-Type: image/png\r\n\r\n" + frame + b"\r\n"
            )
        await asyncio.sleep(0.3)  # idevicescreenshot가 느려서(~0.5~1s) 과도한 폴링은 의미 없음


@app.get("/stream")
async def stream():
    return StreamingResponse(
        mjpeg_generator(), media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/screen_size")
async def screen_size():
    return {"width": PHONE_SCREEN_W, "height": PHONE_SCREEN_H}


# ── 탭 전달 (웹 클릭 → WebDriverAgent → 실제 터치) ─────────
async def ensure_wda_session() -> str:
    global _wda_session_id
    if _wda_session_id:
        return _wda_session_id
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{WDA_URL}/session", json={"capabilities": {}})
        r.raise_for_status()
        _wda_session_id = r.json()["value"]["sessionId"]
        return _wda_session_id


@app.post("/tap")
async def tap(request: Request):
    """body: {"x": <폰 화면 x좌표>, "y": <폰 화면 y좌표>}
    좌표는 이미 PHONE_SCREEN_W/H 기준으로 변환된 값이어야 한다
    (프론트엔드에서 화면에 표시된 이미지 크기 대비 비율로 스케일링)."""
    body = await request.json()
    x, y = body["x"], body["y"]
    try:
        session_id = await ensure_wda_session()
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{WDA_URL}/session/{session_id}/wda/tap/0",
                json={"x": x, "y": y},
            )
            r.raise_for_status()
        return JSONResponse({"ok": True, "x": x, "y": y})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return Path(__file__).with_name("index.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
