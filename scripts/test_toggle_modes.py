import json
import time
import sys
import urllib.request

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

GATEWAY_URL = "http://127.0.0.1:11500"

def test_stream(req_body, test_name):
    print("=" * 65)
    print(f"▶ [TEST] {test_name}")
    print(f"[*] Payload: {json.dumps(req_body, ensure_ascii=False)}")
    print("=" * 65)

    data = json.dumps(req_body).encode("utf-8")
    req = urllib.request.Request(
        f"{GATEWAY_URL}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"}
    )

    t0 = time.time()
    collected_reasoning = []
    collected_content = []

    with urllib.request.urlopen(req, timeout=120) as resp:
        for line in resp:
            line_str = line.decode("utf-8").strip()
            if line_str.startswith("data: ") and line_str != "data: [DONE]":
                payload = json.loads(line_str[6:])
                delta = payload["choices"][0]["delta"]
                if "reasoning_content" in delta:
                    collected_reasoning.append(delta["reasoning_content"])
                if "content" in delta:
                    c = delta["content"]
                    if c:
                        collected_content.append(c)

    elapsed = time.time() - t0
    r_text = "".join(collected_reasoning)
    c_text = "".join(collected_content)

    print(f"[+] Elapsed: {elapsed:.2f}s")
    print(f"[+] reasoning_content chars: {len(r_text)}")
    print(f"[+] content chars: {len(c_text)}")
    print(f"[+] Content sample: {c_text[:100]}...")
    return len(r_text), len(c_text)

def run_tests():
    # 1. Test Mode OFF (Direct Fast Mode)
    print("\n--- TEST 1: Deep Thinking OFF (Direct Fast Mode) ---")
    r_len, c_len = test_stream({
        "model": "gpt-5.6-sol",
        "messages": [{"role": "user", "content": "1+1은 뭐야? 단답형으로 숫자만 말해줘."}],
        "stream": True,
        "deepthink": False
    }, "Deep Thinking OFF (Explicit deepthink: False)")
    assert r_len == 0, f"Expected 0 reasoning chars, got {r_len}"
    assert c_len > 0, "Content should not be empty"
    print("✔ Mode OFF correctly yielded ZERO reasoning_content chunks!")

    # 2. Test Mode ON (Deep Thinking Reasoning Mode)
    print("\n--- TEST 2: Deep Thinking ON (Structured Reasoning Mode) ---")
    r_len, c_len = test_stream({
        "model": "copilot-deepthink",
        "messages": [{"role": "user", "content": "1+1이 2인 이유를 Peano 공리계를 바탕으로 분석해줘."}],
        "stream": True,
        "deepthink": True
    }, "Deep Thinking ON (Explicit deepthink: True)")
    assert r_len > 0, f"Expected reasoning chars, got {r_len}"
    assert c_len > 0, "Content should not be empty"
    print(f"✔ Mode ON correctly yielded {r_len} reasoning_content chunks!")

    print("\n" + "=" * 65)
    print("🎉 ALL TOGGLE TESTS PASSED 100%!")
    print("=" * 65)

if __name__ == "__main__":
    run_tests()
