# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
CustomTkinter native GUI for amv-cp-bridge.
Pure Python — no browser, no WebView2, no proxy issues.
Windows / macOS compatible.
"""

import os
import sys
import socket
import subprocess
import threading
import time
import webbrowser
import urllib.request
import urllib.error
import json
import http.client

try:
    from . import updater
    from ._version import __version__
except (ImportError, ValueError):
    from amv_cp_bridge import updater
    from amv_cp_bridge._version import __version__


def close_boot_splash():
    """EXE 압축 해제 중 표시한 부트 화면을 닫는다. EXE가 아니면 아무 일도 하지 않는다."""
    try:
        import pyi_splash
        pyi_splash.close()
    except (ImportError, RuntimeError, OSError):
        pass


def _bring_to_front(window):
    """창을 맨 앞에 표시한다. 다른 창 사용을 막지 않도록 topmost는 잠시만 유지한다."""
    window.lift()
    window.attributes("-topmost", True)
    window.after(400, lambda: window.attributes("-topmost", False))
    window.focus_force()


def _find_icon_path() -> str:
    candidates = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(os.path.join(sys._MEIPASS, "amv-cp-bridge.ico"))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "amv-cp-bridge.ico"))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "amv-cp-bridge.ico"))
    for p in candidates:
        rp = os.path.normpath(p)
        if os.path.isfile(rp):
            return rp
    return ""


def _start_server(host: str, port: int):
    import traceback
    from pathlib import Path
    log_path = Path.home() / ".amv_cp_bridge" / "server_error.log"
    try:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        import uvicorn
        try:
            from .gateway import app
        except (ImportError, ValueError):
            from amv_cp_bridge.gateway import app
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except BaseException:
        # SystemExit(소켓 충돌)도 포함하여 모두 로그에 기록
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(traceback.format_exc(), encoding="utf-8")


def _fetch_json(url: str, timeout: float = 2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = r.read()
            if not data:
                return None
            return json.loads(data.decode())
    except Exception:
        return None


def _is_our_server(host: str, port: int) -> bool:
    """해당 포트가 amv-cp-bridge 게이트웨이인지 확인."""
    d = _fetch_json(f"http://{host}:{port}/health", timeout=1.0)
    return isinstance(d, dict) and d.get("gateway") == "amv-cp-bridge"


def _find_free_port(host: str, preferred: int) -> int:
    """preferred 포트부터 빈 포트를 탐색해 반환."""
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    return preferred


def _kill_port_process(port: int) -> bool:
    """지정 포트를 점유한 프로세스를 강제 종료 (Windows 전용). 성공 시 True."""
    if sys.platform != "win32":
        return False
    import subprocess
    try:
        r = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=6
        )
        killed = False
        for line in r.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1] if parts else ""
                if pid and pid.isdigit() and pid != "0":
                    subprocess.run(
                        ["taskkill", "/F", "/PID", pid],
                        capture_output=True, timeout=5
                    )
                    killed = True
        return killed
    except Exception:
        return False


def _find_edge() -> tuple:
    if sys.platform == "darwin":
        p = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
        return os.path.isfile(p), p
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return True, p
    return False, ""


# ── Splash Screen ─────────────────────────────────────────────
def _launch_splash(host: str, port: int):
    """순수 tkinter 스플래시: 단계별 진단 + 인라인 로그 에어리어."""
    import tkinter as tk
    from tkinter import scrolledtext

    actual_port = [port]          # 포트 충돌 시 자동 변경
    step_logs: list[str] = [""] * 6

    root = tk.Tk()
    root.title("amv-cp-bridge")

    W, H = 500, 600
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")
    root.resizable(False, False)
    root.configure(bg="#ffffff")

    ico = _find_icon_path()
    if ico:
        try:
            root.iconbitmap(ico)
        except Exception:
            pass

    PRIMARY, GREEN, RED, MUTED, BORDER = (
        "#6366f1", "#16a34a", "#dc2626", "#64748b", "#e2e8f0"
    )
    BG = "#ffffff"

    # ── 헤더 ──────────────────────────────────
    hdr = tk.Frame(root, bg=PRIMARY, height=82)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)

    hdr_inner = tk.Frame(hdr, bg=PRIMARY)
    hdr_inner.pack(expand=True)

    # 아이콘 이미지 (PIL로 .ico 로드)
    _photo = None
    if ico:
        try:
            from PIL import Image, ImageTk
            img = Image.open(ico).resize((34, 34), Image.LANCZOS)
            _photo = ImageTk.PhotoImage(img)
            tk.Label(hdr_inner, image=_photo, bg=PRIMARY).pack(side="left", padx=(0, 8), pady=14)
        except Exception:
            pass

    title_col = tk.Frame(hdr_inner, bg=PRIMARY)
    title_col.pack(side="left")
    tk.Label(title_col, text="amv-cp-bridge",
             bg=PRIMARY, fg="#ffffff",
             font=("Segoe UI", 15, "bold")).pack(anchor="w")
    tk.Label(title_col, text=f"v{__version__}  ·  Created by AMV Foundation",
             bg=PRIMARY, fg="#a5b4fc",
             font=("Segoe UI", 8)).pack(anchor="w")

    body = tk.Frame(root, bg=BG, padx=28)
    body.pack(fill="both", expand=True)

    tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(14, 4))

    hint_lbl = tk.Label(body,
                        text="각 항목을 클릭하면 아래 진단 로그가 표시됩니다.",
                        bg=BG, fg=MUTED, font=("Segoe UI", 8))
    hint_lbl.pack(anchor="w", pady=(0, 6))

    STEPS = [
        "필수 모듈 확인",
        "계정 설정 로드",
        "Microsoft Edge 탐색",
        "게이트웨이 서버 기동",
        "API 서버 연결 확인",
        "업데이트 확인",
    ]
    PCTS = [0, 17, 33, 50, 67, 83, 100]
    SPINNER = ["◐", "◓", "◑", "◒"]

    icon_lbls: list = []
    desc_lbls: list = []
    rows: list = []
    selected_idx = [-1]

    log_frame = tk.Frame(body, bg="#0f172a", bd=0)

    log_area = scrolledtext.ScrolledText(
        log_frame,
        bg="#0f172a", fg="#94a3b8",
        font=("Consolas", 8), bd=0, wrap="word",
        height=11,
        relief="flat",
        insertbackground="#94a3b8",
        selectbackground="#334155",
    )
    log_area.pack(fill="both", expand=True, padx=1, pady=1)
    log_area.tag_configure("ok",   foreground="#22c55e")
    log_area.tag_configure("warn", foreground="#f59e0b")
    log_area.tag_configure("err",  foreground="#ef4444")
    log_area.tag_configure("hdr",  foreground="#a5b4fc",
                            font=("Consolas", 8, "bold"))

    _log_visible = [False]

    def _show_log(idx: int):
        selected_idx[0] = idx
        # 행 배경 갱신
        for i, r in enumerate(rows):
            bg = "#ede9fe" if i == idx else "#f8fafc"
            r.configure(bg=bg)
            icon_lbls[i].configure(bg=bg)
            desc_lbls[i].configure(bg=bg)

        # 로그 에어리어 표시
        if not _log_visible[0]:
            log_frame.pack(fill="x", pady=(6, 0))
            _log_visible[0] = True

        log_area.configure(state="normal")
        log_area.delete("1.0", "end")
        content = step_logs[idx] if step_logs[idx] else (
            "(진행 중입니다)" if idx == _cur[0] else "(아직 실행되지 않은 단계입니다)")
        for line in content.split("\n"):
            if line.startswith("✓"):
                log_area.insert("end", line + "\n", "ok")
            elif line.startswith("⚠"):
                log_area.insert("end", line + "\n", "warn")
            elif line.startswith("✗") or line.startswith("ERR"):
                log_area.insert("end", line + "\n", "err")
            elif line.startswith("==="):
                log_area.insert("end", line + "\n", "hdr")
            else:
                log_area.insert("end", line + "\n")
        log_area.configure(state="disabled")
        log_area.yview_moveto(0)

    def _refresh_log_if_open(idx: int):
        """로그 에어리어가 열려있고 현재 선택된 항목이면 내용 갱신."""
        if _log_visible[0] and selected_idx[0] == idx:
            _show_log(idx)

    for i, step in enumerate(STEPS):
        row = tk.Frame(body, bg="#f8fafc", cursor="hand2", pady=5)
        row.pack(fill="x", pady=2)

        il = tk.Label(row, text="○", bg="#f8fafc", fg=MUTED,
                      font=("Segoe UI Symbol", 12), width=2, anchor="center",
                      cursor="hand2")
        il.pack(side="left", padx=(6, 4))
        dl = tk.Label(row, text=step, bg="#f8fafc", fg=MUTED,
                      font=("Segoe UI", 10), anchor="w", cursor="hand2")
        dl.pack(side="left", fill="x", expand=True)
        al = tk.Label(row, text="▸", bg="#f8fafc", fg="#c7d2fe",
                      font=("Segoe UI", 9), cursor="hand2")
        al.pack(side="right", padx=6)

        _i = i
        for w in (row, il, dl, al):
            w.bind("<Button-1>", lambda e, x=_i: _show_log(x))
            w.bind("<Enter>", lambda e, r=row, li=il, ld=dl, la=al:
                   [w.configure(bg="#f1f0ff") for w in (r, li, ld, la)])
            w.bind("<Leave>", lambda e, r=row, li=il, ld=dl, la=al, idx=_i:
                   [w.configure(bg="#ede9fe" if idx == selected_idx[0] else "#f8fafc")
                    for w in (r, li, ld, la)])

        icon_lbls.append(il)
        desc_lbls.append(dl)
        rows.append(row)

    tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(8, 6))

    # 프로그레스바
    bar_bg = tk.Frame(body, bg=BORDER, height=8)
    bar_bg.pack(fill="x")
    bar_fill = tk.Frame(bar_bg, bg=PRIMARY, height=8)
    bar_fill.place(x=0, y=0, relheight=1, relwidth=0)

    pct_var = tk.StringVar(value="0%")
    tk.Label(body, textvariable=pct_var, bg=BG, fg=MUTED,
             font=("Segoe UI", 8)).pack(pady=(4, 8))

    _cur = [-1]
    _spin_i = [0]
    _spinning = [False]
    _done = [False]

    def _spin():
        if _done[0] or not _spinning[0]:
            return
        idx = _cur[0]
        if 0 <= idx < len(icon_lbls):
            icon_lbls[idx].configure(text=SPINNER[_spin_i[0] % 4], fg=PRIMARY)
            _spin_i[0] += 1
        root.after(110, _spin)

    def _set_pct(pct: int):
        bar_fill.place(x=0, y=0, relheight=1, relwidth=pct / 100)
        pct_var.set(f"{pct}%")

    def _activate(idx: int):
        _cur[0] = idx
        _spin_i[0] = 0
        _spinning[0] = True
        desc_lbls[idx].configure(fg="#1e293b")
        _show_log(idx)
        root.after(0, _spin)

    def _finish(idx: int, ok: bool):
        _spinning[0] = False
        if ok is None:
            icon_lbls[idx].configure(text="!", fg="#d97706")
            desc_lbls[idx].configure(fg="#1e293b")
        else:
            icon_lbls[idx].configure(text="✓" if ok else "✗", fg=GREEN if ok else RED)
            desc_lbls[idx].configure(fg="#1e293b" if ok else RED)
        root.after(0, lambda: _refresh_log_if_open(idx))

    def _run():
        # ── Step 0: 모듈 확인 ──────────────────
        root.after(0, lambda: _activate(0))
        lines = ["=== 필수 모듈 확인 ==="]
        ok0 = True
        for mod in ["customtkinter", "uvicorn", "fastapi", "playwright", "sqlite3"]:
            try:
                m = __import__(mod)
                ver = getattr(m, "__version__", "n/a")
                lines.append(f"✓ {mod} ({ver})")
            except ImportError as e:
                lines.append(f"✗ {mod} 누락: {e}")
                ok0 = False
        step_logs[0] = "\n".join(lines)
        time.sleep(0.15)
        root.after(0, lambda v=ok0: [_finish(0, v), _set_pct(PCTS[1])])

        # ── Step 1: 계정 설정 ──────────────────
        time.sleep(0.05)
        root.after(0, lambda: _activate(1))
        lines = ["=== 계정 설정 로드 ==="]
        ok1 = True
        try:
            from pathlib import Path as _P
            cfg = _P.home() / ".amv_cp_bridge" / "accounts.json"
            lines.append(f"경로: {cfg}")
            if cfg.is_file():
                accs = json.loads(cfg.read_text(encoding="utf-8"))
                if isinstance(accs, list) and len(accs) > 0:
                    for a in accs:
                        lines.append(f"✓ [{a.get('name', '?')}] 포트 {a.get('port')} → {a.get('profile_dir')}")
                else:
                    lines.append("✓ 계정 구성이 비어 있어 기본 계정 구성을 생성합니다.")
            else:
                lines.append("✓ 첫 실행입니다. 기본 계정 구성을 생성합니다.")
        except Exception as e:
            lines.append(f"✗ 로드 실패: {e}")
            ok1 = False
        step_logs[1] = "\n".join(lines)
        time.sleep(0.12)
        root.after(0, lambda v=ok1: [_finish(1, v), _set_pct(PCTS[2])])

        # ── Step 2: Edge 탐색 ──────────────────
        time.sleep(0.05)
        root.after(0, lambda: _activate(2))
        lines = ["=== Microsoft Edge 탐색 ==="]
        found, edge_path = _find_edge()
        if sys.platform != "darwin":
            cands = [
                os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
            ]
            for c in cands:
                if c:
                    lines.append(f"{'✓' if os.path.isfile(c) else '○'} {c}")
        lines.append(f"\n{'✓ 발견' if found else '✗ 없음'}: {edge_path or '(경로 없음)'}")
        if not found:
            lines.append("  → https://www.microsoft.com/edge 에서 설치하십시오")
        step_logs[2] = "\n".join(lines)
        time.sleep(0.12)
        root.after(0, lambda v=found: [_finish(2, v), _set_pct(PCTS[3])])

        # ── Step 3: 서버 기동 ─────────────────────────────────────
        time.sleep(0.05)
        root.after(0, lambda: _activate(3))
        lines = ["=== 게이트웨이 서버 기동 ===",
                 f"요청 포트: {port}"]

        # 이미 우리 서버가 응답 중인지 확인
        if _is_our_server(host, port):
            lines.append(f"✓ amv-cp-bridge 서버 이미 실행 중 (포트 {port})")
            lines.append("  → 중복 기동 스킵")
            actual_port[0] = port
        else:
            # 포트 사용 중 여부 확인
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                in_use = s.connect_ex((host, port)) == 0

            if in_use:
                lines.append(f"⚠ 포트 {port}가 다른 프로세스에 선점됨 → 강제 종료 시도")
                killed = _kill_port_process(port)
                if killed:
                    time.sleep(0.8)
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s2:
                        still_in_use = _s2.connect_ex((host, port)) == 0
                else:
                    still_in_use = True
                if not still_in_use:
                    lines.append(f"✓ 포트 {port} 해제 완료 → 해당 포트 사용")
                    actual_port[0] = port
                else:
                    new_port = _find_free_port(host, port + 1)
                    lines.append(f"  → 포트 해제 실패, 대체 포트 {new_port} 사용")
                    actual_port[0] = new_port
            else:
                actual_port[0] = port
                lines.append(f"✓ 포트 {actual_port[0]} 사용 가능")

            from pathlib import Path as _P
            err_log = _P.home() / ".amv_cp_bridge" / "server_error.log"
            if err_log.exists():
                err_log.unlink()
            threading.Thread(
                target=_start_server, args=(host, actual_port[0]), daemon=True).start()
            lines.append(f"✓ uvicorn 스레드 기동 완료 (포트 {actual_port[0]})")
            lines.append(f"  에러 로그: {err_log}")

        step_logs[3] = "\n".join(lines)
        time.sleep(0.3)
        root.after(0, lambda: [_finish(3, True), _set_pct(PCTS[4])])

        # ── Step 4: API 응답 대기 ─────────────────────────────────
        time.sleep(0.05)
        root.after(0, lambda: _activate(4))
        p = actual_port[0]
        base = f"http://{host}:{p}"
        lines = ["=== API 서버 연결 확인 ===",
                 f"엔드포인트: {base}/health",
                 "최대 대기: 21초 (60회 × 0.35초)"]
        step_logs[4] = "\n".join(lines)
        root.after(0, lambda: _refresh_log_if_open(4))
        ok4 = False
        last_err = ""
        for attempt in range(60):
            time.sleep(0.35)
            try:
                with urllib.request.urlopen(f"{base}/health", timeout=2) as r:
                    data = r.read()
                    if data:
                        result = json.loads(data.decode())
                        if result.get("gateway") == "amv-cp-bridge":
                            lines.append(f"✓ 응답 수신 (시도 #{attempt + 1})")
                            lines.append(f"  상태: {result.get('status')}")
                            lines.append(f"  버전: {result.get('version')}")
                            ok4 = True
                            break
                        else:
                            last_err = f"포트 {p}가 다른 서비스에 점유됨: {str(data[:80])}"
                    else:
                        last_err = f"빈 응답 (시도 #{attempt + 1})"
            except urllib.error.URLError as e:
                last_err = f"URLError: {e.reason}"
            except json.JSONDecodeError as e:
                last_err = f"JSON 파싱 실패 (다른 서비스가 포트 점유 중): {e}"
            except Exception as e:
                last_err = str(e)

        if not ok4:
            lines.append(f"✗ 연결 실패 — 마지막 오류: {last_err}")
            from pathlib import Path as _P
            err_log = _P.home() / ".amv_cp_bridge" / "server_error.log"
            if err_log.exists():
                lines.append("\n=== server_error.log ===")
                lines.append(err_log.read_text(encoding="utf-8", errors="replace"))
            else:
                lines.append("server_error.log 없음")

        step_logs[4] = "\n".join(lines)
        root.after(0, lambda v=ok4: [_finish(4, v), _set_pct(PCTS[5])])

        # ── Step 5: 업데이트 확인 ─────────────────────────────────
        time.sleep(0.05)
        root.after(0, lambda: _activate(5))
        try:
            ok5 = _check_updates()
        except Exception as exc:
            _log_update(f"⚠ 업데이트 확인 중 오류: {exc!r}")
            ok5 = None
        _done[0] = True
        root.after(0, lambda v=ok5: [_finish(5, v), _set_pct(100)])
        time.sleep(0.6 if ok5 else 2.5)
        root.after(0, lambda: _open_main(ok4, actual_port[0]))

    def _log_update(line: str):
        step_logs[5] = f"{step_logs[5]}\n{line}" if step_logs[5] else line
        root.after(0, lambda: _refresh_log_if_open(5))

    def _ask_on_ui(title: str, headline: str, notes: str, primary: str, secondary: str = "") -> bool:
        """UI 스레드에 대화상자를 띄우고 사용자의 선택을 기다린다."""
        chosen = [False]
        answered = threading.Event()
        root.after(0, lambda: _release_dialog(title, headline, notes, primary, secondary, chosen, answered))
        answered.wait()
        return chosen[0]

    def _release_dialog(title, headline, notes, primary, secondary, chosen, answered):
        dlg = tk.Toplevel(root)
        dlg.title(title)
        dlg.configure(bg=BG)
        dlg.transient(root)
        dw, dh = 460, 420
        beside = min(root.winfo_rootx() + W + 10, sw - dw - 10)
        dlg.geometry(f"{dw}x{dh}+{beside}+{root.winfo_rooty()}")
        dlg.resizable(False, False)

        def close(result: bool):
            chosen[0] = result
            dlg.grab_release()
            dlg.destroy()
            answered.set()

        tk.Label(dlg, text=headline, bg=BG, fg="#1e293b", font=("Segoe UI", 11, "bold"),
                 wraplength=dw - 40, justify="left").pack(anchor="w", padx=20, pady=(18, 6))
        tk.Label(dlg, text="변경 사항", bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=20)

        btns = tk.Frame(dlg, bg=BG)
        btns.pack(side="bottom", fill="x", padx=20, pady=14)
        tk.Button(btns, text=primary, bg=PRIMARY, fg="#ffffff", activebackground="#4f46e5",
                  activeforeground="#ffffff", relief="flat", padx=16, pady=5,
                  font=("Segoe UI", 9, "bold"), cursor="hand2",
                  command=lambda: close(True)).pack(side="right")
        if secondary:
            tk.Button(btns, text=secondary, bg=BORDER, fg="#334155", relief="flat", padx=16, pady=5,
                      font=("Segoe UI", 9), cursor="hand2",
                      command=lambda: close(False)).pack(side="right", padx=(0, 8))

        box = scrolledtext.ScrolledText(dlg, bg="#f8fafc", fg="#1e293b", font=("Segoe UI", 9),
                                        bd=0, wrap="word", relief="flat", padx=10, pady=8)
        box.pack(fill="both", expand=True, padx=20, pady=(4, 0))
        box.insert("end", updater.format_notes(notes) or "(릴리스 노트가 없습니다)")
        box.configure(state="disabled")

        dlg.bind("<Return>", lambda e: close(True))
        dlg.bind("<Escape>", lambda e: close(False))
        dlg.protocol("WM_DELETE_WINDOW", lambda: close(False))
        dlg.grab_set()
        dlg.lift()
        dlg.focus_force()

    def _check_updates():
        _log_update("=== 업데이트 확인 ===")
        _log_update(f"현재 버전: v{__version__}")
        ok = True

        if updater.needs_release_notes():
            _log_update(f"v{__version__} 릴리스 노트 조회 중")
            try:
                installed = updater.fetch_release_for_version(__version__)
                _log_update("✓ 릴리스 노트 수신")
                _ask_on_ui("설치 완료", f"v{__version__} 설치가 완료되었습니다.", installed.notes, "확인")
                updater.mark_version_seen()
            except (updater.UpdateError, OSError) as exc:
                _log_update(f"⚠ 릴리스 노트 조회 실패: {exc}")
                _log_update(f"  → {updater.RELEASES_PAGE}")
                ok = None

        _log_update(f"최신 버전 조회: {updater.RELEASES_API}/latest")
        try:
            latest = updater.fetch_latest_release()
        except updater.UpdateError as exc:
            _log_update(f"⚠ 버전 확인 실패: {exc}")
            _log_update("  → 현재 버전으로 계속 진행합니다.")
            return None
        _log_update(f"최신 버전: v{latest.version}")

        if not updater.is_newer(latest.version, __version__):
            _log_update("✓ 최신 버전을 사용 중입니다.")
            return ok

        _log_update(f"⚠ 새 버전 v{latest.version}이 있습니다. 사용자 선택을 기다립니다.")
        accepted = _ask_on_ui(
            "업데이트 안내",
            f"새 버전 v{latest.version}이 있습니다. (현재 v{__version__})\n업데이트하시겠습니까?",
            latest.notes, "업데이트", "다음에 하기")
        if not accepted:
            _log_update("다음에 하기 선택 → 현재 버전으로 계속 진행합니다.")
            return ok

        _log_update("업데이트 선택 → 재설치 명령을 실행합니다.")
        try:
            updater.launch_reinstall()
        except (updater.UpdateError, OSError, subprocess.SubprocessError) as exc:
            _log_update(f"✗ 재설치 명령 실행 실패: {exc}")
            return None
        _log_update("✓ 재설치 창을 열었습니다. 프로그램을 종료합니다.")
        time.sleep(0.8)
        os._exit(0)

    def _open_main(server_ok: bool, resolved_port: int):
        root.destroy()
        _launch_main_gui(host, resolved_port, server_ok)

    _bring_to_front(root)
    root.update()
    close_boot_splash()
    threading.Thread(target=_run, daemon=True).start()
    root.mainloop()


# ── Main GUI ──────────────────────────────────────────────────
def _launch_main_gui(host: str, port: int, server_ok: bool = True):
    import customtkinter as ctk

    BASE = f"http://{host}:{port}"

    TEXTS = {
        "ko": dict(
            tab_dash="📊 대시보드", tab_usage="📈 사용량", tab_howto="📖 사용방법", tab_about="🙋 만든이",
            lbl_today="오늘", lbl_week="이번 주", lbl_month="이번 달", lbl_year="올해",
            tokens="토큰",
            idle="● 대기 중", busy="● 처리 중", connecting="● 연결 중...",
            worker_busy="작업 중", worker_ok="연결됨", worker_unknown="연결 확인 전", worker_login="로그인 필요",
            btn_connect="계정 연결",
            btn_purge="🧹 메모리 정리", btn_reset="🗑 통계 초기화",
            btn_open="🌐 브라우저로 열기",
            confirm_purge="Edge 잔여 프로세스를 정리하시겠습니까?",
            confirm_reset="모든 사용 기록을 삭제하시겠습니까?",
            no_data="기록 없음",
            server_wait="서버 연결 대기 중...",
            ok="성공", fail="실패",
            card_workers="계정 상태", card_task="현재 작업",
            card_queue="실시간 요청 큐 · 라우팅 현황",
            hist_title="최근 사용 기록 (20건)", howto_title="사용 방법",
            ht_1="1. Microsoft Edge에서 Copilot 로그인\n   → https://m365.cloud.microsoft/chat",
            ht_2="2. 계정 설정 파일 편집\n   → ~/.amv_cp_bridge/accounts.json",
            ht_3="3. REST API 호출\n   → POST http://localhost:{port}/v1/chat/completions".format(port=port),
            ht_4="4. MCP 서버 (Claude Desktop / Cursor)\n   → amv-cp-bridge serve",
            ht_5="5. 브라우저 확장프로그램\n   → Releases에서 amv-cp-bridge-extension.zip 다운로드 후 압축 해제\n   → chrome://extensions → 개발자 모드 → 압축해제된 폴더 로드",
            ht_modes="추론 모드: 자동 / 빠름 / 깊게 / Sol Quick / Sol Deep Thinking",
            ab_desc="M365 Copilot을 로컬 API로 연결하는 브릿지입니다.",
            ab_site="🌐  웹사이트", ab_gh="🐙  GitHub", ab_blog="✍️  블로그", ab_coffee="☕  커피 한 잔",
            ab_license="Apache-2.0 OR Commercial License\nCopyright © 2026 Eunho Kim / AMEVA Foundation",
            flag_btn="🇺🇸 EN",
        ),
        "en": dict(
            tab_dash="📊 Dashboard", tab_usage="📈 Usage", tab_howto="📖 How to Use", tab_about="🙋 About",
            lbl_today="Today", lbl_week="This Week", lbl_month="This Month", lbl_year="This Year",
            tokens="tokens",
            idle="● Idle", busy="● Processing", connecting="● Connecting...",
            worker_busy="Busy", worker_ok="Connected", worker_unknown="Not checked", worker_login="Sign-in required",
            btn_connect="Connect",
            btn_purge="🧹 Purge Memory", btn_reset="🗑 Reset Stats",
            btn_open="🌐 Open in Browser",
            confirm_purge="Purge all Edge processes?",
            confirm_reset="Delete all usage records?",
            no_data="No records",
            server_wait="Waiting for server...",
            ok="OK", fail="Fail",
            card_workers="Account Status", card_task="Current Task",
            card_queue="Live Request Queue · Routing",
            hist_title="Recent Records (20)", howto_title="How to Use",
            ht_1="1. Sign in to Copilot in Microsoft Edge\n   → https://m365.cloud.microsoft/chat",
            ht_2="2. Edit account config\n   → ~/.amv_cp_bridge/accounts.json",
            ht_3="3. Call the REST API\n   → POST http://localhost:{port}/v1/chat/completions".format(port=port),
            ht_4="4. MCP Server (Claude Desktop / Cursor)\n   → amv-cp-bridge serve",
            ht_5="5. Browser Extension\n   → Download amv-cp-bridge-extension.zip from Releases and extract it\n   → chrome://extensions → Developer mode → Load unpacked",
            ht_modes="Modes: Auto / Fast / Deep / Sol Quick / Sol Deep Thinking",
            ab_desc="A bridge that exposes M365 Copilot as a local API.",
            ab_site="🌐  Website", ab_gh="🐙  GitHub", ab_blog="✍️  Blog", ab_coffee="☕  Buy Me a Coffee",
            ab_license="Apache-2.0 OR Commercial License\nCopyright © 2026 Eunho Kim / AMEVA Foundation",
            flag_btn="🇰🇷 KO",
        ),
    }

    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")

    app_root = ctk.CTk()
    app_root.title(f"amv-cp-bridge  :{port}")
    app_root.geometry("960x660")
    app_root.minsize(800, 560)

    ico_path = _find_icon_path()
    if ico_path:
        try:
            app_root.iconbitmap(ico_path)
        except Exception:
            pass

    lang_var = {"lang": "ko"}

    C = dict(
        bg="#f0f4ff", card="#ffffff", border="#e2e8f0",
        primary="#6366f1", primary_lt="#ede9fe",
        green="#16a34a", green_lt="#dcfce7",
        red="#dc2626", red_lt="#fee2e2",
        yellow_lt="#fef9c3", yellow="#854d0e",
        muted="#64748b", text="#1e293b",
    )

    def T(k):
        return TEXTS[lang_var["lang"]].get(k, k)

    # ── Top Bar ──────────────────────────────────────────────────
    topbar = ctk.CTkFrame(app_root, fg_color="#ffffff", corner_radius=0, height=52,
                          border_width=1, border_color=C["border"])
    topbar.pack(fill="x", side="top")
    topbar.pack_propagate(False)

    ctk.CTkLabel(topbar, text="⚡ amv-cp-bridge",
                 font=ctk.CTkFont(family="Pretendard", size=15, weight="bold"),
                 text_color=C["primary"]).pack(side="left", padx=16, pady=10)
    ctk.CTkLabel(topbar, text=f"v{__version__}",
                 font=ctk.CTkFont(size=11), fg_color=C["primary_lt"],
                 text_color=C["primary"], corner_radius=99,
                 width=50, height=20).pack(side="left", pady=10)
    # 실제 포트 표시 (기본 포트와 다를 경우 시각적으로 구분)
    if port != 11500:
        ctk.CTkLabel(topbar, text=f":{port}",
                     font=ctk.CTkFont(size=10), fg_color=C["yellow_lt"],
                     text_color=C["yellow"], corner_radius=99,
                     width=50, height=20).pack(side="left", padx=(4, 0), pady=10)

    status_badge = ctk.CTkLabel(
        topbar,
        text=T("idle") if server_ok else T("connecting"),
        font=ctk.CTkFont(size=11, weight="bold"),
        fg_color=C["green_lt"] if server_ok else C["yellow_lt"],
        text_color=C["green"] if server_ok else C["yellow"],
        corner_radius=99, padx=10, pady=4)
    status_badge.pack(side="right", padx=8, pady=10)

    lang_btn = ctk.CTkButton(topbar, text="🇺🇸 EN", width=68, height=28,
                              fg_color=C["border"], text_color=C["muted"],
                              hover_color="#e2e8f0", corner_radius=8,
                              font=ctk.CTkFont(size=11))
    lang_btn.pack(side="right", padx=4, pady=10)

    # ── Tab View ────────────────────────────────────────────────
    tab_frame = ctk.CTkTabview(app_root, fg_color=C["bg"],
                               segmented_button_fg_color="#e8edf5",
                               segmented_button_selected_color=C["primary"],
                               segmented_button_selected_hover_color="#4f46e5",
                               segmented_button_unselected_color="#e8edf5",
                               segmented_button_unselected_hover_color="#d4dbea",
                               text_color="#334155",
                               text_color_disabled="#8898aa",
                               border_width=0)
    tab_frame.pack(fill="both", expand=True)

    for n in ["📊 대시보드", "📈 사용량", "📖 사용방법", "🙋 만든이"]:
        tab_frame.add(n)

    def make_card(parent, **kw):
        return ctk.CTkFrame(parent, fg_color="#ffffff", corner_radius=14,
                            border_width=1, border_color=C["border"], **kw)

    def card_title(parent, text):
        lbl = ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=12, weight="bold"),
                           text_color=C["muted"])
        lbl.pack(anchor="w", padx=16, pady=(12, 0))
        ctk.CTkFrame(parent, height=1, fg_color=C["border"]).pack(fill="x", padx=16, pady=(6, 0))
        return lbl

    # ══ TAB 1: 대시보드 ══════════════════════════════════════════
    t1 = tab_frame.tab("📊 대시보드")
    t1.configure(fg_color=C["bg"])

    stat_frame = ctk.CTkFrame(t1, fg_color="transparent")
    stat_frame.pack(fill="x", padx=12, pady=(10, 0))
    stat_frame.columnconfigure((0, 1, 2, 3), weight=1, uniform="col")

    stat_refs = {}
    for i, key in enumerate(["today", "week", "month", "year"]):
        c = make_card(stat_frame)
        c.grid(row=0, column=i, padx=5, pady=5, sticky="ew")
        lbl = ctk.CTkLabel(c, text=T(f"lbl_{key}"),
                           font=ctk.CTkFont(size=10, weight="bold"), text_color=C["muted"])
        lbl.pack(anchor="w", padx=14, pady=(10, 0))
        val = ctk.CTkLabel(c, text="0",
                           font=ctk.CTkFont(size=28, weight="bold"), text_color=C["text"])
        val.pack(anchor="w", padx=14)
        sub = ctk.CTkLabel(c, text="0 tokens",
                           font=ctk.CTkFont(size=10), text_color=C["muted"])
        sub.pack(anchor="w", padx=14, pady=(0, 10))
        stat_refs[key] = (lbl, val, sub)

    dual = ctk.CTkFrame(t1, fg_color="transparent")
    dual.pack(fill="x", padx=12, pady=(8, 0))
    dual.columnconfigure((0, 1), weight=1, uniform="dual")

    wcard = make_card(dual)
    wcard.grid(row=0, column=0, padx=(0, 4), pady=4, sticky="nsew")
    wcard_title_lbl = card_title(wcard, "계정 상태")
    workers_container = ctk.CTkFrame(wcard, fg_color="transparent")
    workers_container.pack(fill="both", expand=True, padx=12, pady=(8, 12))
    worker_widgets = {}
    server_wait_lbl = ctk.CTkLabel(workers_container, text=T("server_wait"),
                                   text_color=C["muted"], font=ctk.CTkFont(size=11))
    server_wait_lbl.pack(anchor="w", padx=4, pady=8)

    tcard = make_card(dual)
    tcard.grid(row=0, column=1, padx=(4, 0), pady=4, sticky="nsew")
    tcard_title_lbl = card_title(tcard, "현재 작업")
    task_label = ctk.CTkLabel(tcard, text="대기 중", text_color=C["muted"],
                              font=ctk.CTkFont(size=11), wraplength=320, justify="left")
    task_label.pack(anchor="w", padx=16, pady=10)

    btn_row = ctk.CTkFrame(t1, fg_color="transparent")
    btn_row.pack(fill="x", padx=12, pady=(8, 4))

    def do_purge():
        from tkinter import messagebox
        if messagebox.askyesno("메모리 정리", T("confirm_purge")):
            try:
                urllib.request.urlopen(
                    urllib.request.Request(f"{BASE}/api/purge", method="POST"), timeout=3)
            except Exception:
                pass

    def do_reset():
        from tkinter import messagebox
        if messagebox.askyesno("통계 초기화", T("confirm_reset")):
            try:
                urllib.request.urlopen(
                    urllib.request.Request(f"{BASE}/api/stats/reset", method="POST"), timeout=3)
                messagebox.showinfo("완료", "모든 사용 기록이 초기화되었습니다.")
            except Exception as e:
                messagebox.showerror("초기화 실패", f"서버가 응답하지 않습니다.\n{e}")

    purge_btn = ctk.CTkButton(btn_row, text=T("btn_purge"), command=do_purge,
                              fg_color=C["border"], text_color=C["muted"], hover_color="#e2e8f0",
                              corner_radius=8, font=ctk.CTkFont(size=12))
    purge_btn.pack(side="left", padx=(0, 6))
    reset_btn = ctk.CTkButton(btn_row, text=T("btn_reset"), command=do_reset,
                              fg_color=C["red_lt"], text_color=C["red"], hover_color="#fecaca",
                              corner_radius=8, font=ctk.CTkFont(size=12))
    reset_btn.pack(side="left", padx=(0, 6))
    open_btn = ctk.CTkButton(btn_row, text=T("btn_open"),
                             command=lambda: webbrowser.open(f"{BASE}/dashboard"),
                             fg_color=C["primary_lt"], text_color=C["primary"], hover_color="#ddd6fe",
                             corner_radius=8, font=ctk.CTkFont(size=12))
    open_btn.pack(side="left")

    # 태스크 큐 패널
    qcard = make_card(t1)
    qcard.pack(fill="x", padx=12, pady=(6, 4))
    qcard_title_lbl = card_title(qcard, "실시간 요청 큐 · 라우팅 현황")
    queue_scroll = ctk.CTkScrollableFrame(qcard, fg_color=C["bg"], height=100, corner_radius=8)
    queue_scroll.pack(fill="x", padx=10, pady=(4, 10))
    ctk.CTkLabel(queue_scroll, text="작업이 들어오면 여기에 실시간으로 표시됩니다.",
                 font=ctk.CTkFont(size=10), text_color=C["muted"]).pack(pady=10)

    # ══ TAB 2: 사용량 ════════════════════════════════════════════
    t2 = tab_frame.tab("📈 사용량")
    t2.configure(fg_color=C["bg"])
    hist_card = make_card(t2)
    hist_card.pack(fill="both", expand=True, padx=12, pady=10)
    hist_title_lbl = card_title(hist_card, "최근 사용 기록 (20건)")
    hist_scroll = ctk.CTkScrollableFrame(hist_card, fg_color="#f8f9ff", corner_radius=8)
    hist_scroll.pack(fill="both", expand=True, padx=10, pady=(6, 10))
    hist_no_data = ctk.CTkLabel(hist_scroll, text="서버 연결 대기 중...",
                                font=ctk.CTkFont(size=11), text_color=C["muted"])
    hist_no_data.pack(pady=20)

    _hist_row_widgets: list = []  # (frame, record_id) 목록

    # ── 모달 오버레이 ──────────────────────────────────────────
    _modal_ref: list = [None]   # 현재 열린 모달 프레임 (1개만 허용)

    try:
        import markdown2 as _md2
        _has_md2 = True
    except ImportError:
        _has_md2 = False

    try:
        from tkinterweb import HtmlFrame as _HtmlFrame
        _has_tkw = True
    except ImportError:
        _has_tkw = False

    def _md_to_html(text: str) -> str:
        if _has_md2:
            html_body = _md2.markdown(text, extras=["fenced-code-blocks", "tables", "strike",
                                                     "code-friendly", "smarty-pants"])
        else:
            import html as _html
            html_body = "<pre>" + _html.escape(text) + "</pre>"
        css = """
:root{--primary:#6366f1;--primary-lt:#ede9fe;--bg:#ffffff;--bg2:#f8faff;
  --text:#1e293b;--muted:#64748b;--border:#e2e8f0;--green:#16a34a;--red:#dc2626}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;font-size:13.5px;
  color:var(--text);background:var(--bg);padding:18px 22px;line-height:1.72;
  -webkit-font-smoothing:antialiased}
h1,h2,h3,h4{font-weight:700;margin:1.1em 0 .45em;letter-spacing:-.3px}
h1{font-size:1.5em;color:var(--primary)}
h2{font-size:1.25em;color:#3730a3;border-bottom:2px solid var(--primary-lt);padding-bottom:4px}
h3{font-size:1.1em;color:#4338ca}
p{margin:.6em 0}
a{color:var(--primary);text-decoration:none}a:hover{text-decoration:underline}
strong{font-weight:700}em{font-style:italic}
code{background:#f1f5f9;border:1px solid #dde4ef;border-radius:5px;
  padding:1px 5px;font-family:'Cascadia Code','Consolas',monospace;font-size:12px;
  color:#c026d3}
pre{background:#0f172a;border-radius:10px;padding:14px 16px;overflow-x:auto;margin:.8em 0}
pre code{background:none;border:none;padding:0;color:#e2e8f0;font-size:12.5px;line-height:1.6}
.codehilite,pre.highlight{background:#0f172a}
table{border-collapse:collapse;width:100%;margin:.8em 0;border-radius:8px;overflow:hidden}
thead{background:linear-gradient(135deg,#6366f1,#8b5cf6)}
thead th{color:#fff;font-weight:600;padding:9px 13px;font-size:12.5px}
td{border:1px solid var(--border);padding:8px 13px;vertical-align:top;font-size:13px}
tr:nth-child(even) td{background:#f8faff}
blockquote{border-left:4px solid var(--primary);background:var(--primary-lt);
  margin:.7em 0;padding:10px 14px;border-radius:0 8px 8px 0;color:#3730a3}
ul,ol{padding-left:22px;margin:.5em 0}li{margin:.25em 0}
li::marker{color:var(--primary)}
hr{border:none;border-top:1.5px solid var(--border);margin:1.2em 0}
del{color:var(--muted);text-decoration:line-through}
img{max-width:100%;border-radius:8px}
"""
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<style>{css}</style></head><body>{html_body}</body></html>"
        )

    def _make_katex_html(query_text: str, response_text: str) -> str:
        import html as _html
        q_esc = _html.escape(query_text or "")
        resp_body = ""
        if _has_md2:
            try:
                resp_body = _md2.markdown(response_text or "",
                                          extras=["fenced-code-blocks", "tables", "strike", "code-friendly"])
            except Exception:
                resp_body = "<pre>" + _html.escape(response_text or "") + "</pre>"
        else:
            resp_body = "<pre>" + _html.escape(response_text or "") + "</pre>"
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>amv-cp-bridge 응답 뷰어</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.22/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.22/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.22/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body,{{delimiters:[{{left:'$$',right:'$$',display:true}},{{left:'$',right:'$',display:false}},{{left:'\\\\(',right:'\\\\)',display:false}},{{left:'\\\\[',right:'\\\\]',display:true}}]}})">
</script>
<style>
:root{{--primary:#6366f1;--bg:#ffffff;--bg2:#f8faff;--text:#1e293b;--muted:#64748b;--border:#e2e8f0}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;color:var(--text);
  background:#f1f5f9;padding:0;}}
.query-box{{background:#e0e7ff;border-left:4px solid var(--primary);padding:14px 18px;
  margin-bottom:0;font-size:13px;color:#3730a3;white-space:pre-wrap}}
.query-label{{font-size:10px;font-weight:700;color:var(--primary);letter-spacing:.5px;
  margin-bottom:6px;text-transform:uppercase}}
.response-box{{background:var(--bg);padding:22px 26px;min-height:calc(100vh - 80px)}}
h1,h2,h3,h4{{font-weight:700;margin:1em 0 .4em}}
h2{{color:#3730a3;border-bottom:2px solid #e0e7ff;padding-bottom:4px}}
code{{background:#f1f5f9;border:1px solid #dde4ef;border-radius:4px;padding:1px 5px;
  font-family:'Cascadia Code','Consolas',monospace;font-size:12px;color:#c026d3}}
pre{{background:#0f172a;border-radius:8px;padding:14px;overflow-x:auto;margin:.8em 0}}
pre code{{background:none;border:none;color:#e2e8f0;font-size:12.5px}}
table{{border-collapse:collapse;width:100%;margin:.8em 0}}
thead{{background:linear-gradient(135deg,#6366f1,#8b5cf6)}}
thead th{{color:#fff;padding:8px 12px;font-size:12.5px}}
td{{border:1px solid var(--border);padding:7px 12px}}
tr:nth-child(even) td{{background:#f8faff}}
blockquote{{border-left:4px solid var(--primary);background:#ede9fe;
  padding:10px 14px;border-radius:0 8px 8px 0;color:#3730a3;margin:.7em 0}}
ul,ol{{padding-left:22px;margin:.5em 0}}
p{{margin:.6em 0}}
</style>
</head><body>
<div class="query-box"><div class="query-label">질의</div>{q_esc}</div>
<div class="response-box">{resp_body}</div>
</body></html>"""

    def _close_modal():
        if _modal_ref[0] is not None:
            try:
                _modal_ref[0].destroy()
            except Exception:
                pass
            _modal_ref[0] = None

    def _open_modal(record_id: int):
        _close_modal()
        import tkinter as _tk
        from pathlib import Path as _P

        # DB에서 full 레코드 조회
        try:
            from .telemetry_db import telemetry_db as _tdb
        except (ImportError, ValueError):
            from amv_cp_bridge.telemetry_db import telemetry_db as _tdb
        rec = _tdb.get_record_full(record_id)

        # ── 오버레이 (전체 창 덮기) ──────────────────────────
        overlay = _tk.Frame(app_root, bg="#1e293b")
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        overlay.bind("<Button-1>", lambda e: _close_modal())
        _modal_ref[0] = overlay

        # ── 카드 ──────────────────────────────────────────────
        card = ctk.CTkFrame(overlay, fg_color="#ffffff", corner_radius=16,
                            border_width=1, border_color=C["border"])
        card.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.88, relheight=0.88)
        card.bind("<Button-1>", lambda e: "break")
        card.lift()

        # X 버튼 (좌상단)
        close_btn = ctk.CTkButton(card, text="✕", width=28, height=28,
                                  fg_color=C["border"], text_color=C["muted"],
                                  hover_color="#e2e8f0", corner_radius=8,
                                  font=ctk.CTkFont(size=12, weight="bold"),
                                  command=_close_modal)
        close_btn.place(x=8, y=8)

        # 메타 헤더
        src = rec.get("source", "api")
        src_label = SOURCE_LABELS.get(src, src)
        src_color = SOURCE_COLORS.get(src, C["muted"])
        dur = rec.get("duration_ms", 0)
        tok = rec.get("tokens_est", 0)
        ts  = rec.get("time_str", "")

        meta_bar = ctk.CTkFrame(card, fg_color="#f8faff", corner_radius=0, height=38)
        meta_bar.pack(fill="x", padx=0, pady=(44, 0))
        meta_bar.pack_propagate(False)
        ctk.CTkLabel(meta_bar, text=src_label,
                     font=ctk.CTkFont(size=9, weight="bold"),
                     fg_color=src_color, text_color="#ffffff",
                     corner_radius=4, padx=6, pady=2).pack(side="left", padx=10, pady=8)
        ctk.CTkLabel(meta_bar, text=f"🕐 {ts}   ⚡ {dur/1000:.1f}s   🔤 {tok:,} tokens",
                     font=ctk.CTkFont(size=10), text_color=C["muted"]).pack(side="left")

        # 탭: 질의 / 응답
        nb = ctk.CTkTabview(card, fg_color="#ffffff",
                            segmented_button_fg_color="#f1f5f9",
                            segmented_button_selected_color=C["primary"],
                            segmented_button_selected_hover_color="#4f46e5",
                            segmented_button_unselected_color="#f1f5f9",
                            segmented_button_unselected_hover_color="#e0e7ff",
                            border_width=0, height=28)
        nb.pack(fill="both", expand=True, padx=0, pady=0)
        nb.add("📝 질의")
        nb.add("💬 응답")

        def _make_content_area(parent, md_text: str):
            if _has_tkw and _has_md2:
                try:
                    hf = _HtmlFrame(parent, messages_enabled=False, vertical_scrollbar=True)
                    hf.pack(fill="both", expand=True, padx=4, pady=4)
                    hf.load_html(_md_to_html(md_text or "(내용 없음)"))
                    return
                except Exception:
                    pass
            # fallback: CTkTextbox
            tb = ctk.CTkTextbox(parent, font=ctk.CTkFont(family="Consolas", size=11),
                                fg_color="#f8faff", text_color=C["text"],
                                border_width=0, wrap="word")
            tb.pack(fill="both", expand=True, padx=4, pady=4)
            tb.insert("end", md_text or "(내용 없음)")
            tb.configure(state="disabled")

        clean_query = _extract_user_query(rec.get("full_prompt") or "")
        _make_content_area(nb.tab("📝 질의"), clean_query)
        full_response = rec.get("full_response") or ""
        _make_content_area(nb.tab("💬 응답"), full_response)

        # 브라우저에서 열기 버튼 (KaTeX 수식 렌더링용)
        def _open_in_browser():
            import tempfile
            katex_html = _make_katex_html(clean_query, full_response)
            try:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".html",
                                                  delete=False, encoding="utf-8") as tf:
                    tf.write(katex_html)
                    tmp_path = tf.name
                webbrowser.open("file:///" + tmp_path.replace("\\", "/"))
            except Exception:
                pass

        browser_btn = ctk.CTkButton(
            card, text="🌐 브라우저에서 열기 (수식 렌더링)",
            width=220, height=28,
            fg_color=C["primary_lt"], text_color=C["primary"],
            hover_color="#ddd6fe", corner_radius=8,
            font=ctk.CTkFont(size=10),
            command=_open_in_browser)
        browser_btn.pack(side="bottom", pady=(0, 10))

    # ══ TAB 3: 사용방법 ══════════════════════════════════════════
    t3 = tab_frame.tab("📖 사용방법")
    t3.configure(fg_color=C["bg"])
    howto_card = make_card(t3)
    howto_card.pack(fill="both", expand=True, padx=12, pady=10)
    howto_title_lbl = card_title(howto_card, "사용 방법")
    howto_box = ctk.CTkTextbox(howto_card, font=ctk.CTkFont(size=12),
                               fg_color="#f8f9ff", text_color=C["text"],
                               border_width=0, corner_radius=8, wrap="word")
    howto_box.pack(fill="both", expand=True, padx=10, pady=(6, 10))

    def fill_howto():
        howto_box.configure(state="normal")
        howto_box.delete("1.0", "end")
        for s in [T("ht_1"), T("ht_2"), T("ht_3"), T("ht_4"), T("ht_5")]:
            howto_box.insert("end", s + "\n\n")
        howto_box.insert("end", "─" * 50 + "\n")
        howto_box.insert("end", T("ht_modes") + "\n")
        howto_box.configure(state="disabled")

    fill_howto()

    # ══ TAB 4: 만든이 ════════════════════════════════════════════
    t4 = tab_frame.tab("🙋 만든이")
    t4.configure(fg_color=C["bg"])
    ab_card = make_card(t4)
    ab_card.pack(fill="both", expand=True, padx=12, pady=10)
    ctk.CTkLabel(ab_card, text="⚡ Eunho Kim (uno-km)",
                 font=ctk.CTkFont(size=18, weight="bold"),
                 text_color=C["primary"]).pack(pady=(20, 4))
    ab_desc_lbl = ctk.CTkLabel(ab_card, text=T("ab_desc"),
                               font=ctk.CTkFont(size=12), text_color=C["muted"])
    ab_desc_lbl.pack(pady=(0, 16))

    LINKS = [
        ("ab_site", "https://uno-km.vercel.app/foundation/"),
        ("ab_gh",   "https://github.com/uno-km"),
        ("ab_blog", "https://uno-kim.tistory.com/"),
        ("ab_coffee", "https://buymeacoffee.com/uno.km"),
    ]
    link_frame = ctk.CTkFrame(ab_card, fg_color="transparent")
    link_frame.pack(pady=4)
    link_btns = []
    for key, url in LINKS:
        btn = ctk.CTkButton(link_frame, text=T(key), width=200, height=36,
                            fg_color=C["primary_lt"], text_color=C["primary"],
                            hover_color="#ddd6fe", corner_radius=10,
                            font=ctk.CTkFont(size=12, weight="bold"),
                            command=lambda u=url: webbrowser.open(u))
        btn.pack(pady=4)
        link_btns.append((key, btn))

    ctk.CTkFrame(ab_card, height=1, fg_color=C["border"]).pack(fill="x", padx=20, pady=12)
    license_lbl = ctk.CTkLabel(ab_card, text=T("ab_license"),
                               font=ctk.CTkFont(size=10), text_color=C["muted"],
                               justify="center")
    license_lbl.pack(pady=(0, 16))

    def toggle_lang():
        lang_var["lang"] = "en" if lang_var["lang"] == "ko" else "ko"
        lang_btn.configure(text=T("flag_btn"))
        for key, (lbl, val, sub) in stat_refs.items():
            lbl.configure(text=T(f"lbl_{key}"))
        ab_desc_lbl.configure(text=T("ab_desc"))
        license_lbl.configure(text=T("ab_license"))
        for key, btn in link_btns:
            btn.configure(text=T(key))
        fill_howto()
        purge_btn.configure(text=T("btn_purge"))
        reset_btn.configure(text=T("btn_reset"))
        open_btn.configure(text=T("btn_open"))
        server_wait_lbl.configure(text=T("server_wait"))
        wcard_title_lbl.configure(text=T("card_workers"))
        tcard_title_lbl.configure(text=T("card_task"))
        qcard_title_lbl.configure(text=T("card_queue"))
        hist_title_lbl.configure(text=T("hist_title"))
        howto_title_lbl.configure(text=T("howto_title"))

    lang_btn.configure(command=toggle_lang)

    # ── SSE 구독 스레드 ──────────────────────────────────────────
    _connected = [server_ok]
    _sse_stop = threading.Event()

    SOURCE_LABELS = {
        "api":             "REST API",
        "mcp":             "MCP",
        "mcp:claude":      "MCP · Claude",
        "mcp:cursor":      "MCP · Cursor",
        "mcp:antigravity": "MCP · Antigravity",
        "extension":       "브라우저 확장",
        "cli":             "CLI",
    }
    SOURCE_COLORS = {
        "api":             "#6366f1",
        "mcp":             "#d97706",
        "mcp:claude":      "#d97706",
        "mcp:cursor":      "#0891b2",
        "mcp:antigravity": "#7c3aed",
        "extension":       "#16a34a",
        "cli":             "#64748b",
    }

    def _sse_reader():
        """별도 스레드에서 SSE /api/stream 구독."""
        while not _sse_stop.is_set():
            try:
                conn = http.client.HTTPConnection(host, port, timeout=60)
                conn.request("GET", "/api/stream",
                             headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"})
                resp = conn.getresponse()
                if resp.status != 200:
                    raise ConnectionError(f"SSE {resp.status}")
                app_root.after(0, lambda: _on_sse_connect(True))
                buf = ""
                while not _sse_stop.is_set():
                    chunk = resp.read(1)
                    if not chunk:
                        break
                    buf += chunk.decode("utf-8", errors="ignore")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.rstrip("\r")
                        if line.startswith("data: "):
                            raw = line[6:].strip()
                            if raw and raw != "[DONE]":
                                try:
                                    evt = json.loads(raw)
                                    app_root.after(0, lambda e=evt: _on_sse_event(e))
                                except json.JSONDecodeError:
                                    pass
            except Exception:
                app_root.after(0, lambda: _on_sse_connect(False))
                for _ in range(30):
                    if _sse_stop.is_set():
                        return
                    time.sleep(0.1)

    def _on_sse_connect(ok: bool):
        _connected[0] = ok
        if ok:
            status_badge.configure(text=T("idle"), fg_color=C["green_lt"], text_color=C["green"])
            try:
                server_wait_lbl.pack_forget()
            except Exception:
                pass
        else:
            status_badge.configure(text=T("connecting"),
                                   fg_color=C["yellow_lt"], text_color=C["yellow"])

    def _on_sse_event(evt: dict):
        etype = evt.get("type", "")
        if etype == "snapshot":
            st = evt.get("status") or {}
            stats = evt.get("stats") or {}
            if st:
                _apply_update(st, stats)
        elif etype == "accounts":
            _update_workers(evt.get("workers") or [])
        elif etype in ("task_queued", "task_start", "task_done"):
            _apply_task_event(evt)
            # stats_dirty면 stats도 같이 옴
            if evt.get("stats"):
                _apply_stats(evt["stats"])
            # 워커 상태 업데이트
            if "workers" in evt:
                _update_workers(evt["workers"])

    _task_rows: dict = {}  # task_id → frame

    def _apply_task_event(evt: dict):
        import datetime as _dt
        task = evt.get("task") or {}
        tid = task.get("id", "")
        if not tid:
            return
        status = task.get("status", "")
        source = task.get("source", "api")
        preview = _extract_user_query(task.get("preview", ""))
        worker = task.get("worker") or "—"
        tokens = task.get("tokens", 0)
        queued_at = task.get("queued_at", 0)
        time_str = _dt.datetime.fromtimestamp(queued_at).strftime("%H:%M:%S") if queued_at else ""
        src_label = SOURCE_LABELS.get(source, source)
        src_color = SOURCE_COLORS.get(source, C["muted"])

        if tid not in _task_rows:
            fr = ctk.CTkFrame(queue_scroll, fg_color=C["bg"],
                              corner_radius=6, border_width=1, border_color=C["border"])
            fr.pack(fill="x", padx=2, pady=2)
            src_lbl = ctk.CTkLabel(fr, text=src_label,
                                   font=ctk.CTkFont(size=9, weight="bold"),
                                   fg_color=src_color, text_color="#ffffff",
                                   corner_radius=4, padx=6, pady=2)
            src_lbl.pack(side="left", padx=(6, 4), pady=5)
            prev_lbl = ctk.CTkLabel(fr, text=preview[:38],
                                    font=ctk.CTkFont(size=10), text_color=C["text"],
                                    anchor="w")
            prev_lbl.pack(side="left", fill="x", expand=True, pady=5)
            st_lbl = ctk.CTkLabel(fr, text="⏳",
                                  font=ctk.CTkFont(size=11),
                                  text_color=C["muted"])
            st_lbl.pack(side="right", padx=8, pady=5)
            tok_lbl = ctk.CTkLabel(fr, text=f"{tokens:,}tok" if tokens else "",
                                   font=ctk.CTkFont(size=9), text_color=C["muted"])
            tok_lbl.pack(side="right", padx=(0, 2), pady=5)
            time_lbl = ctk.CTkLabel(fr, text=time_str,
                                    font=ctk.CTkFont(size=9), text_color=C["muted"])
            time_lbl.pack(side="right", padx=(0, 4), pady=5)
            wk_lbl = ctk.CTkLabel(fr, text=worker,
                                  font=ctk.CTkFont(size=9), text_color=C["muted"])
            wk_lbl.pack(side="right", padx=(0, 4), pady=5)
            _task_rows[tid] = {"fr": fr, "st": st_lbl, "wk": wk_lbl, "tok": tok_lbl}
            # 최대 15개 유지
            if len(_task_rows) > 15:
                oldest_id = next(iter(_task_rows))
                try:
                    _task_rows[oldest_id]["fr"].destroy()
                except Exception:
                    pass
                del _task_rows[oldest_id]
        else:
            row = _task_rows[tid]
            row["wk"].configure(text=worker)
            if tokens:
                row["tok"].configure(text=f"{tokens:,}tok")
        row = _task_rows[tid]
        icons = {"queued": "⏳", "running": "🚀", "done": "✓", "error": "✗"}
        clrs  = {"queued": C["muted"], "running": C["primary"],
                 "done": C["green"], "error": C["red"]}
        row["st"].configure(text=icons.get(status, "?"),
                            text_color=clrs.get(status, C["muted"]))

    def _apply_update(st, stats):
        _update_workers(st.get("workers", []))
        busy = st.get("is_busy", False)
        if busy:
            status_badge.configure(text=T("busy"), fg_color="#e0e7ff", text_color="#4338ca")
        else:
            status_badge.configure(text=T("idle"), fg_color=C["green_lt"], text_color=C["green"])
        task_label.configure(
            text=st.get("current_task", "...") if busy else T("idle"),
            text_color=C["primary"] if busy else C["muted"])
        if stats:
            _apply_stats(stats)

    def _update_workers(ws):
        if not ws:
            return
        try:
            server_wait_lbl.pack_forget()
        except Exception:
            pass
        for w in ws:
            pw = w.get("port")
            is_busy = w.get("is_busy", False)
            login_state = w.get("login_state", "unknown")
            if is_busy:
                s, col = T("worker_busy"), C["primary"]
            elif login_state == "ok":
                s, col = T("worker_ok"), C["green"]
            elif login_state == "required":
                s, col = T("worker_login"), C["red"]
            else:
                s, col = T("worker_unknown"), C["muted"]
            name_text = f"  {w.get('name', '')}  :{pw}"
            if pw not in worker_widgets:
                f = ctk.CTkFrame(workers_container, fg_color=C["bg"],
                                 corner_radius=8, border_width=1, border_color=C["border"])
                f.pack(fill="x", pady=3)
                nl = ctk.CTkLabel(f, text=name_text,
                                  font=ctk.CTkFont(size=11, weight="bold"), text_color=C["text"])
                nl.pack(side="left", padx=8, pady=6)
                cb = ctk.CTkButton(f, text=T("btn_connect"), width=70, height=24,
                                   fg_color=C["primary"], hover_color="#4f46e5", corner_radius=6,
                                   font=ctk.CTkFont(size=10, weight="bold"),
                                   command=lambda p=pw: _connect_account(p))
                sl = ctk.CTkLabel(f, text=s, font=ctk.CTkFont(size=10, weight="bold"),
                                  text_color=col)
                sl.pack(side="right", padx=10)
                worker_widgets[pw] = {"name_lbl": nl, "status_lbl": sl, "connect_btn": cb}
            else:
                worker_widgets[pw]["name_lbl"].configure(text=name_text)
                worker_widgets[pw]["status_lbl"].configure(text=s, text_color=col)
            btn = worker_widgets[pw]["connect_btn"]
            if login_state == "ok" or is_busy:
                btn.pack_forget()
            elif not btn.winfo_ismapped():
                btn.pack(side="right", padx=(0, 2), pady=4)

    def _connect_account(account_port: int):
        from tkinter import messagebox

        def request_login():
            try:
                urllib.request.urlopen(
                    urllib.request.Request(f"{BASE}/api/accounts/{account_port}/login", method="POST"), timeout=5)
            except Exception as exc:
                app_root.after(0, lambda e=exc: messagebox.showerror(T("btn_connect"), str(e)))

        threading.Thread(target=request_login, daemon=True).start()

    def _apply_stats(stats):
        for key, (lbl, val, sub) in stat_refs.items():
            d = stats.get(key, {})
            val.configure(text=str(d.get("queries", 0)))
            sub.configure(text=f"{d.get('tokens', 0):,} {T('tokens')}")
            lbl.configure(text=T(f"lbl_{key}"))
        recent = stats.get("recent", [])

        # 기존 행 제거
        for w, _ in _hist_row_widgets:
            try:
                w.destroy()
            except Exception:
                pass
        _hist_row_widgets.clear()

        try:
            hist_no_data.pack_forget()
        except Exception:
            pass

        if not recent:
            hist_no_data.configure(text=T("no_data"))
            hist_no_data.pack(pady=20)
            return

        for r in recent:
            rid = r.get("id", 0)
            src = r.get("source", "api")
            src_label = SOURCE_LABELS.get(src, src)
            src_color = SOURCE_COLORS.get(src, C["muted"])
            ok_flag = bool(r.get("success"))
            dur_s  = r.get("duration_ms", 0) / 1000
            tok    = r.get("tokens_est", 0)
            ts     = str(r.get("time_str", ""))[:16]
            preview = _extract_user_query(r.get("prompt_preview", ""))[:60]

            row_frame = ctk.CTkFrame(hist_scroll, fg_color="#ffffff", corner_radius=8,
                                     border_width=1, border_color=C["border"])
            row_frame.pack(fill="x", padx=2, pady=3)

            # 소스 배지
            ctk.CTkLabel(row_frame, text=src_label,
                         font=ctk.CTkFont(size=8, weight="bold"),
                         fg_color=src_color, text_color="#ffffff",
                         corner_radius=4, padx=5, pady=2).pack(side="left", padx=(8, 4), pady=8)

            # 프리뷰 텍스트
            ctk.CTkLabel(row_frame, text=preview,
                         font=ctk.CTkFont(size=10), text_color=C["text"],
                         anchor="w").pack(side="left", fill="x", expand=True, pady=8)

            # 우측 메타
            meta_col = ctk.CTkFrame(row_frame, fg_color="transparent")
            meta_col.pack(side="right", padx=(0, 6), pady=4)
            ctk.CTkLabel(meta_col, text=f"{dur_s:.1f}s  {tok:,}tok",
                         font=ctk.CTkFont(size=9), text_color=C["muted"]).pack(anchor="e")
            ctk.CTkLabel(meta_col, text=ts,
                         font=ctk.CTkFont(size=8), text_color=C["muted"]).pack(anchor="e")

            # 성공/실패 아이콘
            ctk.CTkLabel(row_frame, text="✓" if ok_flag else "✗",
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=C["green"] if ok_flag else C["red"]).pack(side="right", padx=4)

            # more 버튼
            more_btn = ctk.CTkButton(row_frame, text="상세보기", width=62, height=22,
                                     fg_color=C["primary_lt"], text_color=C["primary"],
                                     hover_color="#ddd6fe", corner_radius=6,
                                     font=ctk.CTkFont(size=9),
                                     command=lambda rid=rid: _open_modal(rid))
            more_btn.pack(side="right", padx=(0, 4), pady=6)

            _hist_row_widgets.append((row_frame, rid))

    # SSE 구독 스레드 시작 (daemon=True → 창 닫히면 자동 종료)
    _tray_icon_ref: list = [None]

    def _quit_app():
        _sse_stop.set()
        if _tray_icon_ref[0]:
            try:
                _tray_icon_ref[0].stop()
            except Exception:
                pass
        app_root.destroy()

    def _show_window():
        app_root.deiconify()
        app_root.lift()
        app_root.focus_force()

    def _start_tray():
        try:
            import pystray
            from PIL import Image as _PILImg, ImageDraw as _PILDraw
            ico_path = _find_icon_path()
            if ico_path:
                tray_img = _PILImg.open(ico_path).resize((64, 64))
            else:
                tray_img = _PILImg.new("RGBA", (64, 64), (99, 102, 241, 255))
                _d = _PILDraw.Draw(tray_img)
                _d.text((14, 16), "A", fill="white")
            menu = pystray.Menu(
                pystray.MenuItem("amv-cp-bridge 열기", lambda: app_root.after(0, _show_window), default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("종료", lambda: app_root.after(0, _quit_app)),
            )
            icon = pystray.Icon("amv-cp-bridge", tray_img, "amv-cp-bridge", menu)
            _tray_icon_ref[0] = icon
            icon.run()
        except ImportError:
            pass

    def _on_close():
        app_root.withdraw()
        if _tray_icon_ref[0] is None:
            threading.Thread(target=_start_tray, daemon=True).start()

    app_root.protocol("WM_DELETE_WINDOW", _on_close)
    sse_thread = threading.Thread(target=_sse_reader, daemon=True)
    sse_thread.start()
    _bring_to_front(app_root)
    app_root.mainloop()


def _bring_existing_window_to_front():
    """이미 실행 중인 GUI 창을 앞으로 가져온다."""
    try:
        import ctypes, ctypes.wintypes
        found = []
        def _cb(hwnd, lp):
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(300)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 300)
            t = buf.value.strip()
            if "amv-cp-bridge" in t and ":11" in t:
                found.append(hwnd)
            return True
        FN = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        ctypes.windll.user32.EnumWindows(FN(_cb), 0)
        for hwnd in found:
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _extract_user_query(text: str) -> str:
    """[질문]: 마커 뒤의 마지막 사용자 쿼리를 추출한다. 마커 없으면 원문 반환."""
    marker = "[질문]: "
    idx = text.rfind(marker)
    if idx >= 0:
        return text[idx + len(marker):].strip()
    return text


def launch_gui(host: str = "127.0.0.1", port: int = 11500):
    # Windows 단일 인스턴스 체크
    import sys as _sys
    if _sys.platform == "win32":
        try:
            import ctypes as _ct
            _MUTEX_NAME = "Global\\amv-cp-bridge-gui-singleton"
            _mutex = _ct.windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
            if _ct.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                _bring_existing_window_to_front()
                return
        except Exception:
            pass

    # 11500 포트에 이미 서버가 있으면 그 포트 재사용 (스플래시에서 새 서버 시작 안 함)
    _launch_splash(host, port)
