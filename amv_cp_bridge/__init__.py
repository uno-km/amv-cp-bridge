# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
AMEVA Copilot Bridge Package
Production-grade ephemeral zero-leak bridge and multi-protocol gateway for Microsoft 365 Copilot.
"""

__author__ = "Eunho Kim <contact@uno-km.com>"

from ._version import __version__

__all__ = ["CopilotEngine", "CopilotPool", "CopilotWorker", "load_settings", "save_settings", "__version__"]


def __getattr__(name):
    if name in ("CopilotEngine", "CopilotPool", "CopilotWorker"):
        from . import engine
        return getattr(engine, name)
    if name in ("load_settings", "save_settings"):
        from . import settings
        return getattr(settings, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
