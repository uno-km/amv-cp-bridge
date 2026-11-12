import unittest
from amv_cp_bridge.reasoning import ReasoningStreamParser, extract_reasoning_and_content
from amv_cp_bridge.gateway import resolve_is_deepthink, parse_messages_and_files, ChatMessage

class TestReasoningParser(unittest.TestCase):
    def test_extract_think_tags(self):
        text = "<think>\nStep 1: Check heat.\nStep 2: Check light.\n</think>\n\nFinal Answer: Switch B."
        reasoning, content = extract_reasoning_and_content(text)
        self.assertEqual(reasoning, "Step 1: Check heat.\nStep 2: Check light.")
        self.assertEqual(content, "Final Answer: Switch B.")

    def test_extract_structured_sections(self):
        text = "### 1. Step-by-Step Logical Analysis\nWe deduce using bulb heat.\n\n### 2. Final Conclusion\nSwitch A is correct."
        reasoning, content = extract_reasoning_and_content(text)
        self.assertEqual(reasoning, "We deduce using bulb heat.")
        self.assertEqual(content, "Switch A is correct.")

    def test_extract_no_reasoning(self):
        text = "The capital of France is Paris."
        reasoning, content = extract_reasoning_and_content(text)
        self.assertIsNone(reasoning)
        self.assertEqual(content, text)

    def test_stream_parser_think_tags(self):
        parser = ReasoningStreamParser()
        
        # Chunk 1: <think>
        r, c = parser.feed("<think>")
        self.assertIsNone(r)
        self.assertIsNone(c)
        
        # Chunk 2: <think>Step 1
        r, c = parser.feed("<think>Step 1")
        self.assertEqual(r, "Step 1")
        self.assertIsNone(c)
        
        # Chunk 3: <think>Step 1 and 2</think>Answer
        r, c = parser.feed("<think>Step 1 and 2</think>Answer")
        self.assertEqual(r, " and 2")
        self.assertEqual(c, "Answer")

    def test_stream_parser_structured_sections(self):
        parser = ReasoningStreamParser(force_thinking_mode=True)
        
        # Chunk 1
        r, c = parser.feed("### 1. Step-by-Step Logical Analysis\nTesting heat")
        self.assertEqual(r, "Testing heat")
        self.assertIsNone(c)
        
        # Chunk 2
        r, c = parser.feed("### 1. Step-by-Step Logical Analysis\nTesting heat and light\n\n### 2. Final Conclusion\nSwitch A")
        self.assertEqual(r, " and light")
        self.assertEqual(c, "Switch A")

    def test_resolve_is_deepthink_toggle_rules(self):
        # 1. Default standard model should NOT trigger reasoning when global setting is False
        self.assertFalse(resolve_is_deepthink(model_name="gpt-5.6-sol", global_setting=False))
        self.assertFalse(resolve_is_deepthink(model_name="copilot", global_setting=False))

        # 2. Global setting toggle ON should enable reasoning for standard models
        self.assertTrue(resolve_is_deepthink(model_name="gpt-5.6-sol", global_setting=True))

        # 3. Explicit request parameter overrides everything
        self.assertTrue(resolve_is_deepthink(req_deepthink=True, model_name="gpt-5.6-sol", global_setting=False))
        self.assertFalse(resolve_is_deepthink(req_deepthink=False, model_name="copilot-deepthink", global_setting=True))

        # 4. reasoning_effort (OpenAI o1 standard)
        self.assertFalse(resolve_is_deepthink(reasoning_effort="none", model_name="copilot-deepthink"))
        self.assertTrue(resolve_is_deepthink(reasoning_effort="high", model_name="gpt-5.6-sol"))

        # 5. HTTP Header
        self.assertTrue(resolve_is_deepthink(header_deepthink="true", model_name="gpt-5.6-sol"))
        self.assertFalse(resolve_is_deepthink(header_deepthink="false", model_name="copilot-deepthink"))

        # 6. Model name heuristics
        self.assertTrue(resolve_is_deepthink(model_name="copilot-deepthink"))
        self.assertTrue(resolve_is_deepthink(model_name="deepseek-r1"))
        self.assertTrue(resolve_is_deepthink(model_name="o1-preview"))

    def test_parse_messages_directive_toggle(self):
        msgs = [ChatMessage(role="user", content="Hello")]
        prompt_off, _, _ = parse_messages_and_files(msgs, "gpt-5.6-sol", is_reasoning=False)
        self.assertNotIn("[Structured Reasoning Directive]", prompt_off)
        self.assertIn("[질문]: Hello", prompt_off)

        prompt_on, _, _ = parse_messages_and_files(msgs, "gpt-5.6-sol", is_reasoning=True)
        self.assertIn("[Structured Reasoning Directive]", prompt_on)
        self.assertIn("[질문]: Hello", prompt_on)

if __name__ == "__main__":
    unittest.main()
