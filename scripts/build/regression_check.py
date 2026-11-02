# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
Automated subset of the release regression checklist. Runs dist/amv-cp-bridge.exe against an
isolated home directory. Exits non-zero when any check fails.
"""

import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXE = ROOT / "dist" / "amv-cp-bridge.exe"
VENV_PYTHON = ROOT / "build" / "venv" / "Scripts" / "python.exe"
HOME = ROOT / "build" / "regression_home"

results = []


def check(item: str, passed: bool, detail: str = "") -> None:
    results.append(passed)
    print(f"[{'v' if passed else 'x'}] {item} {detail}".rstrip(), flush=True)


def request(port: int, path: str, method: str = "GET", headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, dict(response.headers), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read().decode("utf-8", errors="replace")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_gateway(port: int, env: dict) -> subprocess.Popen:
    process = subprocess.Popen([str(EXE), "gateway", "--port", str(port)], env=env)
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            if request(port, "/health")[0] == 200:
                return process
        except OSError:
            time.sleep(0.5)
    process.kill()
    raise SystemExit("[x] Gateway did not start within 60 seconds")


def stop_gateway(process: subprocess.Popen) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    process.wait(timeout=15)


def static_checks(version: str) -> None:
    tracked = subprocess.run(["git", "ls-files", "scripts"], cwd=ROOT, check=True,
                             capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
    non_ascii = [name for name in tracked if not name.isascii()]
    check("A-09 ASCII script names", not non_ascii, str(non_ascii) if non_ascii else "")

    unit = subprocess.run([str(VENV_PYTHON), "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=dict(os.environ, USERPROFILE=str(HOME), PYTHONIOENCODING="utf-8"))
    check("Unit tests", unit.returncode == 0, unit.stderr[-300:] if unit.returncode else "")

    multiline = readme_multiline_commands()
    check("README commands are one line", not multiline, str(multiline) if multiline else "")

    sources = {
        "extension/manifest.json": json.loads((ROOT / "extension/manifest.json").read_text(encoding="utf-8-sig"))["version"],
        "README badge": (re.search(r"badge/v([\d.]+)-", (ROOT / "README.md").read_text(encoding="utf-8")) or [None, ""])[1],
    }
    mismatched = {key: value for key, value in sources.items() if value != version}
    check("H-05 version sync", not mismatched, str(mismatched) if mismatched else version)

    modes = subprocess.run(["git", "ls-files", "-s", "scripts/macos", "scripts/setup_all.sh"], cwd=ROOT, check=True,
                           capture_output=True, text=True).stdout.splitlines()
    wrong = [line.split("\t")[1] for line in modes if not line.startswith("100755")]
    check("G-05/H-07 executable bit", not wrong, str(wrong) if wrong else "")

    limiter = subprocess.run(
        [str(VENV_PYTHON), "-c",
         "import sys; sys.path.insert(0, sys.argv[1]);"
         "from amv_cp_bridge.gateway import _RateLimiter as R; r=R();"
         "print(sum(r.is_allowed('t') for _ in range(40)))", str(ROOT)],
        capture_output=True, text=True, env=dict(os.environ, USERPROFILE=str(HOME)))
    check("B-03/I-01 rate limit 30 per minute", limiter.stdout.strip() == "30",
          limiter.stdout.strip() or limiter.stderr[-300:])


def readme_multiline_commands() -> list:
    """Returns fenced README blocks, other than text and JSON, that hold more than one line."""
    found = []
    readme = (ROOT / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    for match in re.finditer(r"^```(\w*)\n(.*?)^```$", readme, re.M | re.S):
        lines = [line for line in match.group(2).splitlines() if line.strip()]
        if match.group(1) not in ("text", "json") and len(lines) != 1:
            found.append(lines[0] if lines else "(empty)")
    return found


def gateway_checks(version: str, env: dict) -> None:
    port = free_port()
    process = start_gateway(port, env)
    try:
        status, _, body = request(port, "/health")
        health = json.loads(body)
        check("B-04 /health", status == 200 and health.get("gateway") == "amv-cp-bridge")
        check("H-05 gateway version", health.get("version") == version, str(health.get("version")))

        models = json.loads(request(port, "/v1/models")[2])
        check("B-05 /v1/models has 3 models", len(models.get("data", [])) == 3, str(len(models.get("data", []))))

        html = request(port, "/dashboard")[2]
        check("H-05 dashboard version", f"v{version}<" in html and "__APP_VERSION__" not in html)

        check("A-13 accounts.json created", (HOME / ".amv_cp_bridge" / "accounts.json").is_file())
        check("E-01 telemetry.db created", (HOME / ".amv_cp_bridge" / "telemetry.db").is_file())
        check("E-04 /api/chart", request(port, "/api/chart")[0] == 200)
        check("E-05/B-12 /api/stats/reset", request(port, "/api/stats/reset", "POST")[0] == 200)
        check("H-04 favicon", request(port, "/favicon.ico")[0] == 200)

        status = json.loads(request(port, "/api/status")[2])
        check("A-13 single default account", status.get("total_accounts") == 1, str(status.get("total_accounts")))
        check("Account state starts unverified", status["workers"][0].get("login_state") == "unknown",
              str(status["workers"][0].get("login_state")))
        check("Unknown account port rejected", request(port, "/api/accounts/1/login", "POST")[0] == 404)

        def preflight(origin: str) -> str:
            headers = {"Origin": origin, "Access-Control-Request-Method": "POST"}
            response_headers = request(port, "/v1/chat/completions", "OPTIONS", headers)[1]
            lowered = {key.lower(): value for key, value in response_headers.items()}
            return lowered.get("access-control-allow-origin", "")

        check("C-05 chrome-extension origin allowed", preflight("chrome-extension://abc") == "chrome-extension://abc")
        check("I-02 other origin rejected", preflight("https://evil.example") == "")

        listening = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
        bound = [line.split()[1] for line in listening.splitlines() if f":{port} " in line and "LISTENING" in line]
        check("I-03 bound to 127.0.0.1", bool(bound) and all(addr.startswith("127.0.0.1:") for addr in bound), str(bound))
    finally:
        stop_gateway(process)

    database = HOME / ".amv_cp_bridge" / "telemetry.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE regression_sentinel (id INTEGER)")
    process = start_gateway(port, env)
    try:
        status = request(port, "/api/stats")[0]
    finally:
        stop_gateway(process)
    with sqlite3.connect(database) as connection:
        kept = connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE name = 'regression_sentinel'").fetchone()[0] == 1
    check("E-07 database kept across restart", status == 200 and kept)


def main() -> None:
    version = re.search(r'"([^"]+)"', (ROOT / "amv_cp_bridge" / "_version.py").read_text(encoding="utf-8")).group(1)
    if HOME.exists():
        shutil.rmtree(HOME)
    HOME.mkdir(parents=True)
    env = dict(os.environ, USERPROFILE=str(HOME))
    static_checks(version)
    gateway_checks(version, env)
    failed = results.count(False)
    print(f"[regression] {len(results) - failed}/{len(results)} passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
