# -*- mode: python ; coding: utf-8 -*-
import json
import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
ICON = os.path.join(ROOT, "amv-cp-bridge.ico")
PACKED_NODE = os.environ.get("AMV_PACKED_NODE", "")
REPORT_PATH = os.environ.get("AMV_RAW_REPORT", "")

DROPPED_DATA_PREFIXES = (
    os.path.join("playwright", "driver", "package", "lib", "vite") + os.sep,
    os.path.join("playwright", "driver", "package", "types") + os.sep,
    "_tcl_data" + os.sep + "tzdata" + os.sep,
    "_tk_data" + os.sep + "demos" + os.sep,
)
DROPPED_DATA_SUFFIXES = (".bak", ".map")

datas = [(ICON, ".")]
binaries = []
hiddenimports = [
    "tkinter", "tkinter.ttk", "tkinter.messagebox", "tkinter.scrolledtext", "sqlite3",
    "amv_cp_bridge", "amv_cp_bridge._version", "amv_cp_bridge.updater",
    "amv_cp_bridge.settings", "amv_cp_bridge.telemetry_db", "amv_cp_bridge.engine",
    "amv_cp_bridge.gateway", "amv_cp_bridge.mcp_server", "amv_cp_bridge.gui",
    "amv_cp_bridge.reasoning", "amv_cp_bridge.notifications", "markdown2",
]
for package in ("uvicorn", "fastapi", "starlette", "pydantic", "websockets",
                "customtkinter", "PIL", "playwright", "tkinterweb", "pystray"):
    collected = collect_all(package)
    datas += collected[0]
    binaries += collected[1]
    hiddenimports += collected[2]

a = Analysis(
    [os.path.join(ROOT, "amv_cp_bridge", "cli.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest", "IPython", "jupyter", "numpy", "matplotlib", "pandas", "scipy"],
    noarchive=False,
    optimize=0,
)

a.datas = [
    entry for entry in a.datas
    if not entry[0].startswith(DROPPED_DATA_PREFIXES) and not entry[0].endswith(DROPPED_DATA_SUFFIXES)
]

raw_bytes = sum(os.path.getsize(entry[1]) for entry in a.binaries + a.datas)
raw_bytes += sum(os.path.getsize(entry[1]) for entry in a.pure if os.path.isfile(entry[1]))
if REPORT_PATH:
    with open(REPORT_PATH, "w", encoding="utf-8") as report:
        json.dump({"raw_bytes": raw_bytes}, report)

if PACKED_NODE:
    node_dest = os.path.join("playwright", "driver", "node.exe")
    a.datas = [
        (entry[0], PACKED_NODE, entry[2]) if entry[0] == node_dest else entry
        for entry in a.datas
    ]

pyz = PYZ(a.pure)


def make_boot_image(path):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (500, 150), "#6366f1")
    draw = ImageDraw.Draw(image)
    logo = Image.open(ICON).convert("RGBA").resize((56, 56))
    image.paste(logo, (34, 47), logo)
    draw.text((106, 44), "amv-cp-bridge", fill="#ffffff", font=ImageFont.truetype("segoeuib.ttf", 28))
    draw.text((106, 84), "Starting...", fill="#c7d2fe", font=ImageFont.truetype("segoeui.ttf", 14))
    image.save(path)


BOOT_IMAGE = os.path.join(ROOT, "build", "boot_splash.png")
make_boot_image(BOOT_IMAGE)
splash = Splash(BOOT_IMAGE, binaries=a.binaries, datas=a.datas, minify_script=True, always_on_top=True)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.datas,
    [],
    name="amv-cp-bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=os.environ.get("AMV_USE_UPX") == "1",
    upx_exclude=["vcruntime140.dll", "vcruntime140_1.dll", "python3.dll", "python312.dll"],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[ICON],
)
