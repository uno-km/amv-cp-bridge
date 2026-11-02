# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
AMEVA Copilot Bridge Package
Production-grade ephemeral zero-leak bridge and multi-protocol gateway for Microsoft 365 Copilot.
"""

__version__ = "1.0.0"
__author__ = "Eunho Kim <contact@uno-km.com>"

from .engine import CopilotEngine, CopilotPool, CopilotWorker

__all__ = ["CopilotEngine", "CopilotPool", "CopilotWorker", "__version__"]
