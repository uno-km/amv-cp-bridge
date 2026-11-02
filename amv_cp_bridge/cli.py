# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
Command Line Interface for amv-cp-bridge (`amv-cp-bridge` / `acb` / `c365`)
"""

import sys
import os
import argparse
import asyncio
import subprocess
import webbrowser

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

def cmd_status(args):
    """현재 워커 풀 상태 및 텔레메트리 사용량 점검"""
    from amv_cp_bridge.engine import CopilotEngine
    from amv_cp_bridge.telemetry_db import telemetry_db
    engine = CopilotEngine()
    print("=" * 65)
    print("⚡ amv-cp-bridge | Sovereign Worker Pool & Telemetry Status")
    print("=" * 65)
    print(engine.get_status_summary())
    for w in engine.workers:
        pids = w.get_listening_pids()
        print(f"  - [{w.name}] 포트 {w.port} 활성 PIDs: {pids if pids else 'None (0MB 회수됨)'}")
    print("-" * 65)
    
    # Telemetry Summary
    stats = telemetry_db.get_summary()
    t = stats["today"]
    w_stat = stats["week"]
    m = stats["month"]
    y = stats["year"]
    tot = stats["total"]
    print(f"📊 [텔레메트리 통계 DB]")
    print(f"  - 오늘 (Today)     : {t['queries']}회 | +{t['tokens']:,} 토큰 (평균 {t['avg_duration_ms']}ms)")
    print(f"  - 이번 주 (Week)   : {w_stat['queries']}회 | +{w_stat['tokens']:,} 토큰")
    print(f"  - 이번 달 (Month)  : {m['queries']}회 | +{m['tokens']:,} 토큰")
    print(f"  - 올해 누적 (Year) : {y['queries']}회 | +{y['tokens']:,} 토큰")
    print(f"  - 총 누적 절감     : {tot['queries']}회 성공 | +{tot['tokens']:,} 토큰 오프로드 (성공률 {tot['success_rate']}%)")
    print("=" * 65)

def cmd_purge(args):
    """디버깅 포트에 잔존하는 모든 Edge 프로세스 강제 일괄 소각"""
    from amv_cp_bridge.engine import CopilotEngine
    engine = CopilotEngine()
    print("[*] 포트 9333 / 9334 잔존 브라우저 프로세스 강제 정리 시작...")
    killed_count = 0
    for w in engine.workers:
        pids = w.get_listening_pids()
        for pid in pids:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(int(pid))], capture_output=True)
                print(f"[+] [{w.name}] PID {pid} 프로세스 트리 소각 완료")
                killed_count += 1
            except Exception as e:
                print(f"[-] [{w.name}] PID {pid} 종료 실패: {e}")
    if killed_count == 0:
        print("[+] 정리할 잔존 프로세스가 없습니다. (이미 0MB 클린 상태)")
    else:
        print(f"[+] 총 {killed_count}개 루트 프로세스 및 하위 트리 소각 완료.")

def cmd_reset(args):
    """로컬 텔레메트리 DB 통계 전량 삭제 초기화"""
    from amv_cp_bridge.telemetry_db import telemetry_db
    confirm = input("[!] 로컬 SQLite 텔레메트리 DB의 모든 사용 기록을 초기화하시겠습니까? (y/N): ")
    if confirm.lower() == 'y':
        telemetry_db.reset_all()
        print("[+] 모든 텔레메트리 기록이 성공적으로 삭제 초기화되었습니다.")
    else:
        print("[-] 초기화 취소됨.")

def cmd_ask(args):
    """터미널에서 직접 질의 수행 및 실시간 스트리밍 출력"""
    prompt = " ".join(args.prompt) if isinstance(args.prompt, list) else args.prompt
    if not prompt or not prompt.strip():
        print("[-] 질문할 프롬프트를 입력해 주세요. 예: amv-cp-bridge ask '양자역학 요약해줘'")
        sys.exit(1)

    if args.deep:
        prompt = f"[DeepThink Mode: 단계별로 치밀하게 생각하여 완전한 논리적 근거와 함께 답변해줘]\n\n{prompt}"

    print(f"\n[?] 질의 전송: {prompt[:80]}..." if len(prompt) > 80 else f"\n[?] 질의 전송: {prompt}")
    print("-" * 65)

    async def _run():
        from amv_cp_bridge.engine import CopilotEngine
        engine = CopilotEngine()
        async for chunk in engine.stream_query(prompt):
            sys.stdout.write(chunk)
            sys.stdout.flush()
        print("\n" + "-" * 65)
        print("[+] 응답 완료. 메모리 점유율 0MB로 자동 회수되었습니다.")

    asyncio.run(_run())

def cmd_dashboard(args):
    """게이트웨이 기동 및 기본 웹 브라우저로 실시간 Cyber 대시보드 자동 팝업"""
    import uvicorn
    try:
        from .gateway import app
    except (ImportError, ValueError):
        from amv_cp_bridge.gateway import app
    port = getattr(args, "port", 11500)
    host = getattr(args, "host", "0.0.0.0")
    url = f"http://localhost:{port}/dashboard"
    
    print("=" * 65)
    print(f"⚡ amv-cp-bridge | Cyber Telemetry Dashboard & Gateway")
    print(f"[*] 대시보드 접속 URL : {url}")
    print(f"[*] OpenAI API 엔드포인트: http://localhost:{port}/v1/chat/completions")
    print("=" * 65)

    # 1초 후 브라우저 자동 오픈
    def _open():
        time.sleep(1.2)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    import threading
    import time
    threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="info")

def cmd_gateway(args):
    """OpenAI 호환 REST API 게이트웨이 전용 실행"""
    import uvicorn
    try:
        from .gateway import app
    except (ImportError, ValueError):
        from amv_cp_bridge.gateway import app
    print(f"[GATEWAY] amv-cp-bridge REST API listening on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")

def cmd_serve(args):
    """FastMCP 표준 서버 구동"""
    try:
        from .mcp_server import mcp
    except (ImportError, ValueError):
        from amv_cp_bridge.mcp_server import mcp
    mcp.run(transport="stdio")

def cmd_selftest(args):
    """패키징 산출물 무결성 점검 (빌드 파이프라인 전용). 결과를 JSON 파일로 기록한다."""
    import importlib
    import json
    import traceback

    checks = {}

    def check(name, fn):
        try:
            value = fn()
            checks[name] = {"ok": True, "detail": str(value) if value is not None else ""}
        except BaseException:
            checks[name] = {"ok": False, "detail": traceback.format_exc()}

    for module in ("customtkinter", "PIL.Image", "pystray", "tkinterweb", "markdown2", "certifi",
                   "uvicorn", "fastapi", "mcp", "amv_cp_bridge.gui", "amv_cp_bridge.gateway",
                   "amv_cp_bridge.mcp_server", "amv_cp_bridge.updater"):
        check(f"import:{module}", lambda m=module: importlib.import_module(m) and None)

    def tk_widgets():
        import tkinter as tk
        import customtkinter
        from tkinterweb import HtmlFrame
        root = tk.Tk()
        root.withdraw()
        customtkinter.CTkLabel(root, text="selftest")
        frame = HtmlFrame(root, messages_enabled=False)
        frame.load_html("<p>selftest</p>")
        root.update()
        root.destroy()
    check("tk:widgets", tk_widgets)

    async def edge_over_cdp():
        import socket
        import tempfile
        from playwright.async_api import async_playwright
        from amv_cp_bridge.gui import _find_edge

        found, edge_path = _find_edge()
        if not found:
            raise RuntimeError("Microsoft Edge not found")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
            edge = subprocess.Popen([edge_path, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                                     "--headless=new", "--no-first-run", "--no-default-browser-check"])
            try:
                async with async_playwright() as pw:
                    last_error = None
                    for _ in range(40):
                        try:
                            browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                            break
                        except Exception as exc:
                            last_error = exc
                            await asyncio.sleep(0.5)
                    else:
                        raise RuntimeError(f"CDP connection failed: {last_error}")
                    context = browser.contexts[0] if browser.contexts else await browser.new_context()
                    page = await context.new_page()
                    await page.goto("data:text/html,<title>selftest</title>")
                    title = await page.title()
                    version = browser.version
                    await browser.close()
                    if title != "selftest":
                        raise RuntimeError(f"unexpected page title: {title!r}")
                    return version
            finally:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(edge.pid)], capture_output=True)
                edge.wait(timeout=15)
    check("playwright:edge_cdp", lambda: asyncio.run(edge_over_cdp()))

    ok = all(item["ok"] for item in checks.values())
    with open(args.out, "w", encoding="utf-8") as report:
        json.dump({"ok": ok, "checks": checks}, report, ensure_ascii=False, indent=2)
    sys.exit(0 if ok else 1)

def main():
    import multiprocessing
    multiprocessing.freeze_support()

    # PyInstaller --windowed sets sys.stdout/stderr to None
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    parser = argparse.ArgumentParser(
        prog="amv-cp-bridge",
        description="amv-cp-bridge: Sovereign Cognitive Offloading Suite for Microsoft 365 Copilot"
    )
    subparsers = parser.add_subparsers(dest="command", help="실행할 명령을 선택하십시오")

    # dashboard
    p_dash = subparsers.add_parser("dashboard", help="게이트웨이 기동 및 웹 대시보드 자동 열기")
    p_dash.add_argument("--host", default="127.0.0.1", help="바인딩 호스트 (기본: 127.0.0.1)")
    p_dash.add_argument("--port", type=int, default=11500, help="게이트웨이 포트 (기본: 11500)")

    # status
    p_status = subparsers.add_parser("status", help="워커 풀 메모리 상태 및 텔레메트리 DB 요약 점검")

    # purge
    p_purge = subparsers.add_parser("purge", help="잔존 프로세스 강제 일괄 소각 (0MB 회수)")

    # reset
    p_reset = subparsers.add_parser("reset", help="로컬 텔레메트리 DB 통계 전량 삭제 초기화")

    # ask
    p_ask = subparsers.add_parser("ask", help="터미널에서 직접 질의 수행")
    p_ask.add_argument("prompt", nargs="+", help="질문 내용")
    p_ask.add_argument("--deep", "--deepthink", action="store_true", help="GPT-5.6 Sol 딥씽크 모드 강제 적용")

    # gateway
    p_gateway = subparsers.add_parser("gateway", help="OpenAI 규격 REST API 게이트웨이 구동")
    p_gateway.add_argument("--host", default="127.0.0.1", help="바인딩 호스트 (기본: 127.0.0.1)")
    p_gateway.add_argument("--port", type=int, default=11500, help="게이트웨이 포트 (기본: 11500)")

    # serve
    p_serve = subparsers.add_parser("serve", help="FastMCP 서버 구동 (Cursor, Claude, Antigravity)")

    # selftest (build pipeline only)
    p_selftest = subparsers.add_parser("selftest")
    p_selftest.add_argument("--out", required=True)

    args = parser.parse_args()

    if args.command:
        from amv_cp_bridge.gui import close_boot_splash
        close_boot_splash()

    if args.command == "selftest":
        cmd_selftest(args)
    elif args.command == "dashboard":
        cmd_dashboard(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "purge":
        cmd_purge(args)
    elif args.command == "reset":
        cmd_reset(args)
    elif args.command == "ask":
        cmd_ask(args)
    elif args.command == "gateway":
        cmd_gateway(args)
    elif args.command == "serve":
        cmd_serve(args)
    else:
        # Default: launch native GUI window (WebView2 on Windows, WebKit on macOS)
        try:
            from .gui import launch_gui
        except (ImportError, ValueError):
            from amv_cp_bridge.gui import launch_gui
        launch_gui(host="127.0.0.1", port=11500)

if __name__ == "__main__":
    try:
        main()
    except Exception as _exc:
        import traceback
        from pathlib import Path as _P
        _log = _P.home() / ".amv_cp_bridge" / "crash.log"
        _log.parent.mkdir(parents=True, exist_ok=True)
        _log.write_text(traceback.format_exc(), encoding="utf-8")
        raise
