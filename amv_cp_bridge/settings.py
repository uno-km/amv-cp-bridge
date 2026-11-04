# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
Persistent configuration management for amv-cp-bridge.
Manages bridge operation mode ('cold' vs 'hot'), standby timeout, and persistence to ~/.amv_cp_bridge/settings.json.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any

CONFIG_DIR = os.path.join(str(Path.home()), ".amv_cp_bridge")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")

DEFAULT_SETTINGS: Dict[str, Any] = {
    "mode": "cold",                # "cold" (단발성 즉시 0MB 종료) | "hot" (웜 스탠바이 유지)
    "standby_timeout_sec": 300,    # 핫로딩 모드 대기 만료 시간(초) — 기본 300초 (5분)
    "rate_limit_rpm": 30,          # IP당 분당 요청 제한
}


def load_settings() -> Dict[str, Any]:
    """Load settings from ~/.amv_cp_bridge/settings.json, with fallback to DEFAULT_SETTINGS."""
    settings = dict(DEFAULT_SETTINGS)
    if os.path.isfile(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                mode = str(loaded.get("mode", "cold")).lower().strip()
                if mode in ("cold", "hot"):
                    settings["mode"] = mode
                if "standby_timeout_sec" in loaded:
                    try:
                        timeout = int(loaded["standby_timeout_sec"])
                        settings["standby_timeout_sec"] = max(10, min(86400, timeout))
                    except (ValueError, TypeError):
                        pass
                if "rate_limit_rpm" in loaded:
                    try:
                        rpm = int(loaded["rate_limit_rpm"])
                        settings["rate_limit_rpm"] = max(1, min(1000, rpm))
                    except (ValueError, TypeError):
                        pass
                return settings
        except Exception as exc:
            print(f"[!] settings.json 읽기 실패, 기본값을 사용합니다: {exc}")

    # 설정 파일이 없으면 기본 설정으로 파일 생성
    save_settings(settings)
    return settings


def save_settings(new_data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and persist settings to ~/.amv_cp_bridge/settings.json."""
    current = dict(DEFAULT_SETTINGS)
    if os.path.isfile(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                current.update(loaded)
        except Exception:
            pass

    if "mode" in new_data:
        mode = str(new_data.get("mode", "cold")).lower().strip()
        current["mode"] = mode if mode in ("cold", "hot") else "cold"

    if "standby_timeout_sec" in new_data:
        try:
            timeout = int(new_data["standby_timeout_sec"])
            current["standby_timeout_sec"] = max(10, min(86400, timeout))
        except (ValueError, TypeError):
            pass

    if "rate_limit_rpm" in new_data:
        try:
            rpm = int(new_data["rate_limit_rpm"])
            current["rate_limit_rpm"] = max(1, min(1000, rpm))
        except (ValueError, TypeError):
            pass

    os.makedirs(CONFIG_DIR, exist_ok=True)
    temp_path = SETTINGS_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, SETTINGS_PATH)
    return current
