import unittest
from amv_cp_bridge.engine import CopilotWorker

class TestImageExtraction(unittest.TestCase):
    def setUp(self):
        self.worker = CopilotWorker(port=9999, name="TestImageWorker", profile_dir="dummy")

    def test_clean_text_with_designer_image_only(self):
        raw = "Copilot said:\n\n![A futuristic cyberpunk skyline](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA)"
        cleaned = self.worker._clean_text(raw)
        self.assertEqual(cleaned, "![A futuristic cyberpunk skyline](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA)")

    def test_clean_text_with_text_and_designer_image(self):
        raw = "Copilot said:\nHere is your requested image:\n\n![Futuristic city](https://copilot.microsoft.com/th?id=OIG123)"
        cleaned = self.worker._clean_text(raw)
        self.assertIn("Here is your requested image:", cleaned)
        self.assertIn("![Futuristic city](https://copilot.microsoft.com/th?id=OIG123)", cleaned)

if __name__ == "__main__":
    unittest.main()
