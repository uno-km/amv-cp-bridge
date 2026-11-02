import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load_updater():
    package = types.ModuleType("amv_cp_bridge")
    package.__path__ = [str(ROOT / "amv_cp_bridge")]
    sys.modules.setdefault("amv_cp_bridge", package)
    spec = importlib.util.spec_from_file_location("amv_cp_bridge.updater", ROOT / "amv_cp_bridge" / "updater.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["amv_cp_bridge.updater"] = module
    spec.loader.exec_module(module)
    return module


updater = _load_updater()


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.payload


class VersionTests(unittest.TestCase):
    def test_numeric_comparison(self):
        self.assertTrue(updater.is_newer("v1.0.10", "1.0.9"))
        self.assertTrue(updater.is_newer("1.1.0", "1.0.99"))

    def test_equal_or_older_is_not_newer(self):
        self.assertFalse(updater.is_newer("v1.0.1", "1.0.1"))
        self.assertFalse(updater.is_newer("1.0.0", "1.0.1"))

    def test_invalid_tag_raises(self):
        with self.assertRaises(updater.UpdateError):
            updater.parse_version("latest")


class FetchTests(unittest.TestCase):
    def test_parses_release(self):
        body = json.dumps({"tag_name": "v9.9.9", "body": " notes ", "html_url": "https://x"}).encode()
        with mock.patch("urllib.request.urlopen", return_value=_Response(body)):
            release = updater.fetch_latest_release()
        self.assertEqual((release.version, release.notes, release.url), ("9.9.9", "notes", "https://x"))

    def test_network_error_is_reported(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            with self.assertRaises(updater.UpdateError):
                updater.fetch_latest_release()

    def test_missing_tag_is_reported(self):
        with mock.patch("urllib.request.urlopen", return_value=_Response(b"{}")):
            with self.assertRaises(updater.UpdateError):
                updater.fetch_latest_release()


class FormatNotesTests(unittest.TestCase):
    def test_converts_markdown_to_plain_text(self):
        notes = "### Added\n- Use `setup_all`\n\n| Item | Size |\n|---|---|\n| Final EXE | 50.7 MB |"
        self.assertEqual(
            updater.format_notes(notes),
            "[Added]\n• Use setup_all\n\nItem: Size\nFinal EXE: 50.7 MB",
        )


class SeenVersionTests(unittest.TestCase):
    def test_notes_needed_until_marked(self):
        with tempfile.TemporaryDirectory() as home, mock.patch("pathlib.Path.home", return_value=Path(home)):
            self.assertTrue(updater.needs_release_notes())
            updater.mark_version_seen()
            self.assertFalse(updater.needs_release_notes())
            updater.mark_version_seen("0.0.1")
            self.assertTrue(updater.needs_release_notes())


class ReinstallEnvTests(unittest.TestCase):
    def test_frozen_env_targets_running_exe(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", r"C:\app\amv-cp-bridge.exe"):
            env = updater._reinstall_env()
        self.assertEqual(env["AMV_EXE_PATH"], r"C:\app\amv-cp-bridge.exe")
        self.assertEqual(env["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertTrue(env["AMV_WAIT_PID"].isdigit())

    def test_macos_script_carries_pid(self):
        self.assertTrue(updater.macos_terminal_script(42).startswith("AMV_WAIT_PID=42 bash -c "))


if __name__ == "__main__":
    unittest.main()
