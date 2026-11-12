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

def test_live_deepthink_streaming():
    print("="*65)
    print("▶ [LIVE E2E TEST] Deep Thinking & reasoning_content Separation")
    print("="*65)
    
    prompt = "There are 3 switches outside a closed room. Inside the room is one incandescent light bulb. You can only enter the room once. How do you figure out which switch controls the light bulb?"
    
    # Request with model='copilot-deepthink' and stream=True
    req_body = {
        "model": "copilot-deepthink",
        "messages": [{"role": "user", "content": prompt}],
        "stream": True
    }
    
    data = json.dumps(req_body).encode("utf-8")
    req = urllib.request.Request(
        f"{GATEWAY_URL}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    
    t0 = time.time()
    collected_reasoning = []
    collected_content = []
    
    print("[*] Sending request to /v1/chat/completions (model: copilot-deepthink)...")
    with urllib.request.urlopen(req, timeout=120) as resp:
        for line in resp:
            line_str = line.decode("utf-8").strip()
            if line_str.startswith("data: ") and line_str != "data: [DONE]":
                payload = json.loads(line_str[6:])
                delta = payload["choices"][0]["delta"]
                
                # Check for reasoning_content vs content
                if "reasoning_content" in delta:
                    r_tok = delta["reasoning_content"]
                    collected_reasoning.append(r_tok)
                    sys.stdout.write(f"\033[33m{r_tok}\033[0m")  # Yellow for thinking
                    sys.stdout.flush()
                elif "content" in delta:
                    c_tok = delta["content"]
                    if c_tok:
                        if not collected_content:
                            print("\n\n" + "-"*40 + " [FINAL CONTENT START] " + "-"*40)
                        collected_content.append(c_tok)
                        sys.stdout.write(f"\033[32m{c_tok}\033[0m")  # Green for answer
                        sys.stdout.flush()

    elapsed = time.time() - t0
    full_reasoning = "".join(collected_reasoning)
    full_content = "".join(collected_content)
    
    print("\n" + "="*65)
    print(f"[+] Total Elapsed Time: {elapsed:.2f}s")
    print(f"[+] Extracted reasoning_content length: {len(full_reasoning)} chars")
    print(f"[+] Extracted content length: {len(full_content)} chars")
    print("="*65)
    
    assert len(full_reasoning) > 0, "reasoning_content was not extracted!"
    assert len(full_content) > 0, "content was empty!"
    
    print("🎉 DEEP THINKING REASONING_CONTENT STREAMING VERIFIED 100%!")
    return {
        "elapsed": elapsed,
        "reasoning_len": len(full_reasoning),
        "content_len": len(full_content),
        "reasoning_sample": full_reasoning[:120],
        "content_sample": full_content[:120]
    }

if __name__ == "__main__":
    test_live_deepthink_streaming()
