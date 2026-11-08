import json
import time
import base64
import sys
import urllib.request
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

GATEWAY_URL = "http://127.0.0.1:11500"

def test_text_inference():
    print("\n" + "="*60)
    print("▶ [TEST 1] Text Inference & Streaming Verification")
    print("="*60)
    prompt = "Explain why the sky is blue in 2 concise sentences."
    req_body = {
        "model": "copilot-gpt4o",
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
    collected = []
    with urllib.request.urlopen(req, timeout=120) as resp:
        for line in resp:
            line_str = line.decode("utf-8").strip()
            if line_str.startswith("data: ") and line_str != "data: [DONE]":
                payload = json.loads(line_str[6:])
                delta = payload["choices"][0]["delta"].get("content", "")
                if delta:
                    collected.append(delta)
                    sys.stdout.write(delta)
                    sys.stdout.flush()
    elapsed = time.time() - t0
    full_text = "".join(collected)
    print(f"\n[+] Elapsed: {elapsed:.2f}s | Length: {len(full_text)} chars")
    assert len(full_text) > 0, "Text response is empty!"
    return {"elapsed": elapsed, "text": full_text[:100]}

def test_vision_inference():
    print("\n" + "="*60)
    print("▶ [TEST 2] Multimodal Vision Verification")
    print("="*60)
    # test_vision2.png has a blue square, orange circle, purple star, and text 'HELLO COPILOT 2026'
    img_path = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "01_multimodal_vision_input.png"
    if not img_path.exists():
        img_path = Path(r"C:\Users\GAME\.gemini\antigravity\brain\18d8f79c-cf0b-4b18-b9b3-d685cdb911c8\test_vision2.png")
    
    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    
    prompt = "Look at this image. What shapes and colors do you see, and is there any text written?"
    req_body = {
        "model": "copilot-gpt4o",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]
            }
        ],
        "stream": True
    }
    data = json.dumps(req_body).encode("utf-8")
    req = urllib.request.Request(
        f"{GATEWAY_URL}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    collected = []
    with urllib.request.urlopen(req, timeout=120) as resp:
        for line in resp:
            line_str = line.decode("utf-8").strip()
            if line_str.startswith("data: ") and line_str != "data: [DONE]":
                payload = json.loads(line_str[6:])
                delta = payload["choices"][0]["delta"].get("content", "")
                if delta:
                    collected.append(delta)
                    sys.stdout.write(delta)
                    sys.stdout.flush()
    elapsed = time.time() - t0
    full_text = "".join(collected)
    print(f"\n[+] Vision Elapsed: {elapsed:.2f}s | Length: {len(full_text)} chars")
    assert len(full_text) > 0, "Vision response is empty!"
    return {"elapsed": elapsed, "text": full_text[:100]}

def test_image_generation():
    print("\n" + "="*60)
    print("▶ [TEST 3] Image Generation (Copilot Designer) Verification")
    print("="*60)
    prompt = "Generate an image of an emerald crystal floating in deep cosmic space."
    req_body = {
        "model": "copilot-gpt4o",
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
    collected = []
    with urllib.request.urlopen(req, timeout=180) as resp:
        for line in resp:
            line_str = line.decode("utf-8").strip()
            if line_str.startswith("data: ") and line_str != "data: [DONE]":
                payload = json.loads(line_str[6:])
                delta = payload["choices"][0]["delta"].get("content", "")
                if delta:
                    collected.append(delta)
                    # Don't print the huge base64 to avoid flooding
                    if "data:image" in delta:
                        sys.stdout.write(f"\n[Received Image Data: {len(delta)} chars]\n")
                    else:
                        sys.stdout.write(delta)
                    sys.stdout.flush()
    elapsed = time.time() - t0
    full_text = "".join(collected)
    print(f"\n[+] Image Generation Elapsed: {elapsed:.2f}s | Length: {len(full_text)} chars")
    assert len(full_text) > 0, "Image generation response is empty!"
    has_image = "![" in full_text and ("](data:image" in full_text or "](http" in full_text or "](blob:" in full_text)
    print(f"[+] Markdown Image Tag Detected: {has_image}")
    return {"elapsed": elapsed, "has_image": has_image, "sample": full_text[:150]}

if __name__ == "__main__":
    results = {}
    try:
        results["text"] = test_text_inference()
        results["vision"] = test_vision_inference()
        results["image_gen"] = test_image_generation()
        print("\n" + "="*60)
        print("🎉 ALL 3 TORTURE TESTS PASSED!")
        print("="*60)
        print(json.dumps(results, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"\n❌ Test Failed with Exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
