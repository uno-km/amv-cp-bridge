# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
Copilot 365 FastMCP Server - Ephemeral Zero-Leak Edition
Antigravity 에이전트와 Microsoft 365 Copilot (Enterprise / Edu) 직결 MCP 서버.
질의 응답 완료 즉시 Edge 프로세스 트리를 강제 종료하여 로컬 메모리 누수 0MB를 엄격히 보장합니다.
"""

import sys
import os
import asyncio
import json
import urllib.error
import urllib.request
from typing import Literal, Optional
from mcp.server.fastmcp import FastMCP

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if package_root not in sys.path:
    sys.path.insert(0, package_root)

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from amv_cp_bridge.engine import CopilotEngine
except (ImportError, ValueError):
    from engine import CopilotEngine

mcp = FastMCP("copilot-bridge")
engine = CopilotEngine()

def _find_gateway_url() -> Optional[str]:
    """활성화된 amv-cp-bridge 게이트웨이 탐색 (11500 최우선)"""
    for port in [11500, 11501, 11553, 8080]:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
            with urllib.request.urlopen(req, timeout=1.2) as r:
                if r.status == 200:
                    data = json.loads(r.read().decode("utf-8", errors="replace"))
                    if data.get("gateway") == "amv-cp-bridge":
                        return f"http://127.0.0.1:{port}"
        except Exception:
            pass
    return None

MODE_PREFIXES = {
    "auto": "",
    "fast": "[Fast Mode: 핵심만 간결하게 요약하여 즉시 답변해줘]\n\n",
    "deep": "[DeepThink Mode: 단계별로 치밀하게 생각하여 완전한 논리적 근거와 함께 답변해줘]\n\n",
    "sol-quick": "[Sol Quick Mode: 빠르고 정확하게 핵심 답변만 제공해줘]\n\n",
    "sol-deep": "[Sol DeepThink Mode: 최고 수준의 논리적 추론을 단계별로 전개하고 반례와 경계조건을 함께 검증하여 답변해줘]\n\n",
}

@mcp.tool()
async def ask_copilot(
    prompt: str,
    mode: str = "auto",
) -> str:
    """Microsoft 365 Copilot (Enterprise / Edu 계정)에게 질문하고 답변을 받습니다.
    질문 처리 완료 즉시 브라우저를 자동 종료하여 로컬 메모리 0MB를 유지합니다.

    Args:
        prompt: 코파일럿에게 전달할 질문 또는 코드 작성 요청 프롬프트
        mode: 추론 모드 선택 - 'auto'(자동), 'fast'(빠름), 'deep'(깊게), 'sol-quick'(Sol 5.6 Quick), 'sol-deep'(Sol 5.6 Deep Thinking)
    """
    prefix = MODE_PREFIXES.get(mode, "")
    full_prompt = prefix + prompt

    # 1. 실행 중인 대시보드 게이트웨이가 있으면 대시보드 큐로 라우팅 (대시보드 실시간 표출)
    gw_url = _find_gateway_url()
    if gw_url:
        try:
            req_body = json.dumps({
                "model": "copilot-deepthink" if "deep" in mode else "copilot-standard",
                "deepthink": True if "deep" in mode else False,
                "messages": [{"role": "user", "content": full_prompt}]
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{gw_url}/v1/chat/completions",
                data=req_body,
                headers={
                    "Content-Type": "application/json",
                    "X-Bridge-Source": "mcp:antigravity",
                    "X-Client-App": "antigravity",
                    "User-Agent": "antigravity-mcp/1.0.0"
                },
                method="POST"
            )
            # 게이트웨이 요청은 비동기 루프 블로킹 방지를 위해 별도 스레드에서 실행
            loop = asyncio.get_running_loop()
            mcp_timeout = max(30.0, float(os.environ.get("COPILOT_MCP_TIMEOUT_SEC", "360")))
            def _call():
                with urllib.request.urlopen(req, timeout=mcp_timeout) as r:
                    return json.loads(r.read().decode())
            resp = await loop.run_in_executor(None, _call)
            return resp["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as he:
            detail = he.read().decode("utf-8", errors="replace") if he.fp else str(he)
            print(f"[!] Gateway HTTP {he.code} (이중 실행 방지를 위해 로컬 폴백 생략): {detail[:200]}", file=sys.stderr)
            return f"[오류 발생] 게이트웨이 HTTP {he.code}: {detail[:300]}"
        except urllib.error.URLError as ue:
            reason = getattr(ue, "reason", None)
            if isinstance(reason, ConnectionRefusedError):
                print(f"[!] Gateway unreachable, falling back to direct engine: {ue}", file=sys.stderr)
            else:
                # Timeout 등: 게이트웨이가 이미 Edge 프로필을 점유 처리 중일 수 있으므로 이중 실행 금지
                print(f"[!] Gateway request error (이중 Edge 충돌 방지): {ue}", file=sys.stderr)
                return f"[오류 발생] 코파일럿 게이트웨이 응답 지연/오류 (기존 세션 보호를 위해 중복 실행하지 않았습니다): {ue}"
        except TimeoutError as te:
            print(f"[!] Gateway timeout ({mcp_timeout}s) — 로컬 중복 실행 생략: {te}", file=sys.stderr)
            return f"[오류 발생] 코파일럿 게이트웨이 응답 시간 초과: {te}"
        except Exception as e:
            print(f"[!] Gateway call failed (이중 실행 방지): {e}", file=sys.stderr)
            return f"[오류 발생] 코파일럿 게이트웨이 호출 실패: {e}"

    # 2. 게이트웨이가 없거나 통신 실패 시 로컬 엔진으로 직결 폴백
    try:
        result = await engine.query(full_prompt, source="mcp:antigravity", client_app="antigravity")
        return result
    except Exception as e:
        print(f"[!] MCP ask_copilot 오류: {e}")
        return f"[오류 발생] 코파일럿 질의 실패: {e}"

@mcp.tool()
async def deepthink_copilot(prompt: str) -> str:
    """Microsoft 365 Copilot의 심층 추론(DeepThink Mode)을 호출하여
    복잡한 알고리즘 증명, 난해한 버그 디버깅, 아키텍처 설계를 수행합니다.

    Args:
        prompt: 복잡한 수학, 알고리즘, 시스템 설계 등의 심층 분석 요청
    """
    return await ask_copilot(prompt, mode="sol-deep")

@mcp.tool()
async def get_copilot_status() -> str:
    """로컬 엣지 브라우저(포트 9333/9334) 디버깅 세션 및 M365 코파일럿 상태를 점검합니다."""
    gw_url = _find_gateway_url()
    if gw_url:
        try:
            loop = asyncio.get_running_loop()
            def _fetch():
                with urllib.request.urlopen(f"{gw_url}/health", timeout=2.0) as r:
                    return json.loads(r.read().decode("utf-8", errors="replace"))
            data = await loop.run_in_executor(None, _fetch)
            return f"[상태 점검 · Gateway {gw_url}] {data.get('pool_status') or data}"
        except Exception:
            pass
    try:
        summary = engine.get_status_summary()
        return f"[상태 점검] {summary}"
    except Exception as e:
        return f"[연결 대기/오류]: 상태 점검 실패. 서버 로그를 확인하십시오."

def _print_startup_banner() -> None:
    """MCP 서버 시작 시 stderr에 상태 배너 출력 (stdout은 MCP JSON-RPC 전용)."""
    import datetime
    now = datetime.datetime.now().strftime("%H:%M:%S")
    lines = [
        "",
        "┌─────────────────────────────────────────┐",
        "│   AMV-CP-BRIDGE  MCP Server  ✓ 가동 중  │",
        f"│   시작 시각: {now}                    │",
        "│   Copilot 365 · DeepThink · FastMCP     │",
        "└─────────────────────────────────────────┘",
        "",
    ]
    for line in lines:
        print(line, file=sys.stderr, flush=True)


def run_server():
    _print_startup_banner()
    mcp.run()

if __name__ == "__main__":
    run_server()
