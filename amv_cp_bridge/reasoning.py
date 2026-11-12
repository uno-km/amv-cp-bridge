"""
amv_cp_bridge/reasoning.py — OpenAI o1/o3 & DeepSeek-R1 호환 reasoning_content 파서

<think>...</think> 태그 또는 구조화된 논리적 추론 블록(Step-by-Step Analysis)을 실시간으로 감지하여
OpenAI 표준 choices[0].delta.reasoning_content 와 delta.content 로 스트리밍을 분리합니다.
"""

import re
from typing import Optional, Tuple, Dict, Any

THINK_OPEN_TAG = "<think>"
THINK_CLOSE_TAG = "</think>"

# 대체 추론 마커 패턴 (Copilot 엔터프라이즈 가드레일 우회용 구조화 블록)
REASONING_START_PATTERNS = [
    r"^(?:###\s*)?(?:1\.\s*)?Step-by-Step Logical Analysis\s*:?",
    r"^\[(?:추론|사고\s*과정|논리\s*분석)\]\s*:?",
    r"^Thought Process\s*:?",
]

CONTENT_START_PATTERNS = [
    r"(?:###\s*)?(?:2\.\s*)?Final Conclusion\s*:?",
    r"(?:###\s*)?(?:2\.\s*)?Final Answer\s*:?",
    r"\[(?:최종\s*답변|결론)\]\s*:?",
]


def extract_reasoning_and_content(full_text: str) -> Tuple[Optional[str], str]:
    """
    완성된 텍스트에서 reasoning_content와 최종 content를 분리합니다.
    분리할 reasoning이 없으면 (None, full_text)를 반환합니다.
    """
    if not full_text:
        return None, ""

    # 1. <think>...</think> 태그 형식
    if THINK_OPEN_TAG in full_text:
        parts = full_text.split(THINK_OPEN_TAG, 1)[1]
        if THINK_CLOSE_TAG in parts:
            reasoning, content = parts.split(THINK_CLOSE_TAG, 1)
            return reasoning.strip(), content.strip()
        else:
            # 아직 닫히지 않았거나 끝까지 think인 경우
            return parts.strip(), ""

    # 2. 구조화된 마커 형식 (1. Step-by-Step Logical Analysis ... 2. Final Conclusion)
    for c_pat in CONTENT_START_PATTERNS:
        c_match = re.search(c_pat, full_text, re.IGNORECASE | re.MULTILINE)
        if c_match:
            pre_text = full_text[:c_match.start()].strip()
            post_text = full_text[c_match.end():].strip()
            
            # pre_text가 추론 시작 패턴으로 시작하는지 확인
            for r_pat in REASONING_START_PATTERNS:
                r_match = re.search(r_pat, pre_text, re.IGNORECASE | re.MULTILINE)
                if r_match:
                    reasoning = pre_text[r_match.end():].strip()
                    return reasoning, post_text
            
            # 시작 패턴이 명시적이지 않더라도 결론 마커 이전은 추론으로 간주 가능
            if len(pre_text) > 20:
                return pre_text, post_text

    return None, full_text


class ReasoningStreamParser:
    """
    실시간 스트리밍 중 수신되는 누적 텍스트를 감시하며
    (reasoning_delta, content_delta)를 생성하는 상태 머신 파서.
    """
    def __init__(self, force_thinking_mode: bool = False):
        self.force_thinking_mode = force_thinking_mode
        self.emitted_reasoning = ""
        self.emitted_content = ""
        self.has_detected_reasoning = False
        self.in_content_phase = False

    def feed(self, current_text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        현재까지 누적된 전체 정제 텍스트(current_text)를 입력받아
        새로 방출할 (reasoning_delta, content_delta)를 반환합니다.
        """
        if not current_text:
            return None, None

        reasoning_part: Optional[str] = None
        content_part: str = ""

        # 1. <think> 태그 기반 파싱
        if THINK_OPEN_TAG in current_text:
            self.has_detected_reasoning = True
            after_open = current_text.split(THINK_OPEN_TAG, 1)[1]
            if THINK_CLOSE_TAG in after_open:
                r_text, c_text = after_open.split(THINK_CLOSE_TAG, 1)
                reasoning_part = r_text
                content_part = c_text.lstrip("\n")
                self.in_content_phase = True
            else:
                reasoning_part = after_open
                content_part = ""
        else:
            # 2. 구조화 마커 기반 파싱
            c_found = False
            for c_pat in CONTENT_START_PATTERNS:
                c_match = re.search(c_pat, current_text, re.IGNORECASE | re.MULTILINE)
                if c_match:
                    self.has_detected_reasoning = True
                    self.in_content_phase = True
                    pre = current_text[:c_match.start()].rstrip()
                    # 시작 마커 제거
                    for r_pat in REASONING_START_PATTERNS:
                        r_match = re.search(r_pat, pre, re.IGNORECASE | re.MULTILINE)
                        if r_match:
                            pre = pre[r_match.end():].lstrip("\n")
                            break
                    reasoning_part = pre
                    content_part = current_text[c_match.end():].lstrip("\n")
                    c_found = True
                    break

            if not c_found:
                if self.has_detected_reasoning and not self.in_content_phase:
                    reasoning_part = current_text
                elif self.force_thinking_mode and not self.in_content_phase:
                    # 시작 마커가 아직 안 닫힌 경우
                    for r_pat in REASONING_START_PATTERNS:
                        r_match = re.search(r_pat, current_text, re.IGNORECASE | re.MULTILINE)
                        if r_match:
                            self.has_detected_reasoning = True
                            reasoning_part = current_text[r_match.end():].lstrip("\n")
                            break
                    if not self.has_detected_reasoning:
                        content_part = current_text
                else:
                    content_part = current_text

        # 델타 계산
        r_delta: Optional[str] = None
        c_delta: Optional[str] = None

        if reasoning_part is not None:
            if len(reasoning_part) > len(self.emitted_reasoning):
                r_delta = reasoning_part[len(self.emitted_reasoning):]
                self.emitted_reasoning = reasoning_part
            elif not reasoning_part.startswith(self.emitted_reasoning) and len(reasoning_part) > 0:
                r_delta = reasoning_part
                self.emitted_reasoning = reasoning_part

        if content_part:
            if len(content_part) > len(self.emitted_content):
                c_delta = content_part[len(self.emitted_content):]
                self.emitted_content = content_part
            elif not content_part.startswith(self.emitted_content) and len(content_part) > 0:
                c_delta = content_part
                self.emitted_content = content_part

        return r_delta, c_delta
