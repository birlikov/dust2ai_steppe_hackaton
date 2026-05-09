/**
 * HappyCake on-site chat widget.
 * Covers w3 (on-site assistant).
 *
 * Plain vanilla JS so it works without a bundler at runtime.
 * Reads API_BASE from the data-api attribute on the script tag, or falls
 * back to "" (relative URLs, same origin as the page). When FastAPI serves
 * the storefront on the same port, this just works.
 */
(function () {
  "use strict";

  var API_BASE = (function () {
    // currentScript is null with defer; use the data-api attribute from the
    // script element's id or look up the script by src.
    var scripts = document.querySelectorAll('script[src*="chat-widget"]');
    var s = scripts[scripts.length - 1];
    return (s && s.dataset && s.dataset.api) || "";
  })();

  var SESSION_KEY = "hc_chat_session_id";
  var sessionId = localStorage.getItem(SESSION_KEY);
  var isOpen = false;
  var isLoading = false;

  function buildWidget() {
    // Styles
    var style = document.createElement("style");
    style.textContent = [
      "#hc-chat-fab{position:fixed;bottom:24px;right:24px;z-index:9999;background:#1B4868;color:#FBF6E8;border:none;width:56px;height:56px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:22px;transition:background 0.15s;}",
      "#hc-chat-fab:hover,#hc-chat-fab:focus{background:#0E2A3C;outline:2px solid #3B7BA8;outline-offset:2px;}",
      "#hc-chat-panel{position:fixed;bottom:92px;right:24px;z-index:9998;width:340px;max-width:calc(100vw - 48px);background:#FBF6E8;border:0.5px solid rgba(14,42,60,0.25);display:flex;flex-direction:column;max-height:480px;box-shadow:0 4px 16px rgba(14,42,60,0.15);}",
      "#hc-chat-panel[hidden]{display:none;}",
      "#hc-chat-header{background:#0E2A3C;color:#FBF6E8;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;font-family:Inter,system-ui,sans-serif;font-size:13px;font-weight:500;}",
      "#hc-chat-close{background:none;border:none;color:#BFD8E8;cursor:pointer;font-size:18px;padding:0 4px;line-height:1;}",
      "#hc-chat-close:hover,#hc-chat-close:focus{color:#FBF6E8;outline:1px solid #3B7BA8;}",
      "#hc-chat-log{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px;font-family:Inter,system-ui,sans-serif;font-size:13px;line-height:1.5;}",
      ".hc-msg{max-width:85%;padding:8px 12px;border:0.5px solid rgba(14,42,60,0.15);}",
      ".hc-msg-assistant{background:#F4ECD3;color:#1A1816;align-self:flex-start;}",
      ".hc-msg-user{background:#1B4868;color:#FBF6E8;align-self:flex-end;}",
      ".hc-msg-error{background:#F4ECD3;color:#1A1816;border-color:#E08066;align-self:flex-start;font-style:italic;}",
      ".hc-typing{background:#F4ECD3;color:#3B7BA8;align-self:flex-start;padding:8px 12px;font-style:italic;font-size:12px;border:0.5px solid rgba(14,42,60,0.15);}",
      "#hc-chat-form{display:flex;border-top:0.5px solid rgba(14,42,60,0.15);}",
      "#hc-chat-input{flex:1;border:none;padding:10px 12px;font-family:Inter,system-ui,sans-serif;font-size:13px;background:#FBF6E8;color:#1A1816;outline:none;}",
      "#hc-chat-input:focus{box-shadow:inset 0 0 0 2px #3B7BA8;}",
      "#hc-chat-send{background:#1B4868;color:#FBF6E8;border:none;padding:10px 16px;cursor:pointer;font-size:13px;font-family:Inter,system-ui,sans-serif;}",
      "#hc-chat-send:hover,#hc-chat-send:focus{background:#0E2A3C;outline:2px solid #3B7BA8;}",
      "#hc-chat-send:disabled{opacity:0.5;cursor:not-allowed;}"
    ].join("\n");
    document.head.appendChild(style);

    // FAB
    var fab = document.createElement("button");
    fab.id = "hc-chat-fab";
    fab.setAttribute("aria-label", "Open chat with HappyCake assistant");
    fab.setAttribute("aria-haspopup", "dialog");
    fab.setAttribute("aria-expanded", "false");
    fab.innerHTML =
      '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
      '<path d="M20 2H4C2.9 2 2 2.9 2 4V22L6 18H20C21.1 18 22 17.1 22 16V4C22 2.9 21.1 2 20 2Z" fill="currentColor"/>' +
      "</svg>";

    // Panel
    var panel = document.createElement("div");
    panel.id = "hc-chat-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "HappyCake assistant");
    panel.hidden = true;
    panel.innerHTML =
      '<div id="hc-chat-header">' +
        '<span>HappyCake assistant</span>' +
        '<button id="hc-chat-close" aria-label="Close chat">&times;</button>' +
      "</div>" +
      '<div id="hc-chat-log" role="log" aria-live="polite" aria-atomic="false" aria-label="Chat messages"></div>' +
      '<form id="hc-chat-form" autocomplete="off">' +
        '<input id="hc-chat-input" type="text" name="message" placeholder="Type a message…" aria-label="Your message" maxlength="1000" autocomplete="off"/>' +
        '<button id="hc-chat-send" type="submit" aria-label="Send">Send</button>' +
      "</form>";

    var root = document.getElementById("chat-widget-root") || document.body;
    root.appendChild(fab);
    root.appendChild(panel);

    // Events
    fab.addEventListener("click", togglePanel);
    document.getElementById("hc-chat-close").addEventListener("click", closePanel);
    document.getElementById("hc-chat-form").addEventListener("submit", function (e) {
      e.preventDefault();
      var input = document.getElementById("hc-chat-input");
      var text = input.value.trim();
      if (!text || isLoading) return;
      input.value = "";
      sendMessage(text);
    });
  }

  function togglePanel() {
    isOpen ? closePanel() : openPanel();
  }

  function openPanel() {
    isOpen = true;
    var panel = document.getElementById("hc-chat-panel");
    var fab = document.getElementById("hc-chat-fab");
    panel.hidden = false;
    fab.setAttribute("aria-expanded", "true");

    var log = document.getElementById("hc-chat-log");
    if (!log.hasChildNodes()) {
      appendMessage("assistant", "Good morning, friends. What can we help you with?");
    }
    setTimeout(function () {
      var input = document.getElementById("hc-chat-input");
      if (input) input.focus();
    }, 50);
  }

  function closePanel() {
    isOpen = false;
    var panel = document.getElementById("hc-chat-panel");
    var fab = document.getElementById("hc-chat-fab");
    panel.hidden = true;
    fab.setAttribute("aria-expanded", "false");
    fab.focus();
  }

  function appendMessage(role, text) {
    var log = document.getElementById("hc-chat-log");
    var div = document.createElement("div");
    div.classList.add("hc-msg");
    if (role === "assistant") div.classList.add("hc-msg-assistant");
    else if (role === "user") div.classList.add("hc-msg-user");
    else div.classList.add("hc-msg-error");
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  function showTyping() {
    var log = document.getElementById("hc-chat-log");
    var div = document.createElement("div");
    div.classList.add("hc-typing");
    div.id = "hc-typing-indicator";
    div.textContent = "Typing…";
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  function removeTyping() {
    var el = document.getElementById("hc-typing-indicator");
    if (el) el.remove();
  }

  function sendMessage(text) {
    if (isLoading) return;
    isLoading = true;

    var sendBtn = document.getElementById("hc-chat-send");
    sendBtn.disabled = true;
    appendMessage("user", text);
    showTyping();

    var body = { message: text };
    if (sessionId) body.session_id = sessionId;

    fetch(API_BASE + "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (res) {
        removeTyping();
        if (res.ok) {
          return res.json().then(function (data) {
            if (data.session_id) {
              sessionId = data.session_id;
              localStorage.setItem(SESSION_KEY, sessionId);
            }
            appendMessage("assistant", data.reply);
          });
        } else {
          appendMessage(
            "error",
            "I couldn’t reach the team’s assistant just now — please try again in a moment."
          );
        }
      })
      .catch(function () {
        removeTyping();
        appendMessage(
          "error",
          "I couldn’t reach the team’s assistant just now — please try again in a moment."
        );
      })
      .finally(function () {
        isLoading = false;
        sendBtn.disabled = false;
        var input = document.getElementById("hc-chat-input");
        if (input) input.focus();
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", buildWidget);
  } else {
    buildWidget();
  }
})();
