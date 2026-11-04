# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""Test /api/settings endpoints on FastAPI gateway."""

import unittest
from fastapi.testclient import TestClient
from amv_cp_bridge.gateway import app


class TestGatewaySettings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_get_settings(self):
        resp = self.client.get("/api/settings")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertIn("mode", data.get("settings", {}))
        self.assertIn("standby_timeout_sec", data.get("settings", {}))

    def test_post_settings(self):
        # Set to hot mode
        resp = self.client.post("/api/settings", json={"mode": "hot", "standby_timeout_sec": 450})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data["settings"]["mode"], "hot")
        self.assertEqual(data["settings"]["standby_timeout_sec"], 450)

        # Verify GET returns updated
        resp2 = self.client.get("/api/settings")
        self.assertEqual(resp2.json()["settings"]["mode"], "hot")
        self.assertEqual(resp2.json()["settings"]["standby_timeout_sec"], 450)

        # Restore default cold mode
        resp3 = self.client.post("/api/settings", json={"mode": "cold", "standby_timeout_sec": 300})
        self.assertEqual(resp3.status_code, 200)
        self.assertEqual(resp3.json()["settings"]["mode"], "cold")
        self.assertEqual(resp3.json()["settings"]["standby_timeout_sec"], 300)


if __name__ == "__main__":
    unittest.main()
