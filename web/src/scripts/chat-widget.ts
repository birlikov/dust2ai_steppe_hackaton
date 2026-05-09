/**
 * Chat widget — floating button + panel, bottom-right.
 *
 * Covers w3 (on-site assistant):
 *   - Greets on open
 *   - POSTs each message to /api/chat with session_id (persisted in localStorage)
 *   - Typing indicator while awaiting reply
 *   - 502 error shows the specified copy
 *   - Keyboard-accessible; aria-live="polite" on message log
 *
 * No React, no framework. Plain TypeScript compiled by Astro.
 */

const API_BASE =
  (window as unknown as Record<string, string>).__HAPPYCAKE_API_BASE__ ??
  "http://localhost:8000";

const SESSION_KEY = "hc_chat_session_id";

// ─── State ────────────────────────────────────────────────────────────────────

let sessionId: string | null = localStorage.getItem(SESSION_KEY);
let isOpen = false;
let isLoading = false;

// ─── DOM construction ──────────────────────────────────────────────────────────

function buildWidget(): void {
  const style = document.createElement("style");
  style.textContent = `
    #hc-chat-fab {
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 9999;
      background: #1B4868;
      color: #FBF6E8;
      border: none;
      border-radius: 0;
      width: 56px;
      height: 56px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 22px;
      box-shadow: 0 2px 8px rgba(14,42,60,0.25);
      transition: background 0.15s;
    }
    #hc-chat-fab:hover, #hc-chat-fab:focus {
      background: #0E2A3C;
      outline: 2px solid #3B7BA8;
      outline-offset: 2px;
    }
    #hc-chat-panel {
      position: fixed;
      bottom: 92px;
      right: 24px;
      z-index: 9998;
      width: 340px;
      max-width: calc(100vw - 48px);
      background: #FBF6E8;
      border: 0.5px solid rgba(14,42,60,0.25);
      display: flex;
      flex-direction: column;
      max-height: 480px;
      box-shadow: 0 4px 16px rgba(14,42,60,0.15);
    }
    #hc-chat-panel[hidden] { display: none; }
    #hc-chat-header {
      background: #0E2A3C;
      color: #FBF6E8;
      padding: 12px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-family: Inter, system-ui, sans-serif;
      font-size: 13px;
      font-weight: 500;
    }
    #hc-chat-close {
      background: none;
      border: none;
      color: #BFD8E8;
      cursor: pointer;
      font-size: 16px;
      padding: 0 4px;
      line-height: 1;
    }
    #hc-chat-close:hover, #hc-chat-close:focus {
      color: #FBF6E8;
      outline: 1px solid #3B7BA8;
    }
    #hc-chat-log {
      flex: 1;
      overflow-y: auto;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      font-family: Inter, system-ui, sans-serif;
      font-size: 13px;
    }
    .hc-msg {
      max-width: 85%;
      padding: 8px 12px;
      line-height: 1.5;
      border: 0.5px solid rgba(14,42,60,0.15);
    }
    .hc-msg-assistant {
      background: #F4ECD3;
      color: #1A1816;
      align-self: flex-start;
    }
    .hc-msg-user {
      background: #1B4868;
      color: #FBF6E8;
      align-self: flex-end;
    }
    .hc-msg-error {
      background: #F4ECD3;
      color: #1A1816;
      border-color: #E08066;
      align-self: flex-start;
      font-style: italic;
    }
    .hc-typing {
      background: #F4ECD3;
      color: #3B7BA8;
      align-self: flex-start;
      padding: 8px 12px;
      font-style: italic;
      font-size: 12px;
      border: 0.5px solid rgba(14,42,60,0.15);
    }
    #hc-chat-form {
      display: flex;
      border-top: 0.5px solid rgba(14,42,60,0.15);
    }
    #hc-chat-input {
      flex: 1;
      border: none;
      padding: 10px 12px;
      font-family: Inter, system-ui, sans-serif;
      font-size: 13px;
      background: #FBF6E8;
      color: #1A1816;
      outline: none;
    }
    #hc-chat-input:focus {
      box-shadow: inset 0 0 0 2px #3B7BA8;
    }
    #hc-chat-send {
      background: #1B4868;
      color: #FBF6E8;
      border: none;
      padding: 10px 16px;
      cursor: pointer;
      font-size: 13px;
      font-family: Inter, system-ui, sans-serif;
      transition: background 0.15s;
    }
    #hc-chat-send:hover, #hc-chat-send:focus {
      background: #0E2A3C;
      outline: 2px solid #3B7BA8;
    }
    #hc-chat-send:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  `;
  document.head.appendChild(style);

  // FAB button
  const fab = document.createElement("button");
  fab.id = "hc-chat-fab";
  fab.setAttribute("aria-label", "Open chat with HappyCake assistant");
  fab.setAttribute("aria-haspopup", "dialog");
  fab.setAttribute("aria-expanded", "false");
  fab.innerHTML = `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M20 2H4C2.9 2 2 2.9 2 4V22L6 18H20C21.1 18 22 17.1 22 16V4C22 2.9 21.1 2 20 2Z" fill="currentColor"/></svg>`;

  // Panel
  const panel = document.createElement("div");
  panel.id = "hc-chat-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "HappyCake assistant");
  panel.setAttribute("aria-modal", "false");
  panel.hidden = true;

  panel.innerHTML = `
    <div id="hc-chat-header">
      <span>HappyCake assistant</span>
      <button id="hc-chat-close" aria-label="Close chat" title="Close">&times;</button>
    </div>
    <div
      id="hc-chat-log"
      role="log"
      aria-live="polite"
      aria-label="Chat messages"
      aria-atomic="false"
    ></div>
    <form id="hc-chat-form" autocomplete="off">
      <input
        id="hc-chat-input"
        type="text"
        name="message"
        placeholder="Type a message…"
        aria-label="Your message"
        maxlength="1000"
        autocomplete="off"
      />
      <button id="hc-chat-send" type="submit" aria-label="Send">Send</button>
    </form>
  `;

  document.getElementById("chat-widget-root")!.append(fab, panel);

  // ─── Events ──────────────────────────────────────────────────────────────

  fab.addEventListener("click", togglePanel);
  fab.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); togglePanel(); }
  });

  document.getElementById("hc-chat-close")!.addEventListener("click", closePanel);

  document.getElementById("hc-chat-form")!.addEventListener("submit", (e) => {
    e.preventDefault();
    const input = document.getElementById("hc-chat-input") as HTMLInputElement;
    const text = input.value.trim();
    if (!text || isLoading) return;
    input.value = "";
    sendMessage(text);
  });
}

// ─── Panel toggle ──────────────────────────────────────────────────────────────

function togglePanel(): void {
  isOpen ? closePanel() : openPanel();
}

function openPanel(): void {
  isOpen = true;
  const panel = document.getElementById("hc-chat-panel")!;
  const fab = document.getElementById("hc-chat-fab")!;
  panel.hidden = false;
  fab.setAttribute("aria-expanded", "true");

  // Greet on first open (no prior messages)
  const log = document.getElementById("hc-chat-log")!;
  if (!log.hasChildNodes()) {
    appendMessage("assistant", "Good morning, friends. What can we help you with?");
  }

  // Focus the input
  setTimeout(() => {
    (document.getElementById("hc-chat-input") as HTMLInputElement)?.focus();
  }, 50);
}

function closePanel(): void {
  isOpen = false;
  const panel = document.getElementById("hc-chat-panel")!;
  const fab = document.getElementById("hc-chat-fab")!;
  panel.hidden = true;
  fab.setAttribute("aria-expanded", "false");
  fab.focus();
}

// ─── Messaging ────────────────────────────────────────────────────────────────

function appendMessage(
  role: "assistant" | "user" | "error",
  text: string
): void {
  const log = document.getElementById("hc-chat-log")!;
  const div = document.createElement("div");
  div.classList.add("hc-msg");
  if (role === "assistant") div.classList.add("hc-msg-assistant");
  else if (role === "user") div.classList.add("hc-msg-user");
  else div.classList.add("hc-msg-error");
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function showTyping(): HTMLDivElement {
  const log = document.getElementById("hc-chat-log")!;
  const div = document.createElement("div");
  div.classList.add("hc-typing");
  div.id = "hc-typing-indicator";
  div.textContent = "Typing…";
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

function removeTyping(): void {
  document.getElementById("hc-typing-indicator")?.remove();
}

async function sendMessage(text: string): Promise<void> {
  if (isLoading) return;
  isLoading = true;

  const sendBtn = document.getElementById("hc-chat-send") as HTMLButtonElement;
  sendBtn.disabled = true;
  appendMessage("user", text);
  const typingEl = showTyping();

  try {
    const body: Record<string, unknown> = { message: text };
    if (sessionId) body.session_id = sessionId;

    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(30000),
    });

    typingEl.remove();

    if (res.ok) {
      const data = await res.json() as { session_id: string; reply: string };
      if (data.session_id) {
        sessionId = data.session_id;
        localStorage.setItem(SESSION_KEY, sessionId);
      }
      appendMessage("assistant", data.reply);
    } else {
      // 502 or other errors — show the specified copy
      appendMessage(
        "error",
        "I couldn't reach the team's assistant just now — please try again in a moment."
      );
    }
  } catch {
    typingEl.remove();
    appendMessage(
      "error",
      "I couldn't reach the team's assistant just now — please try again in a moment."
    );
  } finally {
    isLoading = false;
    sendBtn.disabled = false;
    (document.getElementById("hc-chat-input") as HTMLInputElement)?.focus();
  }
}

// ─── Boot ─────────────────────────────────────────────────────────────────────

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", buildWidget);
} else {
  buildWidget();
}
