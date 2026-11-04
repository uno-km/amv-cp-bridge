# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
Builds, compresses, validates, and publishes a GitHub release for the current version.
Usage: python scripts/build/release.py
"""

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "uno-km/amv-cp-bridge"
EXTENSION_ZIP = "amv-cp-bridge-extension.zip"
TRACKED_SOURCES = ["amv_cp_bridge", "scripts", "extension", "pyproject.toml", "requirements.txt", "CHANGELOG.md"]


def capture(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8", cwd=ROOT).stdout.strip()


def read_version() -> str:
    text = (ROOT / "amv_cp_bridge" / "_version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__ = "([^"]+)"', text)
    if not match:
        raise SystemExit("[release] Version not found in amv_cp_bridge/_version.py")
    return match.group(1)


def changelog_section(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(version)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match or not match.group(1).strip():
        raise SystemExit(f"[release] CHANGELOG.md has no section for {version}")
    return match.group(1).strip()


def check_preconditions(version: str) -> str:
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8-sig"))
    if manifest["version"] != version:
        raise SystemExit(f"[release] extension/manifest.json is {manifest['version']}, expected {version}")
    if f"badge/v{version}-" not in (ROOT / "README.md").read_text(encoding="utf-8"):
        raise SystemExit(f"[release] README.md version badge is not {version}")
    dirty = capture("git", "status", "--porcelain", "--", *TRACKED_SOURCES)
    if dirty:
        raise SystemExit(f"[release] Uncommitted source changes:\n{dirty}")
    capture("git", "fetch", "origin", "--tags")
    head = capture("git", "rev-parse", "HEAD")
    if head != capture("git", "rev-parse", "origin/master"):
        raise SystemExit("[release] HEAD is not origin/master. Push first; setup_all reads from master.")
    if capture("git", "tag", "--list", f"v{version}"):
        raise SystemExit(f"[release] Tag v{version} already exists")
    return head


def previous_exe_bytes() -> tuple:
    latest = json.loads(capture("gh", "api", f"repos/{REPO}/releases/latest"))
    asset = next((a for a in latest["assets"] if a["name"] == "amv-cp-bridge.exe"), None)
    if asset is None:
        raise SystemExit(f"[release] Release {latest['tag_name']} has no EXE asset")
    return latest["tag_name"], asset["size"]


def compression_notes(report: dict, previous_tag: str, previous_bytes: int) -> str:
    mb = lambda value: f"{value / 1048576:.1f} MB"
    saved = (1 - report["exe_bytes"] / previous_bytes) * 100
    return (
        "### Package size\n\n"
        "| Item | Size |\n|---|---|\n"
        f"| Payload before compression | {mb(report['raw_bytes'])} |\n"
        f"| Final EXE | {mb(report['exe_bytes'])} |\n"
        f"| Compression | {report['compression_percent']}% |\n"
        f"| Previous EXE ({previous_tag}) | {mb(previous_bytes)} |\n"
        f"| Change from {previous_tag} | {-saved:+.1f}% |\n\n"
        f"SHA-256: `{report['sha256']}`\n"
    )


def build_extension_zip() -> Path:
    source = ROOT / "extension"
    target = ROOT / "dist" / EXTENSION_ZIP
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())
    with zipfile.ZipFile(target) as archive:
        if "manifest.json" not in archive.namelist():
            raise SystemExit(f"[release] {EXTENSION_ZIP} has no manifest.json at its root")
    return target


def main() -> None:
    skip_build = "--skip-build" in sys.argv
    version = read_version()
    tag = f"v{version}"
    section = changelog_section(version)
    head = check_preconditions(version)
    previous_tag, previous_bytes = previous_exe_bytes()

    if not skip_build:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build" / "build_exe.py")], check=True, cwd=ROOT)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build" / "regression_check.py")], check=True, cwd=ROOT)

    report = json.loads((ROOT / "dist" / "build_report.json").read_text(encoding="utf-8"))
    if report["version"] != version:
        raise SystemExit(f"[release] Built EXE reports {report['version']}, expected {version}")

    notes = f"{section}\n\n{compression_notes(report, previous_tag, previous_bytes)}"
    notes_file = ROOT / "build" / "release_notes.md"
    notes_file.write_text(notes, encoding="utf-8")

    extension_zip = build_extension_zip()
    capture("gh", "release", "create", tag, str(ROOT / "dist" / "amv-cp-bridge.exe"), str(extension_zip),
            "--repo", REPO, "--target", head, "--title", tag, "--notes-file", str(notes_file), "--latest")

    published = json.loads(capture("gh", "api", f"repos/{REPO}/releases/latest"))
    if published["tag_name"] != tag:
        raise SystemExit(f"[release] Latest release is {published['tag_name']}, expected {tag}")
    asset = next(a for a in published["assets"] if a["name"] == "amv-cp-bridge.exe")
    if asset.get("digest") != f"sha256:{report['sha256']}":
        raise SystemExit(f"[release] Asset digest mismatch: {asset.get('digest')}")

    if not any(a["name"] == EXTENSION_ZIP for a in published["assets"]):
        raise SystemExit(f"[release] {EXTENSION_ZIP} is missing from the published release")

    print(f"[release] Published {published['html_url']}")
    print(notes)


if __name__ == "__main__":
    main()
