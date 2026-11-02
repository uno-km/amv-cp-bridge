# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
Builds dist/amv-cp-bridge.exe in an isolated environment, compresses it with UPX,
validates it with an automated self-test, and writes dist/build_report.json.

Usage: python scripts/build/build_exe.py [--no-upx]
"""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"
DIST = ROOT / "dist"
VENV = BUILD / "venv"
VENV_PYTHON = VENV / "Scripts" / "python.exe"
SPEC = ROOT / "scripts" / "build" / "amv-cp-bridge.spec"
RAW_REPORT = BUILD / "raw_report.json"
EXE = DIST / "amv-cp-bridge.exe"
REPORT = DIST / "build_report.json"

PYINSTALLER_VERSION = "6.22.3"
UPX_VERSION = "5.0.2"
UPX_SHA256 = "1cff6d6ee01c404d4a1ae56003056bd4cfa28d0a5cea1d0950daaf872a4facc9"
UPX_URL = f"https://github.com/upx/upx/releases/download/v{UPX_VERSION}/upx-{UPX_VERSION}-win64.zip"
UPX_DIR = BUILD / "tools" / f"upx-{UPX_VERSION}-win64"
UPX_EXE = UPX_DIR / "upx.exe"


def log(message: str) -> None:
    print(f"[build] {message}", flush=True)


def run(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def ensure_venv() -> None:
    if not VENV_PYTHON.exists():
        log(f"Creating isolated build environment: {VENV}")
        venv.create(VENV, with_pip=True, clear=True)
    log("Installing build dependencies")
    run(VENV_PYTHON, "-m", "pip", "install", "--upgrade", "--quiet", "--disable-pip-version-check",
        "-r", ROOT / "requirements.txt", f"pyinstaller=={PYINSTALLER_VERSION}")


def ensure_upx() -> None:
    if UPX_EXE.exists():
        return
    UPX_DIR.parent.mkdir(parents=True, exist_ok=True)
    archive = UPX_DIR.parent / "upx.zip"
    log(f"Downloading UPX {UPX_VERSION}")
    urllib.request.urlretrieve(UPX_URL, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != UPX_SHA256:
        archive.unlink()
        raise SystemExit(f"[build] UPX checksum mismatch: {digest}")
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(UPX_DIR.parent)
    archive.unlink()
    if not UPX_EXE.exists():
        raise SystemExit(f"[build] UPX archive did not contain {UPX_EXE}")


def pack_node() -> Path:
    driver = subprocess.run(
        [str(VENV_PYTHON), "-c",
         "import playwright,os;print(os.path.join(os.path.dirname(playwright.__file__),'driver','node.exe'))"],
        check=True, capture_output=True, text=True).stdout.strip()
    source = Path(driver)
    packed = BUILD / "node_upx" / "node.exe"
    packed.parent.mkdir(parents=True, exist_ok=True)
    expected = subprocess.run([str(source), "--version"], check=True, capture_output=True, text=True).stdout.strip()
    if packed.exists():
        packed.unlink()
    log(f"Compressing node.exe with UPX ({source.stat().st_size / 1048576:.1f} MB)")
    run(UPX_EXE, "--best", "--lzma", "-q", "-o", packed, source, stdout=subprocess.DEVNULL)
    actual = subprocess.run([str(packed), "--version"], check=True, capture_output=True, text=True).stdout.strip()
    if actual != expected:
        raise SystemExit(f"[build] Packed node.exe reports {actual}, expected {expected}")
    log(f"node.exe packed to {packed.stat().st_size / 1048576:.1f} MB and verified ({actual})")
    return packed


def run_pyinstaller(use_upx: bool, packed_node) -> None:
    env = dict(os.environ, AMV_RAW_REPORT=str(RAW_REPORT))
    if packed_node:
        env["AMV_PACKED_NODE"] = str(packed_node)
    if use_upx:
        env["UPX"] = "--best --lzma"
        env["AMV_USE_UPX"] = "1"
    upx_args = ["--upx-dir", str(UPX_DIR)] if use_upx else []
    log("Running PyInstaller")
    run(VENV_PYTHON, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", DIST, "--workpath", BUILD / "pyi", *upx_args, SPEC, env=env, cwd=ROOT)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def self_test() -> str:
    out = BUILD / "selftest.json"
    out.unlink(missing_ok=True)
    log("Running self-test")
    code = subprocess.run([str(EXE), "selftest", "--out", str(out)], timeout=180).returncode
    result = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"error": "no report written"}
    if code != 0 or not result.get("ok"):
        raise SystemExit(f"[build] Self-test failed (exit {code}): {json.dumps(result, indent=2)}")
    log(f"Self-test passed: {len(result['checks'])} checks")

    port = free_port()
    process = subprocess.Popen([str(EXE), "gateway", "--port", str(port)])
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                    health = json.loads(response.read().decode("utf-8"))
                if health.get("gateway") == "amv-cp-bridge":
                    log(f"Gateway /health passed: version {health.get('version')}")
                    return str(health.get("version"))
            except OSError:
                time.sleep(0.5)
        raise SystemExit("[build] Gateway /health did not respond within 60 seconds")
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)


def write_report(version: str, use_upx: bool) -> dict:
    raw = json.loads(RAW_REPORT.read_text(encoding="utf-8"))["raw_bytes"]
    final = EXE.stat().st_size
    report = {
        "version": version,
        "upx": use_upx,
        "raw_bytes": raw,
        "exe_bytes": final,
        "compression_percent": round((1 - final / raw) * 100, 1),
        "sha256": hashlib.sha256(EXE.read_bytes()).hexdigest(),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-upx", action="store_true", help="Build without UPX, for size comparison only")
    args = parser.parse_args()

    if sys.platform != "win32":
        raise SystemExit("[build] The EXE build supports Windows only")

    use_upx = not args.no_upx
    BUILD.mkdir(exist_ok=True)
    ensure_venv()
    packed_node = None
    if use_upx:
        ensure_upx()
        packed_node = pack_node()
    run_pyinstaller(use_upx, packed_node)
    version = self_test()
    report = write_report(version, use_upx)
    log(f"Payload before compression: {report['raw_bytes'] / 1048576:.1f} MB")
    log(f"Final EXE: {report['exe_bytes'] / 1048576:.1f} MB")
    log(f"Compression: {report['compression_percent']}%")
    log(f"SHA-256: {report['sha256']}")


if __name__ == "__main__":
    main()
