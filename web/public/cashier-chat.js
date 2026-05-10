/**
 * HappyCake cashier hero chat — homepage storefront.
 *
 * Plain vanilla JS so it works without a bundler at runtime. Reads the
 * API base URL from a hidden config element in the DOM
 * (`#cashier-chat-config[data-api-base]`) which the Astro component emits
 * at build time from `import.meta.env.PUBLIC_API_BASE ?? ""`. This keeps
 * the same effect as the previous `define:vars` pattern without depending
 * on Astro's bundler.
 *
 * Persists conversation history under `hc_cashier_history` (capped at 24
 * turns) and the session id under `hc_cashier_session_id`. Reads cart
 * context from `hc_cart`. Sends `ngrok-skip-browser-warning: true` on
 * every fetch so the dev tunnel doesn't gate the request.
 */
(function () {
  "use strict";

  var configEl = document.getElementById("cashier-chat-config");
  var apiBase = (configEl && configEl.dataset && configEl.dataset.apiBase) || "";

  const STORAGE_KEY = "hc_cashier_session_id";
  const HISTORY_KEY = "hc_cashier_history";
  const HISTORY_MAX = 24;
  const CART_KEY = "hc_cart";
  let sessionId = localStorage.getItem(STORAGE_KEY);
  let pending = false;

  function readHistory() {
    try {
      var raw = localStorage.getItem(HISTORY_KEY);
      if (!raw) return [];
      var arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr.slice(-HISTORY_MAX) : [];
    } catch (e) {
      return [];
    }
  }
  function writeHistory(history) {
    try {
      localStorage.setItem(
        HISTORY_KEY,
        JSON.stringify(history.slice(-HISTORY_MAX))
      );
    } catch (e) { /* quota / disabled — ignore */ }
  }
  function readCartContext() {
    try {
      var raw = localStorage.getItem(CART_KEY);
      var cart = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(cart) || cart.length === 0) return null;
      return cart.map(function (line) {
        return {
          slug: line.slug,
          name: line.name,
          quantity: line.quantity,
          price: line.price,
        };
      });
    } catch (e) {
      return null;
    }
  }

  const transcript = document.getElementById("cashier-transcript");
  const form = document.getElementById("cashier-form");
  const input = document.getElementById("cashier-input");
  const send = document.getElementById("cashier-send");
  const chips = document.getElementById("cashier-chips");
  const figure = document.getElementById("cashier-figure");
  const caption = document.getElementById("cashier-caption");

  if (!transcript || !form || !input || !send || !chips) return;

  const CAPTIONS = {
    idle: "listening",
    thinking: "checking the counter",
    serving: "ringing it up",
    apologizing: "let me check",
  };

  function setState(state) {
    if (figure) figure.dataset.state = state;
    if (caption) caption.textContent = CAPTIONS[state] || "listening";
  }

  function pickState(reply) {
    var lower = (reply || "").toLowerCase();
    if (/sorry|apolog|can'?t|couldn'?t|let me check/.test(lower)) return "apologizing";
    if (/yes|ready|on the counter|we have|today|order|confirm/.test(lower)) return "serving";
    return "idle";
  }

  var CLOSING_RE = /\s*(?:[—-]\s*)?Order on the site at happycake\.us[^\n]*$/i;
  var SIGN_RE = /\s*[—-]\s*the HappyCake team\s*$/i;

  function cleanReply(text) {
    // The cashier is literally on the site — strip the closing pattern
    // and the team-sign-off so chat replies don't read like marketing posts.
    var t = String(text || "").trim();
    t = t.replace(CLOSING_RE, "").trim();
    t = t.replace(SIGN_RE, "").trim();
    return t;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function renderMarkdown(text) {
    // Tiny, conservative md → html. Supports: bullets (- / *), bold,
    // italic, inline code, paragraph breaks. Anything else stays text.
    var lines = String(text).split(/\r?\n/);
    var out = [];
    var inList = false;
    var paragraph = [];

    function flushParagraph() {
      if (paragraph.length === 0) return;
      var html = paragraph.join(" ").trim();
      if (html) out.push("<p>" + inlineMd(html) + "</p>");
      paragraph = [];
    }
    function closeList() {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
    }
    function inlineMd(s) {
      s = escapeHtml(s);
      // **bold** → <strong>
      s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
      // *italic* / _italic_  (only when surrounded by word boundaries)
      s = s.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,!?]|$)/g, "$1<em>$2</em>");
      s = s.replace(/(^|[\s(])_([^_\n]+)_(?=[\s).,!?]|$)/g, "$1<em>$2</em>");
      // `code`
      s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>");
      return s;
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      if (line === "") {
        flushParagraph();
        closeList();
        continue;
      }
      var bulletMatch = line.match(/^[-*•]\s+(.*)$/);
      if (bulletMatch) {
        flushParagraph();
        if (!inList) {
          out.push("<ul>");
          inList = true;
        }
        out.push("<li>" + inlineMd(bulletMatch[1]) + "</li>");
        continue;
      }
      if (inList) closeList();
      paragraph.push(line);
    }
    flushParagraph();
    closeList();
    if (out.length === 0) out.push("<p>" + inlineMd(escapeHtml(text)) + "</p>");
    return out.join("");
  }

  function appendMessage(text, role) {
    var row = document.createElement("div");
    row.className = "cashier-row cashier-row--" + role;

    var wrap = document.createElement("div");
    wrap.className = "cashier-bubble-wrap";

    var label = document.createElement("div");
    label.className = "cashier-bubble-label";
    label.textContent = role === "user"
      ? "you →"
      : role === "assistant" ? "← cashier" : role;

    var bubble = document.createElement("div");
    bubble.className = "cashier-bubble";

    if (role === "assistant") {
      bubble.innerHTML = renderMarkdown(cleanReply(text));
    } else {
      bubble.textContent = text;
    }

    wrap.appendChild(label);
    wrap.appendChild(bubble);
    row.appendChild(wrap);
    transcript.appendChild(row);
    transcript.classList.add("has-messages");
    transcript.scrollTop = transcript.scrollHeight;
    return row;
  }

  async function sendMessage(message) {
    if (!message || pending) return;
    pending = true;
    send.disabled = true;
    input.value = "";
    setState("thinking");

    appendMessage(message, "user");
    const typing = appendMessage("checking the counter", "typing");

    try {
      var body = { session_id: sessionId, message: message };
      var cart = readCartContext();
      if (cart) body.context = { cart: cart };
      const res = await fetch(apiBase + "/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "ngrok-skip-browser-warning": "true",
        },
        body: JSON.stringify(body),
      });
      typing.remove();

      if (!res.ok) {
        setState("apologizing");
        appendMessage(
          "I couldn't reach the team's assistant just now — please try again in a moment.",
          "error"
        );
        return;
      }

      const data = await res.json();
      if (data.session_id && data.session_id !== sessionId) {
        sessionId = data.session_id;
        localStorage.setItem(STORAGE_KEY, sessionId);
      }
      const reply = data.reply || "(no response)";
      setState(pickState(reply));
      appendMessage(reply, "assistant");
      // Persist this exchange so a page navigation doesn't lose context.
      var history = readHistory();
      history.push({ role: "user", text: message });
      history.push({ role: "assistant", text: reply });
      writeHistory(history);
    } catch (err) {
      typing.remove();
      setState("apologizing");
      appendMessage(
        "Couldn't reach the cashier — please try again.",
        "error"
      );
    } finally {
      pending = false;
      send.disabled = false;
      input.focus();
      // Settle back to idle a few seconds after a successful turn so the
      // next visitor doesn't see a stale serving/apologizing state.
      setTimeout(function () {
        if (!pending && figure && figure.dataset.state !== "idle") {
          setState("idle");
        }
      }, 6000);
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const message = (input.value || "").trim();
    sendMessage(message);
  });

  // Replay prior history on page load so navigating to /menu and back
  // doesn't drop the conversation. Skip the typing/error variants —
  // we only persist real user/assistant turns.
  (function replayHistory() {
    var history = readHistory();
    if (history.length === 0) return;
    history.forEach(function (turn) {
      if (turn && (turn.role === "user" || turn.role === "assistant")) {
        appendMessage(turn.text || "", turn.role);
      }
    });
  })();

  chips.addEventListener("click", function (event) {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const prompt = target.dataset.prompt;
    if (!prompt) return;
    sendMessage(prompt);
  });
})();
