/**
 * Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0 OR Commercial-License
 */

// 사이드 패널 기본 동작: 액션 아이콘 클릭 시 사이드패널 오픈
if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
}

// 컨텍스트 메뉴(우클릭 메뉴) 생성
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "copilot-explain-selection",
    title: "Copilot 365로 심층 분석하기",
    contexts: ["selection"]
  });

  chrome.contextMenus.create({
    id: "copilot-summarize-page",
    title: "Copilot 365로 이 웹페이지 요약하기",
    contexts: ["page"]
  });
});

// 컨텍스트 메뉴 클릭 핸들러
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (!tab || !tab.id) return;

  // 사이드 패널 열기
  if (chrome.sidePanel && chrome.sidePanel.open) {
    try {
      await chrome.sidePanel.open({ tabId: tab.id });
    } catch (e) {
      console.warn("Failed to open side panel:", e);
    }
  }

  let prompt = "";
  if (info.menuItemId === "copilot-explain-selection" && info.selectionText) {
    prompt = `다음 텍스트에 대해 핵심 요약과 심층 분석을 제공해줘:\n\n"${info.selectionText}"`;
  } else if (info.menuItemId === "copilot-summarize-page" && tab.url) {
    prompt = `현재 페이지(${tab.title || tab.url})의 핵심 내용을 개요, 주요 포인트, 결론으로 나누어 3줄 이내로 명확히 요약해줘.`;
  }

  if (prompt) {
    // 사이드패널이 로드된 후 전달받을 수 있도록 스토리지에 큐잉
    await chrome.storage.local.set({
      pendingPrompt: {
        text: prompt,
        timestamp: Date.now()
      }
    });

    // 이미 열려있는 사이드패널에 실시간 메시지 발송
    chrome.runtime.sendMessage({
      type: "TRIGGER_PROMPT",
      prompt: prompt
    }).catch(() => {});
  }
});
