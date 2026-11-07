# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
Automated live demo screenshot capture script for amv-cp-bridge v1.1.0 in ENGLISH.
Captures both the Native CustomTkinter GUI tabs and the Web Telemetry Dashboard in EN.
"""

import os
import sys
import time
import shutil
import threading
import ctypes
from ctypes import wintypes
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR = Path(r"C:\Users\GAME\.gemini\antigravity\brain\18d8f79c-cf0b-4b18-b9b3-d685cdb911c8")

PORT = 8765
HOST = "127.0.0.1"
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def capture_hwnd_to_file(hwnd: int, save_path: Path):
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top

    hwndDC = ctypes.windll.user32.GetWindowDC(hwnd)
    mfcDC = ctypes.windll.gdi32.CreateCompatibleDC(hwndDC)
    saveBitMap = ctypes.windll.gdi32.CreateCompatibleBitmap(hwndDC, w, h)
    ctypes.windll.gdi32.SelectObject(mfcDC, saveBitMap)

    # PW_RENDERFULLCONTENT = 2
    ctypes.windll.user32.PrintWindow(hwnd, mfcDC, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ('biSize', wintypes.DWORD),
            ('biWidth', wintypes.LONG),
            ('biHeight', wintypes.LONG),
            ('biPlanes', wintypes.WORD),
            ('biBitCount', wintypes.WORD),
            ('biCompression', wintypes.DWORD),
            ('biSizeImage', wintypes.DWORD),
            ('biXPelsPerMeter', wintypes.LONG),
            ('biYPelsPerMeter', wintypes.LONG),
            ('biClrUsed', wintypes.DWORD),
            ('biClrImportant', wintypes.DWORD)
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buf = ctypes.create_string_buffer(w * h * 4)
    ctypes.windll.gdi32.GetDIBits(mfcDC, saveBitMap, 0, h, buf, ctypes.byref(bmi), 0)
    im = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1)
    im.save(save_path)
    print(f"[OK] Saved GUI screenshot: {save_path.name} ({w}x{h})", flush=True)

    ctypes.windll.gdi32.DeleteObject(saveBitMap)
    ctypes.windll.gdi32.DeleteDC(mfcDC)
    ctypes.windll.user32.ReleaseDC(hwnd, hwndDC)


def run_web_captures_en():
    print("Capturing Web Dashboard via Playwright Edge (English)...", flush=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=EDGE_PATH, headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 840})
        page.goto(f"http://{HOST}:{PORT}/dashboard", wait_until="networkidle")
        time.sleep(1.0)

        # Switch to English
        btn_en = page.locator("#btnEn")
        if btn_en.count() > 0:
            btn_en.click()
            time.sleep(0.5)

        # 1. Main Dashboard EN
        p1 = SCREENSHOTS_DIR / "05_web_dashboard_en.png"
        page.screenshot(path=str(p1))
        print(f"[OK] Saved Web Dashboard EN: {p1.name}", flush=True)

        # 2. Settings Tab EN
        settings_tab = page.locator(".tab", has_text="Settings")
        if settings_tab.count() == 0:
            settings_tab = page.locator("#tab-settings")
        if settings_tab.count() > 0:
            settings_tab.first.click()
            time.sleep(0.6)
            p2 = SCREENSHOTS_DIR / "06_web_settings_en.png"
            page.screenshot(path=str(p2))
            print(f"[OK] Saved Web Settings EN: {p2.name}", flush=True)

        browser.close()


def run_gui_captures_en():
    print("Capturing Native GUI via CustomTkinter & PrintWindow (English)...", flush=True)
    import customtkinter as ctk
    import amv_cp_bridge.gui as gui_mod

    def find_widgets(widget, target_class):
        res = []
        if isinstance(widget, target_class):
            res.append(widget)
        for child in widget.winfo_children():
            res.extend(find_widgets(child, target_class))
        return res

    orig_mainloop = ctk.CTk.mainloop

    def patched_mainloop(self, *args, **kwargs):
        hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
        tabviews = find_widgets(self, ctk.CTkTabview)
        tabview = tabviews[0] if tabviews else None

        # Find lang button
        buttons = find_widgets(self, ctk.CTkButton)
        lang_btn = None
        for b in buttons:
            if "EN" in b.cget("text") or "KO" in b.cget("text"):
                lang_btn = b
                break

        # Switch to English
        if lang_btn and "EN" in lang_btn.cget("text"):
            print("Switching GUI to English...", flush=True)
            lang_btn.invoke()
            self.update()
            self.update_idletasks()
            time.sleep(0.5)

        def step3_howto():
            print("[GUI EN Step 3] Capturing How-To tab...", flush=True)
            capture_hwnd_to_file(hwnd, SCREENSHOTS_DIR / "04_gui_howto_en.png")
            self.after(300, self.destroy)

        def step2_settings():
            print("[GUI EN Step 2] Capturing Settings tab...", flush=True)
            capture_hwnd_to_file(hwnd, SCREENSHOTS_DIR / "03_gui_settings_en.png")
            if tabview:
                try:
                    tabview.set("📖 사용방법")
                except Exception:
                    pass
            self.after(600, step3_howto)

        def step1_dashboard():
            print("[GUI EN Step 1] Capturing Dashboard tab...", flush=True)
            capture_hwnd_to_file(hwnd, SCREENSHOTS_DIR / "02_gui_dashboard_en.png")
            if tabview:
                try:
                    tabview.set("⚙️ 설정")
                except Exception:
                    pass
            self.after(600, step2_settings)

        self.after(800, step1_dashboard)
        return orig_mainloop(self, *args, **kwargs)

    ctk.CTk.mainloop = patched_mainloop
    gui_mod._launch_main_gui(HOST, PORT, server_ok=True)


def start_server_in_bg():
    import uvicorn
    from amv_cp_bridge.gateway import app
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    import urllib.request
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"http://{HOST}:{PORT}/health", timeout=0.2) as r:
                if r.status == 200:
                    print(f"Gateway server ready on http://{HOST}:{PORT}", flush=True)
                    return server
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Server failed to start")


def main():
    server = start_server_in_bg()

    # 1. Playwright Web Capture EN
    try:
        run_web_captures_en()
    except Exception as e:
        print(f"[WARN] Playwright error: {e}", flush=True)

    # 2. Native GUI Capture EN
    try:
        run_gui_captures_en()
    except Exception as e:
        print(f"[WARN] GUI error: {e}", flush=True)

    # Copy all generated screenshots to Artifacts Directory
    print(f"Syncing screenshots to Artifacts directory: {ARTIFACTS_DIR}", flush=True)
    for f in SCREENSHOTS_DIR.glob("*_en.png"):
        try:
            dst = ARTIFACTS_DIR / f.name
            shutil.copyfile(f, dst)
        except Exception as e:
            print(f"Copy error {f.name}: {e}", flush=True)

    print("[SUCCESS] All EN screenshots generated and synced!", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
