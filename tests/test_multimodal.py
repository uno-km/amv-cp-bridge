# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
Unit tests for Multimodal Vision & File Attachment in amv-cp-bridge v1.2.0.
Pure standard library unittest — compatible with isolated build virtual environments.
"""

import os
import unittest
import tempfile
from pathlib import Path
from amv_cp_bridge.gateway import (
    ChatMessage,
    ChatCompletionRequest,
    parse_messages_and_files,
    cleanup_temp_files,
)

SAMPLE_PNG_B64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


class TestMultimodal(unittest.TestCase):
    def test_parse_plain_text(self):
        messages = [
            ChatMessage(role="system", content="시스템 프롬프트"),
            ChatMessage(role="user", content="일반 텍스트 질문입니다."),
        ]
        prompt, file_paths, temp_files = parse_messages_and_files(messages, "gpt-5.6-sol")

        self.assertIn("[시스템]: 시스템 프롬프트", prompt)
        self.assertIn("[질문]: 일반 텍스트 질문입니다.", prompt)
        self.assertEqual(len(file_paths), 0)
        self.assertEqual(len(temp_files), 0)

    def test_parse_vision_base64_image(self):
        messages = [
            ChatMessage(
                role="user",
                content=[
                    {"type": "text", "text": "이 이미지를 분석하고 코드를 작성해줘."},
                    {"type": "image_url", "image_url": {"url": SAMPLE_PNG_B64}}
                ]
            )
        ]
        prompt, file_paths, temp_files = parse_messages_and_files(messages, "gpt-5.6-sol")

        self.assertIn("이 이미지를 분석하고 코드를 작성해줘.", prompt)
        self.assertEqual(len(file_paths), 1)
        self.assertEqual(len(temp_files), 1)

        tmp_path = Path(file_paths[0])
        self.assertTrue(tmp_path.is_file())
        self.assertEqual(tmp_path.suffix, ".png")
        self.assertTrue(tmp_path.read_bytes().startswith(b"\x89PNG"))

        cleanup_temp_files(temp_files)
        self.assertFalse(tmp_path.exists())

    def test_parse_nested_image_url_dict(self):
        messages = [
            ChatMessage(
                role="user",
                content=[
                    {"type": "text", "text": "스캔해줘"},
                    {"type": "image_url", "image_url": SAMPLE_PNG_B64}
                ]
            )
        ]
        prompt, file_paths, temp_files = parse_messages_and_files(messages, "gpt-5.6-sol")

        self.assertIn("스캔해줘", prompt)
        self.assertEqual(len(file_paths), 1)
        self.assertTrue(Path(file_paths[0]).is_file())

        cleanup_temp_files(temp_files)
        self.assertFalse(Path(file_paths[0]).exists())

    def test_parse_local_file_path(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"dummy pdf content")
            local_path = f.name

        try:
            messages = [
                ChatMessage(
                    role="user",
                    content=[
                        {"type": "text", "text": "문서 검토"},
                        {"type": "file_path", "path": local_path}
                    ]
                )
            ]
            prompt, file_paths, temp_files = parse_messages_and_files(messages, "gpt-5.6-sol")

            self.assertIn("문서 검토", prompt)
            self.assertEqual(len(file_paths), 1)
            self.assertEqual(file_paths[0], local_path)
            self.assertEqual(len(temp_files), 0)

            cleanup_temp_files(temp_files)
            self.assertTrue(os.path.isfile(local_path))
        finally:
            if os.path.isfile(local_path):
                os.unlink(local_path)

    def test_chat_completion_request_pydantic_validation(self):
        payload = {
            "model": "gpt-5.6-sol",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Look at this UI screenshot"},
                        {"type": "image_url", "image_url": {"url": SAMPLE_PNG_B64}}
                    ]
                }
            ]
        }
        req = ChatCompletionRequest(**payload)
        self.assertEqual(req.model, "gpt-5.6-sol")
        self.assertEqual(len(req.messages), 1)
        self.assertIsInstance(req.messages[0].content, list)
