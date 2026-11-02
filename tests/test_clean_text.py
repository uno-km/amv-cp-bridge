# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["USERPROFILE"] = os.environ["HOME"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amv_cp_bridge.engine import CopilotWorker  # noqa: E402


class CleanTextTest(unittest.TestCase):
    def setUp(self):
        self.clean = CopilotWorker(9999, "test", "unused", ephemeral_mode=True)._clean_text

    def test_answer_words_are_kept(self):
        answer = "파일을 복사하고 편집한 뒤 공유합니다. 새로 고침은 작업 중...에 하지 않습니다."
        self.assertEqual(self.clean(answer), answer)

    def test_status_before_answer_is_removed(self):
        self.assertEqual(self.clean("진행 중…2"), "2")
        self.assertEqual(self.clean("준비 중입니다…\n생각 중...\n답변"), "답변")

    def test_status_only_is_empty(self):
        self.assertEqual(self.clean("진행 중…"), "")
        self.assertEqual(self.clean("진행 중..."), "")

    def test_button_labels_on_own_line_are_removed(self):
        self.assertEqual(self.clean("답변 본문\n복사\n공유\n좋아요\n싫어요"), "답변 본문")

    def test_copilot_said_prefix_is_removed(self):
        self.assertEqual(self.clean("Copilot said:\n답변"), "답변")


if __name__ == "__main__":
    unittest.main()
