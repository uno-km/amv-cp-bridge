/**
 * Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0 OR Commercial-License
 */

const DEFAULT_GATEWAY = "http://127.0.0.1:11500/v1";
const DEFAULT_MODEL = "gpt-5.6-sol";

let gatewayUrl = DEFAULT_GATEWAY;
let selectedModel = DEFAULT_MODEL;
let messageHistory = [];
let isInferring = false;

// DOM Elements
const statusPill = document.getElementById("statusPill");
const settingsBtn = document.getElementById("settingsBtn");
const settingsDrawer = document.getElementById("settingsDrawer");
const gatewayUrlInput = document.getElementById("gatewayUrlInput");
const modelSelect = document.getElementById("modelSelect");
const saveSettingsBtn = document.getElementById("saveSettingsBtn");
const testGatewayBtn = document.getElementById("testGatewayBtn");
const clearBtn = document.getElementById("clearBtn");
const chatViewport = document.getElementById("chatViewport");
const welcomeCard = document.getElementById("welcomeCard");
const chatForm = document.getElementById("chatForm");
const promptInput = document.getElementById("promptInput");
const sendBtn = document.getElementById("sendBtn");
const currentModelLabel = document.getElementById("currentModelLabel");

// 1. Settings Init
async function initSettings() {
  try {
    const data = await chrome.storage.local.get(["gatewayUrl", "selectedModel"]);
    if (data.gatewayUrl) gatewayUrl = data.gatewayUrl;
    if (data.selectedModel) selectedModel = data.selectedModel;

    gatewayUrlInput.value = gatewayUrl;
    modelSelect.value = selectedModel;
    currentModelLabel.textContent = selectedModel;
  } catch (e) {
    console.warn("Storage access fallback:", e);
  }
  checkGatewayHealth();
}

function updateStatus(state, label) {
  const dot = statusPill.querySelector(".status-dot");
  if (dot) {
    dot.className = `status-dot status-${state}`;
  }
}

// 2. Health Check
async function checkGatewayHealth() {
  try {
    const rootUrl = gatewayUrl.replace(/\/v1\/?$/, "");
    const res = await fetch(`${rootUrl}/health`, { method: "GET", signal: AbortSignal.timeout(2500) });
    if (res.ok) {
      updateStatus("idle");
    } else {
      updateStatus("offline");
    }
  } catch {
    updateStatus("offline");
  }
}

// 3. Simple Markdown Parser
function formatMarkdown(text) {
  if (!text) return "";
  let esc = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Code blocks: ```lang ... ```
  esc = esc.replace(/```([\w-]*)\n([\s\S]*?)```/g, (_, lang, code) => {
    return `<pre><code class="language-${lang}">${code.trim()}</code></pre>`;
  });

  // Inline code: `...`
  esc = esc.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Bold: **...**
  esc = esc.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

  // Newlines to <br>
  esc = esc.replace(/\n/g, '<br>');

  return esc;
}

// 4. Message Rendering
function appendUserMessage(text) {
  if (welcomeCard) welcomeCard.style.display = "none";

  const wrap = document.createElement("div");
  wrap.className = "msg-wrapper user";
  wrap.setAttribute("data-raw-content", text);

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.innerHTML = formatMarkdown(text);

  const meta = document.createElement("div");
  meta.className = "msg-meta";
  const nameSpan = document.createElement("span");
  nameSpan.textContent = "나";
  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "copy-msg-btn";
  copyBtn.title = "복사";
  copyBtn.textContent = "복사";
  copyBtn.addEventListener("click", () => {
    navigator.clipboard.writeText(text);
    copyBtn.textContent = "복사됨 ✓";
    setTimeout(() => { copyBtn.textContent = "복사"; }, 1500);
  });
  meta.appendChild(nameSpan);
  meta.appendChild(copyBtn);

  wrap.appendChild(bubble);
  wrap.appendChild(meta);
  chatViewport.appendChild(wrap);
  chatViewport.scrollTop = chatViewport.scrollHeight;
}

function appendAssistantMessagePlaceholder() {
  if (welcomeCard) welcomeCard.style.display = "none";

  const wrap = document.createElement("div");
  wrap.className = "msg-wrapper assistant";
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.innerHTML = `<span class="typing-cursor"></span>`;

  const meta = document.createElement("div");
  meta.className = "msg-meta";
  meta.innerHTML = `
    <span>${selectedModel}</span>
    <button type="button" class="copy-msg-btn" title="복사">복사</button>
  `;

  meta.querySelector(".copy-msg-btn").addEventListener("click", () => {
    const raw = wrap.getAttribute("data-raw-content") || "";
    navigator.clipboard.writeText(raw);
    meta.querySelector(".copy-msg-btn").textContent = "복사됨 ✓";
    setTimeout(() => { meta.querySelector(".copy-msg-btn").textContent = "복사"; }, 1500);
  });

  wrap.appendChild(bubble);
  wrap.appendChild(meta);
  chatViewport.appendChild(wrap);
  chatViewport.scrollTop = chatViewport.scrollHeight;

  return { wrap, bubble };
}

// 5. Send Prompt & Streaming Execution
async function sendPrompt(promptText) {
  if (!promptText || isInferring) return;
  isInferring = true;
  sendBtn.disabled = true;
  updateStatus("busy");

  appendUserMessage(promptText);
  messageHistory.push({ role: "user", content: promptText });

  const { wrap, bubble } = appendAssistantMessagePlaceholder();
  let accumulated = "";

  try {
    const endpoint = `${gatewayUrl.replace(/\/$/, "")}/chat/completions`;
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Bridge-Source": "extension" },
      body: JSON.stringify({
        model: selectedModel,
        messages: messageHistory,
        stream: true
      })
    });

    if (!response.ok) {
      throw new Error(`HTTP Error ${response.status}: ${await response.text()}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop(); // keep remainder

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith("data:")) continue;
        const payload = trimmed.replace(/^data:\s*/, "");
        if (payload === "[DONE]") break;

        try {
          const parsed = json_safe_parse(payload);
          if (parsed && parsed.choices && parsed.choices[0] && parsed.choices[0].delta) {
            const content = parsed.choices[0].delta.content || "";
            if (content) {
              accumulated += content;
              bubble.innerHTML = formatMarkdown(accumulated) + `<span class="typing-cursor"></span>`;
              chatViewport.scrollTop = chatViewport.scrollHeight;
            }
          }
        } catch {}
      }
    }

    // Finalize
    bubble.innerHTML = formatMarkdown(accumulated);
    wrap.setAttribute("data-raw-content", accumulated);
    messageHistory.push({ role: "assistant", content: accumulated });

  } catch (err) {
    bubble.innerHTML = `<span style="color: var(--accent-rose);">[오류] 질의 실패: ${err.message}</span>`;
    wrap.setAttribute("data-raw-content", err.message);
  } finally {
    isInferring = false;
    sendBtn.disabled = false;
    updateStatus("idle");
    chatViewport.scrollTop = chatViewport.scrollHeight;
    promptInput.focus();
  }
}

function json_safe_parse(str) {
  try { return JSON.parse(str); } catch { return null; }
}

// 6. Event Listeners
chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = promptInput.value.trim();
  if (text) {
    promptInput.value = "";
    promptInput.style.height = "auto";
    sendPrompt(text);
  }
});

promptInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    chatForm.dispatchEvent(new Event("submit"));
  }
});

// Auto-expand textarea
promptInput.addEventListener("input", () => {
  promptInput.style.height = "auto";
  promptInput.style.height = Math.min(promptInput.scrollHeight, 120) + "px";
});

// Settings Toggle
settingsBtn.addEventListener("click", () => {
  const isHidden = settingsDrawer.style.display === "none";
  settingsDrawer.style.display = isHidden ? "flex" : "none";
});

saveSettingsBtn.addEventListener("click", async () => {
  gatewayUrl = gatewayUrlInput.value.trim() || DEFAULT_GATEWAY;
  selectedModel = modelSelect.value || DEFAULT_MODEL;
  currentModelLabel.textContent = selectedModel;
  settingsDrawer.style.display = "none";

  try {
    await chrome.storage.local.set({ gatewayUrl, selectedModel });
  } catch {}
  checkGatewayHealth();
});

testGatewayBtn.addEventListener("click", async () => {
  testGatewayBtn.textContent = "테스트 중...";
  try {
    const rootUrl = gatewayUrlInput.value.trim().replace(/\/v1\/?$/, "");
    const res = await fetch(`${rootUrl}/health`, { signal: AbortSignal.timeout(3000) });
    if (res.ok) {
      testGatewayBtn.textContent = "연결 성공 ✓";
    } else {
      testGatewayBtn.textContent = "응답 오류 ✗";
    }
  } catch {
    testGatewayBtn.textContent = "접속 실패 ✗";
  }
  setTimeout(() => { testGatewayBtn.textContent = "연결 테스트"; }, 2000);
});

// Clear Chat
clearBtn.addEventListener("click", () => {
  messageHistory = [];
  chatViewport.innerHTML = "";
  if (welcomeCard) {
    chatViewport.appendChild(welcomeCard);
    welcomeCard.style.display = "block";
  }
});

// 7. Check for pending prompt from context menus (Background.js)
async function checkPendingPrompt() {
  try {
    const data = await chrome.storage.local.get("pendingPrompt");
    if (data.pendingPrompt && data.pendingPrompt.text) {
      const age = Date.now() - (data.pendingPrompt.timestamp || 0);
      if (age < 30000) { // within 30 seconds
        sendPrompt(data.pendingPrompt.text);
      }
      await chrome.storage.local.remove("pendingPrompt");
    }
  } catch {}
}

// Runtime message listener from background.js
chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "TRIGGER_PROMPT" && msg.prompt) {
    sendPrompt(msg.prompt);
  }
});

// Initialize on Load
initSettings();
checkPendingPrompt();
