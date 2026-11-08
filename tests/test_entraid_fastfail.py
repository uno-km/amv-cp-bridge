# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
Unit tests for Entra ID Fast-Fail, HTTP 401 error mapping, and notifications in v1.2.1.
"""

import unittest
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock

from amv_cp_bridge._version import __version__
from amv_cp_bridge.engine import _is_login_url, CopilotWorker, CopilotLoginRequired
from amv_cp_bridge.notifications import notify_login_required


class TestEntraIdFastFail(unittest.TestCase):
    def test_version_bump(self):
        self.assertEqual(__version__, "1.2.1")

    def test_is_login_url(self):
        self.assertTrue(_is_login_url("https://login.microsoftonline.com/common/oauth2/v2.0/authorize"))
        self.assertTrue(_is_login_url("https://login.live.com/login.srf?wa=wsignin1.0"))
        self.assertTrue(_is_login_url("https://login.microsoft.com/extauth"))
        self.assertFalse(_is_login_url("https://m365.cloud.microsoft/chat"))
        self.assertFalse(_is_login_url("https://copilot.microsoft.com/"))
        self.assertFalse(_is_login_url("https://localhost:11500/dashboard"))

    def test_fast_fail_timeout_behavior(self):
        """Verify that _wait_for_composer fails fast (~1.5s) when redirected to a login host."""
        worker = CopilotWorker(9333, "TestWorker", "test_profile")

        mock_page = MagicMock()
        mock_page.url = "https://login.microsoftonline.com/kmsi"

        mock_textbox = MagicMock()
        mock_textbox.is_visible = AsyncMock(return_value=False)
        mock_page.locator.return_value.first = mock_textbox

        start = time.time()
        result = asyncio.run(worker._wait_for_composer(mock_page, timeout=45.0, fast_fail=True))
        elapsed = time.time() - start

        self.assertFalse(result)
        # Fast-fail should return around 1.5s to 2.5s, definitely not waiting 45s
        self.assertLess(elapsed, 4.0)

    def test_open_login_allows_user_time(self):
        """When fast_fail=False (such as in open_login), it should wait up to the explicit timeout."""
        worker = CopilotWorker(9333, "TestWorker", "test_profile")

        mock_page = MagicMock()
        mock_page.url = "https://login.microsoftonline.com/kmsi"

        mock_textbox = MagicMock()
        mock_textbox.is_visible = AsyncMock(return_value=False)
        mock_page.locator.return_value.first = mock_textbox

        start = time.time()
        result = asyncio.run(worker._wait_for_composer(mock_page, timeout=1.0, fast_fail=False))
        elapsed = time.time() - start

        self.assertFalse(result)
        self.assertGreaterEqual(elapsed, 0.9)

    def test_notify_login_required_debounce(self):
        """Verify that notify_login_required debounces consecutive calls."""
        first = notify_login_required("Session expired")
        second = notify_login_required("Session expired")
        # Second call immediately after should be debounced and return False
        self.assertFalse(second)

    def test_http_401_on_login_required(self):
        """Verify that CopilotLoginRequired produces HTTP 401 with standard error format."""
        from fastapi.testclient import TestClient
        from amv_cp_bridge.gateway import app, engine
        from unittest.mock import patch

        client = TestClient(app)

        with patch.object(engine, "query", side_effect=CopilotLoginRequired("Session revoked")):
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "copilot-standard",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": False
                }
            )
            self.assertEqual(response.status_code, 401)
            data = response.json()
            self.assertIn("error", data["detail"])
            self.assertEqual(data["detail"]["error"]["code"], "session_expired")
            self.assertEqual(data["detail"]["error"]["type"], "authentication_error")


if __name__ == "__main__":
    unittest.main()
