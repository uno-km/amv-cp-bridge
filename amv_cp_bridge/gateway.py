# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
OpenAI-Compatible REST API Gateway & Real-Time Cyber Telemetry Dashboard for amv-cp-bridge
FastAPI 기반 /v1/chat/completions, /v1/models 및 실시간 모니터링 /dashboard를 제공합니다.
"""

import sys
import os
import time
import uuid
import json
import asyncio
import base64
import re
import mimetypes
from pathlib import Path
from typing import List, Optional, Dict, Any, Union, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, RedirectResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from collections import defaultdict

from ._version import __version__
from .engine import CopilotEngine, event_bus
from .telemetry_db import telemetry_db

# --- Rate Limiter (per-IP, token bucket) ---
_RATE_LIMIT_RPM = int(os.environ.get("COPILOT_RATE_LIMIT_RPM", "30"))

class _RateLimiter:
    def __init__(self, rpm: int = _RATE_LIMIT_RPM):
        self._rpm = rpm
        self._window = 60.0
        self._hits: Dict[str, list] = defaultdict(list)

    def is_allowed(self, client_ip: str) -> bool:
        now = time.time()
        bucket = self._hits[client_ip]
        bucket[:] = [t for t in bucket if now - t < self._window]
        if len(bucket) >= self._rpm:
            return False
        bucket.append(now)
        return True

_rate_limiter = _RateLimiter()

app = FastAPI(
    title="amv-cp-bridge OpenAI Gateway & Dashboard",
    version=__version__,
    description="Universal M365 Copilot AI Bridge with Zero-Leak Lifecycle & Real-Time Telemetry"
)

ALLOWED_ORIGINS = [
    "http://127.0.0.1:11500",
    "http://localhost:11500",
    "http://127.0.0.1:8089",
    "http://localhost:8089",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"^chrome-extension://.*$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

engine = CopilotEngine()


# ── 소스 감지 ─────────────────────────────────────────────────────────────
_SOURCE_MAP = {
    # User-Agent 키워드 → client_app 값
    "claude-desktop":   "claude-desktop",
    "claude desktop":   "claude-desktop",
    "antigravity":      "antigravity",
    "cursor/":          "cursor",
    "cursor ":          "cursor",
    "whale":            "whale",
    "amv-cp-bridge-cli":"cli",
}

def _detect_source(request: Request) -> tuple[str, str, str]:
    """(source, client_app, client_version) 반환.
    source:     'api' | 'mcp:claude' | 'mcp:cursor' | 'mcp:antigravity' | 'extension' | 'cli'
    client_app: 식별된 클라이언트 식별자
    client_version: UA에서 파싱한 버전 문자열
    """
    hdr_source = request.headers.get("X-Bridge-Source", "").lower().strip()
    hdr_client  = request.headers.get("X-Client-App", "").lower().strip()
    ua = request.headers.get("User-Agent", "")
    ua_lower = ua.lower()
    origin = request.headers.get("Origin", "")

    # 버전 파싱 (UA에서 첫 번째 /숫자 패턴)
    import re
    vm = re.search(r"[\w\-]+/([\d.]+)", ua)
    client_version = vm.group(1) if vm else ""

    # Chrome Extension
    if origin.startswith("chrome-extension://") or hdr_source == "extension":
        app = "whale" if "whale" in ua_lower else "chrome"
        return "extension", app, client_version

    # CLI
    if hdr_source == "cli" or "amv-cp-bridge-cli" in ua_lower:
        return "cli", "cli", client_version

    # MCP — 클라이언트 세분화 (X-Bridge-Source: mcp 또는 mcp:* 형태 모두 처리)
    if hdr_source == "mcp" or hdr_source.startswith("mcp:"):
        # 이미 세분화된 경우 (mcp:claude, mcp:cursor, mcp:antigravity) 그대로 사용
        if hdr_source in ("mcp:claude", "mcp:cursor", "mcp:antigravity"):
            return hdr_source, hdr_client or hdr_source.split(":")[1], client_version
        # UA / X-Client-App 으로 클라이언트 구분
        for kw, app_id in _SOURCE_MAP.items():
            if kw in ua_lower or kw in hdr_client:
                if "antigravity" in app_id:
                    return "mcp:antigravity", app_id, client_version
                if "cursor" in app_id:
                    return "mcp:cursor", app_id, client_version
                if "claude" in app_id:
                    return "mcp:claude", app_id, client_version
        # MCP이지만 UA로 구분 불가 → claude-desktop 기본
        return "mcp:claude", "claude-desktop", client_version

    # UA 기반 감지 (X-Bridge-Source 헤더 없어도)
    for kw, app_id in _SOURCE_MAP.items():
        if kw in ua_lower:
            if "cli" in app_id:
                return "cli", app_id, client_version
    return "api", "api", client_version

class ChatMessage(BaseModel):
    role: str = "user"
    content: Union[str, List[Any]] = ""

class ChatCompletionRequest(BaseModel):
    model: Optional[str] = "gpt-5.6-sol"
    messages: List[ChatMessage]
    stream: Optional[bool] = False
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None

@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/dashboard")

@app.get("/health")
@app.get("/status")
async def health_check():
    return {
        "status": "healthy",
        "gateway": "amv-cp-bridge",
        "version": __version__,
        "pool_status": engine.get_status_summary(),
        "timestamp": time.time()
    }

@app.get("/api/status")
async def api_status():
    """실시간 엔진 큐, 워커 가용성, 태스크 진행 상태 반환"""
    return engine.get_telemetry_status()

@app.get("/api/stats")
async def api_stats():
    """일/주/월/년 및 최근 쿼리 텔레메트리 DB 통계 반환"""
    return telemetry_db.get_summary()

@app.get("/api/chart")
async def api_chart():
    """최근 14일간 일별 사용량 차트 데이터"""
    return telemetry_db.get_daily_chart(14)

@app.post("/api/stats/reset")
async def api_stats_reset():
    """DB 사용 기록 및 통계 전량 삭제 초기화"""
    telemetry_db.reset_all()
    return {"ok": True, "message": "모든 텔레메트리 기록이 성공적으로 초기화되었습니다."}

@app.get("/favicon.ico")
async def favicon():
    candidates = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(os.path.join(sys._MEIPASS, "amv-cp-bridge.ico"))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "amv-cp-bridge.ico"))
    for c in candidates:
        if os.path.isfile(c):
            return FileResponse(c, media_type="image/x-icon")
    raise HTTPException(status_code=404)

@app.get("/api/record/{record_id}")
async def api_record(record_id: int):
    """특정 record의 full_prompt, full_response 조회"""
    rec = telemetry_db.get_record_full(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")
    return rec

@app.post("/api/purge")
async def api_purge():
    """잔존 Edge 브라우저 프로세스 0MB 강제 소각"""
    for w in engine.workers:
        w.kill_browser_process()
    return {"ok": True, "message": "모든 Edge 프로세스가 강제 소각되어 0MB로 회수되었습니다."}

class SettingsUpdateRequest(BaseModel):
    mode: Optional[str] = Field(None, description="'cold' or 'hot'")
    standby_timeout_sec: Optional[int] = Field(None, description="Standby timeout in seconds")
    rate_limit_rpm: Optional[int] = Field(None, description="Rate limit RPM")

@app.get("/api/settings")
async def api_get_settings():
    """현재 브릿지 동작 모드 및 수명 주기 설정 반환"""
    return {
        "status": "ok",
        "settings": engine.settings,
    }

@app.post("/api/settings")
async def api_update_settings(req: SettingsUpdateRequest):
    """브릿지 동작 모드(콜드/핫로딩) 및 대기 시간 동적 적용 및 영구 저장"""
    data = {}
    if req.mode is not None:
        data["mode"] = req.mode
    if req.standby_timeout_sec is not None:
        data["standby_timeout_sec"] = req.standby_timeout_sec
    if req.rate_limit_rpm is not None:
        data["rate_limit_rpm"] = req.rate_limit_rpm
    updated = engine.update_settings(data)
    return {
        "status": "ok",
        "settings": updated,
    }

@app.post("/api/accounts/{port}/login", status_code=202)
async def api_account_login(port: int):
    """계정 로그인 창을 띄우고 연결 상태를 확인한다. 결과는 SSE accounts 이벤트로 전달된다."""
    worker = next((w for w in engine.workers if w.port == port), None)
    if worker is None:
        raise HTTPException(status_code=404, detail=f"등록되지 않은 계정 포트입니다: {port}")
    if worker.is_busy():
        raise HTTPException(status_code=409, detail=f"{worker.name} 계정이 사용 중입니다.")
    asyncio.create_task(engine.open_login(port))
    return {"ok": True, "port": port}

@app.get("/v1/models")
async def list_models():
    now = int(time.time())
    models = [
        {"id": "gpt-5.6-sol", "object": "model", "created": now, "owned_by": "amv-cp-bridge", "permission": []},
        {"id": "copilot-deepthink", "object": "model", "created": now, "owned_by": "amv-cp-bridge", "permission": []},
        {"id": "copilot-standard", "object": "model", "created": now, "owned_by": "amv-cp-bridge", "permission": []}
    ]
    return {"object": "list", "data": models}

TEMP_UPLOADS_DIR = Path.home() / ".amv_cp_bridge" / "temp_uploads"
TEMP_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_temp_files(file_paths: List[str]):
    """요청 처리 완료 후 생성된 로컬 임시 업로드 파일들을 안전하게 삭제"""
    for fp in file_paths:
        try:
            p = Path(fp)
            if p.is_file():
                p.unlink(missing_ok=True)
        except Exception:
            pass


def parse_messages_and_files(messages: List[ChatMessage], model_name: str) -> Tuple[str, List[str], List[str]]:
    """OpenAI Vision 및 멀티턴 메시지를 파싱하여 텍스트 프롬프트, 첨부 파일 목록, 임시 파일 목록을 반환"""
    prompt_parts = []
    file_paths: List[str] = []
    temp_files: List[str] = []

    deepthink = ("deepthink" in model_name.lower()) or ("sol" in model_name.lower())
    if deepthink:
        prompt_parts.append("[시스템 지침: 1원리(First-principles) 기반으로 수식 및 코드를 생략 없이 완벽하게 유도하여 작성하시오.]\n")

    for msg in messages:
        role_prefix = "[시스템]" if msg.role == "system" else ("[질문]" if msg.role == "user" else "[답변]")
        text_content = ""

        if isinstance(msg.content, str):
            text_content = msg.content
        elif isinstance(msg.content, list):
            parts = []
            for item in msg.content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    itype = item.get("type", "")
                    if itype == "text":
                        parts.append(item.get("text", ""))
                    elif itype in ("image_url", "image", "file", "file_url"):
                        target = item.get("image_url") or item.get("file") or item.get("url") or ""
                        raw_url = target if isinstance(target, str) else (target.get("url", "") if isinstance(target, dict) else "")
                        if not raw_url and isinstance(target, dict):
                            raw_url = target.get("image_url", "")

                        if isinstance(raw_url, str) and raw_url.startswith("data:"):
                            match = re.match(r"^data:([^;]+);base64,(.+)$", raw_url)
                            if match:
                                mime = match.group(1).lower()
                                b64_data = match.group(2)
                                ext = mimetypes.guess_extension(mime) or (".png" if "image" in mime else ".bin")
                                if ext == ".jpe":
                                    ext = ".jpg"
                                tmp_path = TEMP_UPLOADS_DIR / f"upload_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
                                try:
                                    tmp_path.write_bytes(base64.b64decode(b64_data))
                                    file_paths.append(str(tmp_path))
                                    temp_files.append(str(tmp_path))
                                except Exception as b64_err:
                                    print(f"[!] Base64 디코딩 실패: {b64_err}")
                        elif isinstance(raw_url, str) and raw_url.startswith("file://"):
                            local_p = raw_url[7:]
                            if local_p.startswith("/") and os.name == "nt" and len(local_p) > 2 and local_p[2] == ":":
                                local_p = local_p[1:]
                            if os.path.isfile(local_p):
                                file_paths.append(local_p)
                        elif isinstance(raw_url, str) and os.path.isfile(raw_url):
                            file_paths.append(raw_url)
                    elif itype == "file_path":
                        p = item.get("path", "")
                        if isinstance(p, str) and os.path.isfile(p):
                            file_paths.append(p)
            text_content = " ".join(parts).strip()

        if text_content:
            prompt_parts.append(f"{role_prefix}: {text_content}")

    prompt = "\n\n".join(prompt_parts)
    return prompt, file_paths, temp_files


def format_messages_to_prompt(messages: List[ChatMessage], model_name: str) -> str:
    """하위 호환성을 위한 텍스트 프롬프트 변환기"""
    prompt, _, _ = parse_messages_and_files(messages, model_name)
    return prompt


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not _rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail=f"요청 속도 제한 초과 (최대 {_RATE_LIMIT_RPM}회/분)")

    if not req.messages:
        raise HTTPException(status_code=400, detail="messages 필드가 비어있습니다.")

    source, client_app, client_version = _detect_source(request)
    client_ip = request.client.host if request.client else ""

    prompt, file_paths, temp_files = parse_messages_and_files(req.messages, req.model or "gpt-5.6-sol")
    prompt_bytes = len(prompt.encode("utf-8", errors="ignore"))
    request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created_ts = int(time.time())

    if req.stream:
        async def event_generator():
            try:
                first_chunk = {
                    "id": request_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": req.model,
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]
                }
                yield f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n"

                async for token in engine.stream_query(prompt, reset_chat=True, file_paths=file_paths, source=source,
                                                        client_app=client_app, client_version=client_version,
                                                        prompt_bytes=prompt_bytes, ip_addr=client_ip):
                    chunk_data = {
                        "id": request_id,
                        "object": "chat.completion.chunk",
                        "created": created_ts,
                        "model": req.model,
                        "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}]
                    }
                    yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"

                final_chunk = {
                    "id": request_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": req.model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                }
                yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                import traceback
                print(f"[!] 스트리밍 질의 오류: {type(e).__name__}: {e}\n{traceback.format_exc()}")
                err_chunk = {
                    "id": request_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": req.model,
                    "error": {"message": f"[{type(e).__name__}] {str(e)}", "type": "bridge_error"}
                }
                yield f"data: {json.dumps(err_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                cleanup_temp_files(temp_files)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
        )
    else:
        try:
            full_response = await engine.query(prompt, file_paths=file_paths, source=source,
                                               client_app=client_app, client_version=client_version,
                                               prompt_bytes=prompt_bytes, ip_addr=client_ip)
            tokens_est = max(1, int(len(full_response.encode("utf-8")) / 4.2))
            return {
                "id": request_id,
                "object": "chat.completion",
                "created": created_ts,
                "model": req.model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": full_response},
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": len(prompt.split()),
                    "completion_tokens": tokens_est,
                    "total_tokens": len(prompt.split()) + tokens_est
                }
            }
        except Exception as e:
            import traceback
            err_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            print(f"[!] Copilot 브릿지 실행 오류:\n{err_msg}")
            raise HTTPException(status_code=500, detail=f"[디버그] {type(e).__name__}: {str(e)}")
        finally:
            cleanup_temp_files(temp_files)

@app.get("/api/stream")
async def api_event_stream(request: Request):
    """SSE 이벤트 스트림 — GUI/대시보드가 구독, 서버가 Push.
    이벤트 타입: snapshot | task_queued | task_start | task_done
    """
    async def generator():
        q = event_bus.subscribe()
        try:
            # 연결 즉시 현재 상태 스냅샷 전송
            snap = {
                "type": "snapshot",
                "status": engine.get_telemetry_status(),
                "stats": telemetry_db.get_summary(),
            }
            yield f"data: {json.dumps(snap, ensure_ascii=False, default=str)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25.0)
                    # stats_dirty 이벤트 시 최신 통계 첨부
                    if event.get("stats_dirty"):
                        event["stats"] = telemetry_db.get_summary()
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            event_bus.unsubscribe(q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ==============================================================================
# Cyber Dark Real-Time Telemetry Dashboard UI (HTML / CSS / JS)
# ==============================================================================
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>amv-cp-bridge</title>
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" />
  <style>
    :root{
      --bg:#f0f4ff;--card:#ffffff;--bdr:#e2e8f0;
      --p:#6366f1;--ps:#a5b4fc;--g:#22c55e;--y:#f59e0b;--r:#ef4444;
      --t:#1e293b;--m:#64748b;--s:#f8fafc;
      --mono:"Fira Code",Consolas,monospace;
      --rad:16px;--rad-sm:10px;
    }
    *{box-sizing:border-box;margin:0;padding:0}
    body{background:var(--bg);color:var(--t);font-family:"Pretendard Variable",-apple-system,sans-serif;min-height:100vh;overflow-x:hidden}
    /* ── App Shell ── */
    .app{display:flex;flex-direction:column;height:100vh}
    /* ── Top Bar ── */
    .topbar{
      background:#fff;border-bottom:1px solid var(--bdr);
      padding:10px 20px;display:flex;align-items:center;justify-content:space-between;
      gap:12px;flex-shrink:0;
    }
    .logo-area{display:flex;align-items:center;gap:10px}
    .logo-icon{font-size:1.4rem}
    .logo-name{font-size:1.1rem;font-weight:800;background:linear-gradient(135deg,#6366f1,#a855f7);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
    .logo-ver{font-size:.65rem;background:#ede9fe;color:#7c3aed;padding:2px 7px;border-radius:99px;font-weight:700}
    .topbar-right{display:flex;align-items:center;gap:8px}
    .flag-btn{font-size:1.4rem;cursor:pointer;border:none;background:none;padding:2px 4px;border-radius:6px;transition:.15s;line-height:1}
    .flag-btn:hover{background:#f1f5f9}
    .flag-btn.active{outline:2px solid var(--p);outline-offset:1px}
    .live-badge{display:flex;align-items:center;gap:5px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:99px;padding:4px 10px;font-size:.72rem;font-weight:700;color:#16a34a}
    .live-badge.busy{background:#eff6ff;border-color:#bfdbfe;color:#2563eb}
    .dot{width:7px;height:7px;border-radius:50%;background:#22c55e}
    .dot.busy{background:#6366f1;animation:pulse 1.2s infinite}
    @keyframes pulse{0%,100%{opacity:.7;transform:scale(.9)}50%{opacity:1;transform:scale(1.2)}}
    /* ── Tab Nav ── */
    .tabnav{
      background:#fff;border-bottom:1px solid var(--bdr);
      display:flex;gap:0;padding:0 16px;flex-shrink:0;
    }
    .tab{
      padding:10px 18px;font-size:.82rem;font-weight:600;cursor:pointer;
      color:var(--m);border-bottom:2px solid transparent;transition:.15s;
      display:flex;align-items:center;gap:6px;user-select:none;
    }
    .tab:hover{color:var(--p);background:#f8f7ff}
    .tab.active{color:var(--p);border-bottom-color:var(--p);background:transparent}
    /* ── Content Area ── */
    .content{flex:1;overflow-y:auto;padding:20px}
    .panel{display:none}.panel.active{display:block}
    /* ── Settings ── */
    .settings-group{margin-bottom:20px}
    .mode-select-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:14px 0}
    @media(max-width:680px){.mode-select-grid{grid-template-columns:1fr}}
    .mode-card{border:2px solid var(--bdr);border-radius:12px;padding:16px;cursor:pointer;transition:.2s;background:#fff}
    .mode-card:hover{border-color:var(--ps);background:#fafafa}
    .mode-card.selected{border-color:var(--p);background:#f5f3ff}
    .mode-card-title{font-size:.95rem;font-weight:700;display:flex;align-items:center;gap:8px;margin-bottom:8px}
    .mode-card-desc{font-size:.8rem;color:var(--m);line-height:1.6}
    .timeout-row{display:flex;align-items:center;gap:10px;margin-top:10px;flex-wrap:wrap}
    .timeout-input{width:110px;padding:8px 12px;border:1px solid var(--bdr);border-radius:8px;font-size:.9rem;font-family:var(--mono)}
    .btn-preset{padding:6px 12px;font-size:.78rem;font-weight:600;border:1px solid var(--bdr);border-radius:8px;background:#fff;cursor:pointer;color:var(--m);transition:.15s}
    .btn-preset:hover{border-color:var(--p);color:var(--p);background:#f5f3ff}
    .btn-save{background:var(--p);color:#fff;border:none;padding:10px 22px;border-radius:10px;font-weight:700;font-size:.9rem;cursor:pointer;transition:.15s}
    .btn-save:hover{background:#4f46e5}
    .save-alert{display:inline-block;margin-left:12px;font-size:.82rem;font-weight:600;color:var(--g)}
    /* ── Cards ── */
    .card{background:var(--card);border:1px solid var(--bdr);border-radius:var(--rad);padding:18px 20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
    .card-title{font-size:.82rem;font-weight:700;color:var(--m);margin-bottom:14px;display:flex;align-items:center;justify-content:space-between;padding-bottom:10px;border-bottom:1px solid var(--bdr)}
    /* ── Stat Grid ── */
    .stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
    @media(max-width:720px){.stat-grid{grid-template-columns:repeat(2,1fr)}}
    .stat-card{
      background:var(--card);border:1px solid var(--bdr);border-radius:var(--rad);
      padding:14px 16px;box-shadow:0 1px 4px rgba(0,0,0,.04);
      position:relative;overflow:hidden;
    }
    .stat-card::after{content:"";position:absolute;top:0;left:0;right:0;height:3px;border-radius:var(--rad) var(--rad) 0 0;background:linear-gradient(90deg,var(--p),var(--ps))}
    .stat-label{font-size:.7rem;font-weight:700;color:var(--m);text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px}
    .stat-val{font-size:1.8rem;font-weight:800;font-family:var(--mono);color:var(--t);line-height:1}
    .stat-unit{font-size:.78rem;color:var(--p);font-weight:600;margin-left:4px}
    .stat-sub{font-size:.72rem;color:var(--m);margin-top:5px}
    /* ── Status Banner ── */
    .status-row{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;padding:14px 18px;background:linear-gradient(135deg,#f5f3ff,#ede9fe);border:1px solid #ddd6fe;border-radius:var(--rad);margin-bottom:16px}
    .status-left{display:flex;align-items:center;gap:12px}
    .st-title{font-weight:700;font-size:.95rem}
    .st-sub{font-size:.75rem;color:var(--m);margin-top:2px}
    .chips{display:flex;gap:8px;flex-wrap:wrap}
    .chip{background:#fff;border:1px solid var(--bdr);padding:5px 11px;border-radius:99px;font-size:.73rem;font-weight:600;color:var(--m);display:flex;align-items:center;gap:4px}
    .chip strong{color:var(--p);font-family:var(--mono)}
    /* ── Dual ── */
    .dual{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px}
    @media(max-width:720px){.dual{grid-template-columns:1fr}}
    /* ── Worker Item ── */
    .wi{display:flex;align-items:center;justify-content:space-between;padding:9px 12px;background:var(--s);border:1px solid var(--bdr);border-radius:var(--rad-sm);margin-bottom:6px}
    .wn{font-weight:600;font-size:.82rem;color:var(--t)}
    .ws{font-size:.68rem;color:var(--m);margin-top:2px}
    .wb{font-size:.68rem;padding:3px 8px;border-radius:99px;font-weight:700}
    .b-idle{background:#dcfce7;color:#16a34a}.b-busy{background:#e0e7ff;color:#4338ca}.b-off{background:#f1f5f9;color:#94a3b8}
    /* ── Task box ── */
    .task-box{font-family:var(--mono);font-size:.78rem;background:var(--s);border:1px solid var(--bdr);padding:12px;border-radius:var(--rad-sm);min-height:68px;color:var(--m);line-height:1.6;word-break:break-all}
    /* ── Chart ── */
    .chart-wrap{position:relative;height:200px}
    /* ── Table ── */
    .tbl-wrap{overflow-x:auto;margin-top:10px}
    table{width:100%;border-collapse:collapse;font-size:.76rem;text-align:left}
    th{color:var(--m);font-weight:600;border-bottom:2px solid var(--bdr);padding:8px 10px;white-space:nowrap;background:var(--s)}
    td{padding:8px 10px;border-bottom:1px solid var(--bdr);color:var(--t);white-space:nowrap}
    tr:hover td{background:#f8f7ff}
    .tp{max-width:320px;overflow:hidden;text-overflow:ellipsis;font-weight:500}
    .tm{font-family:var(--mono);font-size:.72rem}
    /* ── How-to ── */
    .how-section{margin-bottom:20px}
    .how-h{font-size:.88rem;font-weight:700;color:var(--t);margin-bottom:10px;display:flex;align-items:center;gap:7px}
    .how-step{display:flex;gap:12px;margin-bottom:10px;align-items:flex-start}
    .step-num{width:24px;height:24px;border-radius:50%;background:var(--p);color:#fff;font-size:.72rem;font-weight:800;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:1px}
    .step-body{flex:1}
    .step-title{font-weight:600;font-size:.82rem;margin-bottom:3px}
    .step-desc{font-size:.77rem;color:var(--m);line-height:1.5}
    code{background:#f1f5f9;border:1px solid var(--bdr);border-radius:6px;padding:2px 6px;font-family:var(--mono);font-size:.77rem;color:#6366f1}
    pre{background:#1e293b;color:#e2e8f0;padding:14px;border-radius:var(--rad-sm);font-size:.76rem;line-height:1.6;overflow-x:auto;margin:8px 0}
    pre code{background:none;border:none;padding:0;color:inherit;font-size:inherit}
    .mode-tag{display:inline-block;background:#ede9fe;color:#7c3aed;border-radius:99px;padding:2px 9px;font-size:.7rem;font-weight:700;margin:2px}
    /* ── About / Links ── */
    .link-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
    @media(max-width:500px){.link-grid{grid-template-columns:1fr}}
    .link-card{
      display:flex;align-items:center;gap:14px;
      background:var(--card);border:1px solid var(--bdr);border-radius:var(--rad);
      padding:14px 16px;text-decoration:none;color:var(--t);
      transition:.15s;box-shadow:0 1px 3px rgba(0,0,0,.05);
    }
    .link-card:hover{border-color:var(--ps);box-shadow:0 4px 12px rgba(99,102,241,.12);transform:translateY(-1px)}
    .link-icon{font-size:1.6rem;width:42px;height:42px;display:flex;align-items:center;justify-content:center;border-radius:12px;flex-shrink:0}
    .link-info .lk-name{font-weight:700;font-size:.85rem}
    .link-info .lk-url{font-size:.72rem;color:var(--m);margin-top:2px}
    .about-hero{text-align:center;padding:24px 16px;margin-bottom:20px}
    .about-hero h2{font-size:1.3rem;font-weight:800;margin-bottom:6px;background:linear-gradient(135deg,#6366f1,#a855f7);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
    .about-hero p{color:var(--m);font-size:.82rem;line-height:1.6}
    /* ── Action Buttons ── */
    .action-row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
    .btn{padding:7px 14px;border-radius:var(--rad-sm);font-size:.78rem;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;gap:5px;border:1px solid transparent;transition:.15s;font-family:inherit}
    .btn-ghost{background:var(--s);color:var(--m);border-color:var(--bdr)}.btn-ghost:hover{background:#e2e8f0;color:var(--t)}
    .btn-danger{background:#fff0f0;color:#dc2626;border-color:#fecaca}.btn-danger:hover{background:#fecaca}
    .badge-ok{display:inline-flex;align-items:center;gap:4px;background:#dcfce7;color:#16a34a;border-radius:99px;padding:2px 8px;font-size:.68rem;font-weight:700}
    .badge-warn{background:#fef9c3;color:#854d0e;border-radius:99px;padding:2px 8px;font-size:.68rem;font-weight:700}
    .setup-item{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:var(--s);border:1px solid var(--bdr);border-radius:var(--rad-sm);margin-bottom:6px}
    .setup-name{font-weight:600;font-size:.82rem;display:flex;align-items:center;gap:8px}
  </style>
</head>
<body>
<div class="app">

  <!-- Top Bar -->
  <header class="topbar">
    <div class="logo-area">
      <span class="logo-icon">⚡</span>
      <span class="logo-name">amv-cp-bridge</span>
      <span class="logo-ver">v__APP_VERSION__</span>
    </div>
    <div class="topbar-right">
      <div class="live-badge" id="liveBadge">
        <span class="dot" id="liveDot"></span>
        <span id="liveText">Idle</span>
      </div>
      <button class="flag-btn active" id="btnKo" onclick="setLang('ko')" title="한국어">🇰🇷</button>
      <button class="flag-btn" id="btnEn" onclick="setLang('en')" title="English">🇺🇸</button>
    </div>
  </header>

  <!-- Tab Nav -->
  <nav class="tabnav">
    <div class="tab active" onclick="switchTab('dashboard')" id="tab-dashboard">
      <span>📊</span><span data-i="tab_dash">대시보드</span>
    </div>
    <div class="tab" onclick="switchTab('usage')" id="tab-usage">
      <span>📈</span><span data-i="tab_usage">사용량</span>
    </div>
    <div class="tab" onclick="switchTab('settings')" id="tab-settings">
      <span>⚙️</span><span data-i="tab_settings">설정</span>
    </div>
    <div class="tab" onclick="switchTab('howto')" id="tab-howto">
      <span>📖</span><span data-i="tab_howto">사용방법</span>
    </div>
    <div class="tab" onclick="switchTab('about')" id="tab-about">
      <span>🙋</span><span data-i="tab_about">만든이</span>
    </div>
  </nav>

  <!-- Content -->
  <div class="content">

    <!-- ① Dashboard Panel -->
    <div class="panel active" id="panel-dashboard">
      <!-- Status -->
      <div class="status-row">
        <div class="status-left">
          <div class="dot" id="statusDot"></div>
          <div>
            <div class="st-title" id="statusTitle">IDLE</div>
            <div class="st-sub" id="statusSub" data-i="idle_sub">대기 중</div>
          </div>
        </div>
        <div class="chips">
          <div class="chip"><span data-i="lbl_queue">대기 큐</span> <strong id="chipQueue">0</strong></div>
          <div class="chip"><span data-i="lbl_accounts">계정</span> <strong id="chipAccounts">0/0</strong></div>
        </div>
      </div>

      <!-- Stat Cards -->
      <div class="stat-grid">
        <div class="stat-card"><div class="stat-label" data-i="today">오늘</div><div><span class="stat-val" id="todayQ">0</span><span class="stat-unit" data-i="times">회</span></div><div class="stat-sub" id="todayD">0 tokens</div></div>
        <div class="stat-card"><div class="stat-label" data-i="week">이번 주</div><div><span class="stat-val" id="weekQ">0</span><span class="stat-unit" data-i="times">회</span></div><div class="stat-sub" id="weekD">0 tokens</div></div>
        <div class="stat-card"><div class="stat-label" data-i="month">이번 달</div><div><span class="stat-val" id="monthQ">0</span><span class="stat-unit" data-i="times">회</span></div><div class="stat-sub" id="monthD">0 tokens</div></div>
        <div class="stat-card"><div class="stat-label" data-i="year">올해</div><div><span class="stat-val" id="yearQ">0</span><span class="stat-unit" data-i="times">회</span></div><div class="stat-sub" id="yearD">0 tokens</div></div>
      </div>

      <!-- Worker + Task -->
      <div class="dual">
        <div class="card">
          <div class="card-title"><span data-i="workers_title">계정 상태</span><span style="font-size:.7rem;color:var(--p)" id="workerSummary"></span></div>
          <div id="workersList"></div>
        </div>
        <div class="card">
          <div class="card-title"><span data-i="task_title">현재 작업</span><span style="font-size:.7rem;color:var(--y)" id="taskElapsed">—</span></div>
          <div class="task-box" id="taskPreview" data-i="no_task">대기 중</div>
        </div>
      </div>

      <!-- Install Status -->
      <div class="card">
        <div class="card-title"><span data-i="setup_title">설치 상태</span></div>
        <div id="setupList"></div>
      </div>

      <!-- Actions -->
      <div class="action-row">
        <button class="btn btn-ghost" onclick="refreshAll()">🔄 새로고침</button>
        <button class="btn btn-ghost" onclick="forcePurge()">🧹 <span data-i="purge_btn">메모리 정리</span></button>
        <button class="btn btn-danger" onclick="resetStats()">🗑 <span data-i="reset_btn">통계 초기화</span></button>
      </div>
    </div>

    <!-- ② Usage Panel -->
    <div class="panel" id="panel-usage">
      <div class="card">
        <div class="card-title"><span data-i="chart_title">최근 14일 사용량</span></div>
        <div class="chart-wrap"><canvas id="usageChart"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title"><span data-i="history_title">최근 사용 기록 (20건)</span><span class="tm" style="color:var(--m);font-size:.72rem" id="dbCount">0</span></div>
        <div class="tbl-wrap">
          <table><thead><tr>
            <th data-i="th_time">시간</th><th data-i="th_prompt">프롬프트</th>
            <th data-i="th_tokens">토큰</th><th data-i="th_latency">지연</th>
            <th data-i="th_source">소스</th><th data-i="th_result">결과</th><th></th>
          </tr></thead>
          <tbody id="histBody"><tr><td colspan="7" style="text-align:center;padding:24px;color:var(--m)" data-i="no_data">기록 없음</td></tr></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ③ How-to Panel -->
    <div class="panel" id="panel-howto">
      <div class="card">
        <div class="how-section">
          <div class="how-h">🚀 <span data-i="ht_start">빠른 시작</span></div>
          <div class="how-step"><div class="step-num">1</div><div class="step-body"><div class="step-title" data-i="ht_s1_title">Edge 로그인</div><div class="step-desc" data-i="ht_s1_desc">Microsoft Edge에서 <code>https://m365.cloud.microsoft/chat</code> 에 로그인하세요.</div></div></div>
          <div class="how-step"><div class="step-num">2</div><div class="step-body"><div class="step-title" data-i="ht_s2_title">계정 설정</div><div class="step-desc" data-i="ht_s2_desc"><code>~/.amv_cp_bridge/accounts.json</code> 파일에 계정 정보를 추가하세요.</div></div></div>
          <div class="how-step"><div class="step-num">3</div><div class="step-body"><div class="step-title" data-i="ht_s3_title">API 사용</div><div class="step-desc" data-i="ht_s3_desc">아래 엔드포인트로 요청을 보내면 됩니다.</div></div></div>
        </div>

        <div class="how-section">
          <div class="how-h">🔗 <span data-i="ht_api">API 엔드포인트</span></div>
          <pre><code>POST http://localhost:11500/v1/chat/completions

{
  "model": "gpt-5.6-sol",
  "messages": [{"role": "user", "content": "안녕하세요"}],
  "stream": true
}</code></pre>
        </div>

        <div class="how-section">
          <div class="how-h">🧩 <span data-i="ht_mcp">MCP 연동 (Claude Desktop / Cursor)</span></div>
          <pre><code>{
  "mcpServers": {
    "copilot": {
      "command": "amv-cp-bridge",
      "args": ["serve"]
    }
  }
}</code></pre>
        </div>

        <div class="how-section">
          <div class="how-h">🎛️ <span data-i="ht_modes">추론 모드</span></div>
          <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px">
            <span class="mode-tag" data-i="mode_auto">자동 (Auto)</span>
            <span class="mode-tag" data-i="mode_fast">빠름 (Fast)</span>
            <span class="mode-tag" data-i="mode_deep">깊게 (Deep)</span>
            <span class="mode-tag">Sol 5.6 Quick</span>
            <span class="mode-tag">Sol 5.6 Deep Thinking</span>
          </div>
        </div>

        <div class="how-section">
          <div class="how-h">🖥️ <span data-i="ht_ext">브라우저 확장프로그램</span></div>
          <div class="how-step"><div class="step-num">1</div><div class="step-body"><div class="step-desc" data-i="ht_ext1"><code>chrome://extensions</code> 또는 <code>whale://extensions</code> 접속</div></div></div>
          <div class="how-step"><div class="step-num">2</div><div class="step-body"><div class="step-desc" data-i="ht_ext2">개발자 모드 ON → "압축해제된 확장 프로그램을 로드합니다" 클릭</div></div></div>
          <div class="how-step"><div class="step-num">3</div><div class="step-body"><div class="step-desc" data-i="ht_ext3">Releases의 <code>amv-cp-bridge-extension.zip</code> 압축 해제 폴더 선택 → <kbd>Ctrl+Shift+Y</kbd> 로 사이드바 열기</div></div></div>
        </div>

        <div class="how-section">
          <div class="how-h">🍎 <span data-i="ht_mac">macOS 설치</span></div>
          <pre><code>bash &lt;(curl -fsSL https://raw.githubusercontent.com/uno-km/amv-cp-bridge/main/scripts/macos/install.sh)</code></pre>
        </div>
      </div>
    </div>

    <!-- ④ About Panel -->
    <div class="panel" id="panel-about">
      <div class="about-hero">
        <h2>Eunho Kim (uno-km)</h2>
        <p data-i="about_desc">amv-cp-bridge를 만들고 있습니다.<br>피드백이나 커피 한 잔은 언제나 환영합니다 ☕</p>
      </div>
      <div class="link-grid">
        <a class="link-card" href="https://uno-km.vercel.app/foundation/" target="_blank">
          <div class="link-icon" style="background:#ede9fe">🌐</div>
          <div class="link-info"><div class="lk-name" data-i="lk_site">웹사이트</div><div class="lk-url">uno-km.vercel.app/foundation</div></div>
        </a>
        <a class="link-card" href="https://github.com/uno-km" target="_blank">
          <div class="link-icon" style="background:#f1f5f9">🐙</div>
          <div class="link-info"><div class="lk-name">GitHub</div><div class="lk-url">github.com/uno-km</div></div>
        </a>
        <a class="link-card" href="https://uno-kim.tistory.com/" target="_blank">
          <div class="link-icon" style="background:#fff7ed">✍️</div>
          <div class="link-info"><div class="lk-name" data-i="lk_blog">블로그</div><div class="lk-url">uno-kim.tistory.com</div></div>
        </a>
        <a class="link-card" href="https://buymeacoffee.com/uno.km" target="_blank">
          <div class="link-icon" style="background:#fefce8">☕</div>
          <div class="link-info"><div class="lk-name" data-i="lk_coffee">커피 한 잔</div><div class="lk-url">buymeacoffee.com/uno.km</div></div>
        </a>
      </div>
      <div class="card" style="margin-top:16px;text-align:center;color:var(--m);font-size:.78rem;line-height:1.7">
        <p data-i="about_footer">Apache-2.0 OR Commercial License &nbsp;·&nbsp; Copyright © 2026 Eunho Kim / AMEVA Foundation</p>
        <p style="margin-top:6px" data-i="about_stack">Python · FastAPI · Playwright · SQLite · CustomTkinter · Chrome MV3</p>
      </div>
    </div>

    <!-- ⑤ Settings Panel -->
    <div class="panel" id="panel-settings">
      <div class="card">
        <div class="card-title">
          <span>⚡ <span data-i="cfg_title">브릿지 동작 모드 및 수명 주기 설정</span></span>
          <span style="font-size:.72rem;background:#ede9fe;color:#7c3aed;padding:2px 8px;border-radius:99px;font-weight:700">v1.1.0</span>
        </div>

        <div class="settings-group">
          <label style="font-weight:700;font-size:.88rem;color:var(--t)" data-i="cfg_mode_label">동작 모드 선택</label>
          <div class="mode-select-grid">
            <div class="mode-card selected" id="optCold" onclick="selectMode('cold')">
              <div class="mode-card-title">
                <input type="radio" name="bridgeMode" id="radioCold" checked>
                <label for="radioCold" style="cursor:pointer" data-i="cfg_mode_cold">❄️ 콜드 유지 (기본값 / 0MB 권장)</label>
              </div>
              <div class="mode-card-desc" data-i="cfg_desc_cold">
                • 질문-답변 완료 즉시 Edge 브라우저를 완전 강제 종료합니다.<br>
                • 평상시 유휴 메모리 점유율을 0MB로 깨끗하게 유지합니다.<br>
                • 첫 질문 시 브라우저 기동에 10~15초 소요됩니다.
              </div>
            </div>

            <div class="mode-card" id="optHot" onclick="selectMode('hot')">
              <div class="mode-card-title">
                <input type="radio" name="bridgeMode" id="radioHot">
                <label for="radioHot" style="cursor:pointer" data-i="cfg_mode_hot">🔥 핫로딩 (웜 스탠바이 / 초고속)</label>
              </div>
              <div class="mode-card-desc" data-i="cfg_desc_hot">
                • 질문 완료 후에도 설정된 시간 동안 Edge를 켜둔 채 대기합니다.<br>
                • 연속 질문 시 5초 미만 즉각 응답 및 이전 맥락이 유지됩니다.<br>
                • 대기 시간 만료 시 메모리 누수 방지를 위해 자동으로 브라우저를 종료(0MB)합니다.
              </div>
            </div>
          </div>
        </div>

        <div class="settings-group" id="timeoutGroup" style="border-top:1px solid var(--bdr);padding-top:16px">
          <label style="font-weight:700;font-size:.88rem;color:var(--t)" data-i="cfg_timeout_label">웜 스탠바이 유지 시간 (초 단위)</label>
          <div style="font-size:.78rem;color:var(--m);margin-top:4px" data-i="cfg_timeout_hint">핫로딩 모드에서 마지막 요청 완료 후 브라우저 프로세스를 유지할 시간입니다.</div>
          <div class="timeout-row">
            <input type="number" id="inputTimeout" class="timeout-input" value="300" min="10" max="86400">
            <span style="font-size:.85rem;color:var(--m)" data-i="seconds">초</span>
            <button type="button" class="btn-preset" onclick="setTimeoutVal(60)">60초 (1분)</button>
            <button type="button" class="btn-preset" onclick="setTimeoutVal(300)">300초 (5분)</button>
            <button type="button" class="btn-preset" onclick="setTimeoutVal(600)">600초 (10분)</button>
            <button type="button" class="btn-preset" onclick="setTimeoutVal(1800)">1800초 (30분)</button>
          </div>
        </div>

        <div style="margin-top:24px;display:flex;align-items:center">
          <button class="btn-save" onclick="saveSettings()">💾 <span data-i="cfg_btn_save">설정 저장</span></button>
          <span id="saveAlert" class="save-alert" style="display:none">✓ <span data-i="cfg_saved_msg">설정이 성공적으로 저장되었습니다.</span></span>
        </div>
      </div>
    </div>

  </div><!-- .content -->
</div><!-- .app -->

<!-- 상세보기 모달 -->
<div id="recModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9999;align-items:center;justify-content:center">
  <div style="background:#fff;border-radius:16px;width:min(92vw,760px);max-height:88vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.25)">
    <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid #e2e8f0">
      <span style="font-weight:700;font-size:.9rem;color:#1e293b" id="modalMeta">—</span>
      <button onclick="closeModal()" style="background:#f1f5f9;border:none;border-radius:8px;width:28px;height:28px;cursor:pointer;font-size:1rem;color:#64748b">✕</button>
    </div>
    <div style="display:flex;border-bottom:1px solid #e2e8f0">
      <button id="mTabQ" onclick="mTab('q')" style="flex:1;padding:9px;font-size:.82rem;font-weight:700;background:#6366f1;color:#fff;border:none;cursor:pointer">📝 질의</button>
      <button id="mTabR" onclick="mTab('r')" style="flex:1;padding:9px;font-size:.82rem;font-weight:700;background:#f1f5f9;color:#64748b;border:none;cursor:pointer">💬 응답</button>
    </div>
    <div style="flex:1;overflow-y:auto;padding:16px 18px;font-size:.84rem;line-height:1.75;white-space:pre-wrap;color:#1e293b;font-family:'Cascadia Code','Consolas',monospace" id="modalContent"></div>
  </div>
</div>

<script>
// ── i18n ──
const L = {
  ko:{
    tab_dash:"대시보드", tab_usage:"사용량", tab_settings:"설정", tab_howto:"사용방법", tab_about:"만든이",
    idle_sub:"대기 중", lbl_queue:"대기 큐", lbl_accounts:"계정",
    today:"오늘", week:"이번 주", month:"이번 달", year:"올해", times:"회",
    workers_title:"계정 상태", task_title:"현재 작업", no_task:"대기 중",
    setup_title:"설치 상태", chart_title:"최근 14일 사용량", history_title:"최근 사용 기록 (20건)",
    th_time:"시간", th_prompt:"프롬프트", th_tokens:"토큰", th_latency:"지연", th_source:"소스", th_result:"결과",
    no_data:"기록 없음", purge_btn:"메모리 정리", reset_btn:"통계 초기화",
    busy:"작업 중", acct_ok:"연결됨", acct_unknown:"연결 확인 전", acct_required:"로그인 필요",
    s_gw:"게이트웨이", s_ext:"브라우저 확장프로그램", s_mcp:"MCP 서버", s_db:"텔레메트리 DB",
    installed:"✅ 실행 중", unknown:"설치 안내",
    confirm_purge:"Edge 잔여 프로세스를 정리하시겠습니까?", confirm_reset:"모든 사용 기록을 삭제하시겠습니까?",
    ok:"성공", fail:"실패",
    chart_queries:"쿼리", chart_tokens:"토큰",
    ht_start:"빠른 시작",
    ht_s1_title:"Edge 로그인", ht_s1_desc:"Microsoft Edge에서 https://m365.cloud.microsoft/chat 에 로그인하세요.",
    ht_s2_title:"계정 설정", ht_s2_desc:"~/.amv_cp_bridge/accounts.json 파일에 계정 정보를 추가하세요.",
    ht_s3_title:"API 사용", ht_s3_desc:"아래 엔드포인트로 요청을 보내면 됩니다.",
    ht_api:"API 엔드포인트", ht_mcp:"MCP 연동 (Claude Desktop / Cursor)",
    ht_modes:"추론 모드", mode_auto:"자동 (Auto)", mode_fast:"빠름 (Fast)", mode_deep:"깊게 (Deep)",
    ht_ext:"브라우저 확장프로그램",
    ht_ext1:"chrome://extensions 또는 whale://extensions 접속",
    ht_ext2:"개발자 모드 ON → 압축해제된 확장 프로그램을 로드합니다 클릭",
    ht_ext3:"Releases의 amv-cp-bridge-extension.zip 압축 해제 폴더 선택 → Ctrl+Shift+Y 로 사이드바 열기",
    ht_mac:"macOS 설치",
    cfg_title:"브릿지 동작 모드 및 수명 주기 설정",
    cfg_mode_label:"동작 모드 선택",
    cfg_mode_cold:"❄️ 콜드 유지 (기본값 / 0MB 권장)",
    cfg_mode_hot:"🔥 핫로딩 (웜 스탠바이 / 초고속)",
    cfg_desc_cold:"• 질문-답변 완료 즉시 Edge 브라우저를 완전 강제 종료합니다.<br>• 평상시 유휴 메모리 점유율을 0MB로 깨끗하게 유지합니다.<br>• 첫 질문 시 브라우저 기동에 10~15초 소요됩니다.",
    cfg_desc_hot:"• 질문 완료 후에도 설정된 시간 동안 Edge를 켜둔 채 대기합니다.<br>• 연속 질문 시 5초 미만 즉각 응답 및 이전 맥락이 유지됩니다.<br>• 대기 시간 만료 시 메모리 누수 방지를 위해 자동으로 브라우저를 종료(0MB)합니다.",
    cfg_timeout_label:"웜 스탠바이 유지 시간 (초 단위)",
    cfg_timeout_hint:"핫로딩 모드에서 마지막 요청 완료 후 브라우저 프로세스를 유지할 시간입니다.",
    cfg_btn_save:"설정 저장",
    cfg_saved_msg:"설정이 성공적으로 저장되고 엔진에 즉시 적용되었습니다.",
    seconds:"초",
    about_desc:"amv-cp-bridge를 만들고 있습니다. 피드백이나 커피 한 잔은 언제나 환영합니다 ☕",
    lk_site:"웹사이트", lk_blog:"블로그", lk_coffee:"커피 한 잔",
    about_footer:"Apache-2.0 OR Commercial License · Copyright © 2026 Eunho Kim / AMEVA Foundation",
    about_stack:"Python · FastAPI · Playwright · SQLite · CustomTkinter · Chrome MV3",
  },
  en:{
    tab_dash:"Dashboard", tab_usage:"Usage", tab_settings:"Settings", tab_howto:"How to Use", tab_about:"About",
    idle_sub:"Idle", lbl_queue:"Queue", lbl_accounts:"Accounts",
    today:"Today", week:"This Week", month:"This Month", year:"This Year", times:"queries",
    workers_title:"Account Status", task_title:"Current Task", no_task:"Idle",
    setup_title:"Installation Status", chart_title:"Usage (Last 14 Days)", history_title:"Recent Activity (20)",
    th_time:"Time", th_prompt:"Prompt", th_tokens:"Tokens", th_latency:"Latency", th_source:"Source", th_result:"Result",
    no_data:"No records", purge_btn:"Purge Memory", reset_btn:"Reset Stats",
    busy:"Busy", acct_ok:"Connected", acct_unknown:"Not checked", acct_required:"Sign-in required",
    s_gw:"Gateway", s_ext:"Browser Extension", s_mcp:"MCP Server", s_db:"Telemetry DB",
    installed:"✅ Running", unknown:"Setup Guide",
    confirm_purge:"Purge all Edge processes?", confirm_reset:"Delete all usage records?",
    ok:"OK", fail:"Fail",
    chart_queries:"Queries", chart_tokens:"Tokens",
    ht_start:"Quick Start",
    ht_s1_title:"Sign in to Edge", ht_s1_desc:"Sign into https://m365.cloud.microsoft/chat in Microsoft Edge.",
    ht_s2_title:"Configure Accounts", ht_s2_desc:"Add account info to ~/.amv_cp_bridge/accounts.json.",
    ht_s3_title:"Use the API", ht_s3_desc:"Send requests to the endpoint below.",
    ht_api:"API Endpoint", ht_mcp:"MCP Integration (Claude Desktop / Cursor)",
    ht_modes:"Inference Modes", mode_auto:"Auto", mode_fast:"Fast", mode_deep:"Deep",
    ht_ext:"Browser Extension",
    ht_ext1:"Go to chrome://extensions or whale://extensions",
    ht_ext2:"Enable Developer Mode → Click Load unpacked",
    ht_ext3:"Select the folder extracted from amv-cp-bridge-extension.zip in Releases → Press Ctrl+Shift+Y to open sidebar",
    ht_mac:"macOS Install",
    cfg_title:"Bridge Operation Mode & Standby Lifecycle",
    cfg_mode_label:"Operation Mode",
    cfg_mode_cold:"❄️ Cold Launch (Default / 0MB Idle)",
    cfg_mode_hot:"🔥 Hot Standby (Keep-Alive / Ultra-Fast)",
    cfg_desc_cold:"• Forcibly terminates the Edge browser process immediately after query.<br>• Guarantees 0MB idle memory footprint.<br>• Takes 10-15s to launch browser on new query.",
    cfg_desc_hot:"• Keeps Edge browser alive in background for specified seconds after query.<br>• Enables <5s ultra-fast consecutive responses and retains conversation context.<br>• Automatically terminates browser to 0MB if no further queries arrive within timeout.",
    cfg_timeout_label:"Warm Standby Timeout (Seconds)",
    cfg_timeout_hint:"How long to keep Edge running after the last query in hot mode.",
    cfg_btn_save:"Save Settings",
    cfg_saved_msg:"Settings successfully saved and applied to engine.",
    seconds:"sec",
    about_desc:"Building amv-cp-bridge. Feedback and coffee are always welcome ☕",
    lk_site:"Website", lk_blog:"Blog", lk_coffee:"Buy Me a Coffee",
    about_footer:"Apache-2.0 OR Commercial License · Copyright © 2026 Eunho Kim / AMEVA Foundation",
    about_stack:"Python · FastAPI · Playwright · SQLite · CustomTkinter · Chrome MV3",
  }
};
let lang = 'ko';
function t(k){ return L[lang][k] ?? k; }

function setLang(l){
  lang = l;
  document.getElementById('btnKo').classList.toggle('active', l==='ko');
  document.getElementById('btnEn').classList.toggle('active', l==='en');
  document.querySelectorAll('[data-i]').forEach(el=>{
    const v = t(el.dataset.i);
    if(el.tagName==='INPUT') el.placeholder=v; else el.textContent=v;
  });
  updateSetupPanel();
  if(usageChart){ usageChart.data.datasets[0].label=t('chart_queries'); usageChart.data.datasets[1].label=t('chart_tokens'); usageChart.update('none'); }
}

// ── Tabs ──
function switchTab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  document.getElementById('panel-'+name).classList.add('active');
  if(name==='usage') updateChart();
}

// ── Chart ──
let usageChart = null;
function initChart(){
  const ctx = document.getElementById('usageChart').getContext('2d');
  usageChart = new Chart(ctx, {
    type:'bar',
    data:{labels:[],datasets:[
      {label:t('chart_queries'),data:[],backgroundColor:'rgba(99,102,241,0.65)',borderRadius:5,yAxisID:'y'},
      {label:t('chart_tokens'),data:[],backgroundColor:'rgba(34,197,94,0.35)',borderRadius:5,yAxisID:'y1'}
    ]},
    options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{legend:{labels:{color:'#64748b',font:{size:11},boxWidth:12}}},
      scales:{
        x:{ticks:{color:'#94a3b8',font:{size:10}},grid:{color:'rgba(0,0,0,.05)'}},
        y:{position:'left',ticks:{color:'#6366f1',font:{size:10}},grid:{color:'rgba(0,0,0,.05)'}},
        y1:{position:'right',ticks:{color:'#16a34a',font:{size:10}},grid:{drawOnChartArea:false}}
      }
    }
  });
}

async function updateChart(){
  try{
    const data = await fetch('/api/chart').then(r=>r.json());
    if(!usageChart) return;
    usageChart.data.labels = data.map(d=>d.day.slice(5));
    usageChart.data.datasets[0].data = data.map(d=>d.queries);
    usageChart.data.datasets[1].data = data.map(d=>d.tokens);
    usageChart.update('none');
  }catch(e){}
}

// ── Setup Panel ──
function updateSetupPanel(){
  const items=[
    {key:'s_gw',ok:true},{key:'s_db',ok:true},
    {key:'s_ext',ok:null},{key:'s_mcp',ok:null}
  ];
  document.getElementById('setupList').innerHTML = items.map(c=>`
    <div class="setup-item">
      <div class="setup-name">${c.ok===true?'🟢':c.ok===null?'🔵':'🔴'} ${t(c.key)}</div>
      ${c.ok===true
        ?`<span class="badge-ok">${t('installed')}</span>`
        :`<span class="badge-warn">${t('unknown')}</span>`
      }
    </div>`).join('');
}

// ── Utils ──
function esc(s){return s?String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'):''}
function extractUserQuery(text){
  if(!text) return '';
  const marker='[질문]: ';
  const idx=text.lastIndexOf(marker);
  return idx>=0 ? text.slice(idx+marker.length).trim() : text;
}

// ── Dashboard ──
async function updateDashboard(){
  try{
    const [st,stats]=await Promise.all([fetch('/api/status').then(r=>r.json()),fetch('/api/stats').then(r=>r.json())]);
    const busy=st.is_busy;
    const badge=document.getElementById('liveBadge');
    const dot=document.getElementById('liveDot');
    const liveText=document.getElementById('liveText');
    if(busy){badge.className='live-badge busy';dot.className='dot busy';liveText.textContent='Processing';}
    else{badge.className='live-badge';dot.className='dot';liveText.textContent='Idle';}
    const sdot=document.getElementById('statusDot');
    document.getElementById('statusTitle').textContent=busy?'PROCESSING':'IDLE';
    sdot.className=busy?'dot busy':'dot';
    document.getElementById('chipQueue').textContent=st.queued_requests;
    document.getElementById('chipAccounts').textContent=st.available_accounts+'/'+st.total_accounts;
    document.getElementById('taskElapsed').textContent=busy?st.current_task_elapsed_sec+'s':'—';
    document.getElementById('taskPreview').textContent=busy?(st.current_task||'...'):t('no_task');
    if(st.workers){
      document.getElementById('workerSummary').textContent=st.total_accounts+' accts';
      document.getElementById('workersList').innerHTML=st.workers.map(w=>{
        const cls=w.is_busy?'b-busy':(w.login_state==='ok'?'b-idle':'b-off');
        let txt=w.is_busy?t('busy'):t(w.login_state==='ok'?'acct_ok':(w.login_state==='required'?'acct_required':'acct_unknown'));
        if(!w.is_busy && w.is_alive && w.standby_remaining_sec > 0){
          txt += ' (⏱️ ' + Math.round(w.standby_remaining_sec) + 's)';
        }
        return `<div class="wi"><div><div class="wn">${esc(w.name)}</div><div class="ws">port ${w.port}</div></div><span class="wb ${cls}">${txt}</span></div>`;
      }).join('');
    }
    document.getElementById('todayQ').textContent=stats.today.queries.toLocaleString();
    document.getElementById('todayD').textContent=stats.today.tokens.toLocaleString()+' tokens';
    document.getElementById('weekQ').textContent=stats.week.queries.toLocaleString();
    document.getElementById('weekD').textContent=stats.week.tokens.toLocaleString()+' tokens';
    document.getElementById('monthQ').textContent=stats.month.queries.toLocaleString();
    document.getElementById('monthD').textContent=stats.month.tokens.toLocaleString()+' tokens';
    document.getElementById('yearQ').textContent=stats.year.queries.toLocaleString();
    document.getElementById('yearD').textContent=stats.year.tokens.toLocaleString()+' tokens ('+stats.total.success_rate+'%)';
    document.getElementById('dbCount').textContent=stats.total.queries.toLocaleString();
    const tb=document.getElementById('histBody');
    if(stats.recent&&stats.recent.length>0){
      tb.innerHTML=stats.recent.map(r=>{
        const q=esc(extractUserQuery(r.prompt_preview||''));
        return `<tr>
          <td class="tm">${r.time_str}</td>
          <td class="tp tm" title="${q}">${q||'—'}</td>
          <td class="tm" style="color:var(--p);font-weight:700">+${r.tokens_est.toLocaleString()}</td>
          <td class="tm">${(r.duration_ms/1000).toFixed(1)}s</td>
          <td>${esc(r.source||'api')}</td>
          <td>${r.success?'<span style="color:#16a34a">'+t('ok')+'</span>':'<span style="color:#dc2626">'+t('fail')+'</span>'}</td>
          <td><button onclick="openModal(${r.id})" style="font-size:.72rem;padding:3px 8px;background:#ede9fe;color:#6366f1;border:none;border-radius:6px;cursor:pointer;font-weight:700">상세</button></td>
        </tr>`;
      }).join('');
    } else {
      tb.innerHTML=`<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--m)">${t('no_data')}</td></tr>`;
    }
  }catch(e){console.warn('dashboard fetch failed:',e);}
}

// ── Record Modal ──
let _modalRec=null;
async function openModal(id){
  try{
    const r=await fetch('/api/record/'+id).then(res=>res.json());
    _modalRec=r;
    const src=r.source||'api';
    const dur=(r.duration_ms/1000).toFixed(1);
    const tok=(r.tokens_est||0).toLocaleString();
    document.getElementById('modalMeta').textContent=`${r.time_str||''} · ${src} · ${dur}s · ${tok} tokens`;
    document.getElementById('recModal').style.display='flex';
    mTab('q');
  }catch(e){alert('기록을 불러올 수 없습니다.');}
}
function closeModal(){document.getElementById('recModal').style.display='none';}
function mTab(tab){
  if(!_modalRec) return;
  const isQ=tab==='q';
  document.getElementById('mTabQ').style.cssText=isQ?'flex:1;padding:9px;font-size:.82rem;font-weight:700;background:#6366f1;color:#fff;border:none;cursor:pointer':'flex:1;padding:9px;font-size:.82rem;font-weight:700;background:#f1f5f9;color:#64748b;border:none;cursor:pointer';
  document.getElementById('mTabR').style.cssText=!isQ?'flex:1;padding:9px;font-size:.82rem;font-weight:700;background:#6366f1;color:#fff;border:none;cursor:pointer':'flex:1;padding:9px;font-size:.82rem;font-weight:700;background:#f1f5f9;color:#64748b;border:none;cursor:pointer';
  const text=isQ ? (extractUserQuery(_modalRec.full_prompt||'')||'(내용 없음)') : (_modalRec.full_response||'(내용 없음)');
  document.getElementById('modalContent').textContent=text;
}
document.getElementById('recModal').addEventListener('click',function(e){if(e.target===this)closeModal();});

async function refreshAll(){updateDashboard();updateChart();}
async function forcePurge(){
  if(!confirm(t('confirm_purge'))) return;
  try{await fetch('/api/purge',{method:'POST'});updateDashboard();}catch(e){alert(e);}
}
async function resetStats(){
  if(!confirm(t('confirm_reset'))) return;
  try{await fetch('/api/stats/reset',{method:'POST'});updateDashboard();updateChart();}catch(e){alert(e);}
}

// ── Settings UI Handler ──
let currentSettings = { mode: 'cold', standby_timeout_sec: 300 };

async function loadSettingsUI(){
  try{
    const res = await fetch('/api/settings').then(r=>r.json());
    if(res.settings){
      currentSettings = res.settings;
      selectMode(currentSettings.mode || 'cold', true);
      const input = document.getElementById('inputTimeout');
      if(input) input.value = currentSettings.standby_timeout_sec || 300;
    }
  }catch(e){}
}

function selectMode(m, updateRadio=true){
  currentSettings.mode = m;
  const isCold = m === 'cold';
  const optCold = document.getElementById('optCold');
  const optHot = document.getElementById('optHot');
  if(optCold) optCold.classList.toggle('selected', isCold);
  if(optHot) optHot.classList.toggle('selected', !isCold);
  if(updateRadio){
    const rCold = document.getElementById('radioCold');
    const rHot = document.getElementById('radioHot');
    if(rCold) rCold.checked = isCold;
    if(rHot) rHot.checked = !isCold;
  }
}

function setTimeoutVal(v){
  const input = document.getElementById('inputTimeout');
  if(input) input.value = v;
}

async function saveSettings(){
  const mode = currentSettings.mode || 'cold';
  const input = document.getElementById('inputTimeout');
  const timeout = parseInt(input ? input.value : '300', 10) || 300;
  try{
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: mode, standby_timeout_sec: timeout })
    }).then(r=>r.json());
    if(res.status === 'ok'){
      const alertEl = document.getElementById('saveAlert');
      if(alertEl){
        alertEl.style.display = 'inline-block';
        setTimeout(()=>{ alertEl.style.display = 'none'; }, 3000);
      }
      updateDashboard();
    }
  }catch(e){
    alert('설정 저장 실패: ' + e);
  }
}

// ── Boot ──
initChart();
updateSetupPanel();
updateDashboard();
loadSettingsUI();
</script>
</body>
</html>
"""

@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    return DASHBOARD_HTML.replace("__APP_VERSION__", __version__)
