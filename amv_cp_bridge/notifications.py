# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
Desktop OS and tray notification dispatcher for amv-cp-bridge.
Notifies users when M365 Copilot re-authentication is required.
"""

import sys
import time
import threading
import subprocess
from typing import Optional

_last_notify_time = 0.0
_NOTIFY_DEBOUNCE_SEC = 20.0
_notify_lock = threading.Lock()


def notify_login_required(detail: str = "") -> bool:
    """Dispatches a system tray / OS desktop notification when authentication is required.
    Debounced to prevent multiple alerts within 20 seconds.
    """
    global _last_notify_time
    with _notify_lock:
        now = time.time()
        if now - _last_notify_time < _NOTIFY_DEBOUNCE_SEC:
            return False
        _last_notify_time = now

    title = "amv-cp-bridge: Re-authentication Required"
    message = "Microsoft 365 Copilot session expired (Entra ID). Please sign in via the tray or dashboard."

    # 1. Attempt pystray tray notification via GUI reference
    try:
        from amv_cp_bridge import gui
        if hasattr(gui, "_tray_icon_ref") and gui._tray_icon_ref and gui._tray_icon_ref[0]:
            gui._tray_icon_ref[0].notify(message, title)
            return True
    except Exception:
        pass

    # 2. Windows Toast fallback via PowerShell
    if sys.platform == "win32":
        def _send_windows_toast():
            try:
                ps = (
                    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
                    "$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                    "$texts = $xml.GetElementsByTagName('text');"
                    f"$texts[0].AppendChild($xml.CreateTextNode('{title}')) | Out-Null;"
                    f"$texts[1].AppendChild($xml.CreateTextNode('{message}')) | Out-Null;"
                    "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml);"
                    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('amv-cp-bridge').Show($toast);"
                )
                subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                    capture_output=True,
                    timeout=5
                )
            except Exception:
                pass

        threading.Thread(target=_send_windows_toast, daemon=True).start()
        return True

    return False
