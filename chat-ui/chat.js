/*
 * mgr4smb chat UI — self-contained vanilla JS.
 *
 * Talks to the FastAPI backend at API_BASE.
 * Stores JWT + API base in localStorage when "remember" is checked.
 * Manages a session_id in memory so turns share conversation history.
 */

(() => {
  "use strict";

  // ---------------------------------------------------------------------------
  // DOM refs
  // ---------------------------------------------------------------------------
  const $ = (sel) => document.querySelector(sel);

  const dom = {
    healthDot:   $("#health-dot"),
    healthText:  $("#health-text"),
    settingsBtn: $("#settings-toggle"),
    settings:    $("#settings"),
    apiBase:     $("#api-base"),
    token:       $("#jwt-token"),
    remember:    $("#remember-token"),
    saveBtn:     $("#save-settings"),
    clearBtn:    $("#clear-settings"),
    sessionId:   $("#session-id"),
    newSession:  $("#new-session"),
    chat:        $("#chat"),
    errorBanner: $("#error-banner"),
    form:        $("#composer"),
    input:       $("#input"),
    sendBtn:     $("#send-btn"),
  };

  // ---------------------------------------------------------------------------
  // State (in-memory + localStorage)
  // ---------------------------------------------------------------------------
  const LS_KEYS = { token: "mgr4smb.token", base: "mgr4smb.apiBase", remember: "mgr4smb.remember" };

  function defaultApiBase() {
    // If we are served from the API itself, use window.location.origin.
    // Otherwise, fall back to http://localhost:8000 for file:// or dev use.
    if (window.location.protocol === "http:" || window.location.protocol === "https:") {
      return window.location.origin;
    }
    return "http://localhost:8000";
  }

  const state = {
    apiBase: localStorage.getItem(LS_KEYS.base) || defaultApiBase(),
    token:   localStorage.getItem(LS_KEYS.token) || "",
    remember: (localStorage.getItem(LS_KEYS.remember) ?? "true") === "true",
    sessionId: null,
    sending: false,
  };

  // ---------------------------------------------------------------------------
  // UI helpers
  // ---------------------------------------------------------------------------
  function renderSettings() {
    dom.apiBase.value = state.apiBase;
    dom.token.value = state.token;
    dom.remember.checked = state.remember;
  }

  function renderSession() {
    dom.sessionId.textContent = state.sessionId || "none";
  }

  function showError(msg) {
    if (!msg) {
      dom.errorBanner.hidden = true;
      dom.errorBanner.textContent = "";
      return;
    }
    dom.errorBanner.hidden = false;
    dom.errorBanner.textContent = msg;
  }

  function addMessage(role, text) {
    const div = document.createElement("div");
    div.className = "msg " + (role === "user" ? "msg-user" : role === "system" ? "msg-system" : "msg-bot");
    div.textContent = text;
    dom.chat.appendChild(div);
    dom.chat.scrollTop = dom.chat.scrollHeight;
    return div;
  }

  function addTypingIndicator() {
    const div = document.createElement("div");
    div.className = "msg-typing";
    div.id = "typing";
    div.innerHTML = "<span></span><span></span><span></span>";
    dom.chat.appendChild(div);
    dom.chat.scrollTop = dom.chat.scrollHeight;
    return div;
  }

  function removeTypingIndicator() {
    const t = $("#typing");
    if (t) t.remove();
  }

  function persistOrClear() {
    if (state.remember) {
      localStorage.setItem(LS_KEYS.token, state.token);
      localStorage.setItem(LS_KEYS.base, state.apiBase);
      localStorage.setItem(LS_KEYS.remember, "true");
    } else {
      localStorage.removeItem(LS_KEYS.token);
      localStorage.setItem(LS_KEYS.remember, "false");
    }
  }

  // ---------------------------------------------------------------------------
  // API calls
  // ---------------------------------------------------------------------------
  async function checkHealth() {
    try {
      const r = await fetch(state.apiBase + "/health", { method: "GET" });
      if (!r.ok && r.status !== 503) throw new Error("HTTP " + r.status);
      const body = await r.json();
      const ok = body.status === "ok";
      dom.healthDot.classList.remove("ok", "warn", "err");
      dom.healthDot.classList.add(ok ? "ok" : "warn");
      const checks = body.checks || {};
      const parts = Object.entries(checks).map(([k, v]) => `${k}:${v === "ok" ? "ok" : "err"}`);
      dom.healthText.textContent = `${body.status}${parts.length ? " · " + parts.join(" · ") : ""}`;
    } catch (e) {
      dom.healthDot.classList.remove("ok", "warn");
      dom.healthDot.classList.add("err");
      dom.healthText.textContent = "unreachable";
    }
  }

  async function sendMessage(text) {
    if (!state.token) {
      showError("Set a JWT token in Settings before sending.");
      return;
    }
    showError("");
    addMessage("user", text);
    state.sending = true;
    dom.sendBtn.disabled = true;
    addTypingIndicator();

    const body = { message: text };
    if (state.sessionId) body.session_id = state.sessionId;

    let resp;
    try {
      resp = await fetch(state.apiBase + "/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + state.token,
        },
        body: JSON.stringify(body),
      });
    } catch (e) {
      removeTypingIndicator();
      showError("Network error: " + e.message);
      state.sending = false;
      dom.sendBtn.disabled = false;
      return;
    }

    removeTypingIndicator();

    if (resp.status === 401) {
      showError("401 Unauthorized — your JWT is invalid, expired, or the client has been disabled.");
      state.sending = false;
      dom.sendBtn.disabled = false;
      return;
    }

    if (!resp.ok) {
      let detail = "";
      try { detail = " — " + JSON.stringify(await resp.json()); } catch (_) {}
      showError(`HTTP ${resp.status}${detail}`);
      state.sending = false;
      dom.sendBtn.disabled = false;
      return;
    }

    const data = await resp.json();
    state.sessionId = data.session_id;
    renderSession();
    addMessage("bot", data.response || "(no response)");
    state.sending = false;
    dom.sendBtn.disabled = false;
    dom.input.focus();
  }

  // ---------------------------------------------------------------------------
  // Event wiring
  // ---------------------------------------------------------------------------
  dom.settingsBtn.addEventListener("click", () => {
    dom.settings.hidden = !dom.settings.hidden;
  });

  dom.saveBtn.addEventListener("click", (e) => {
    e.preventDefault();
    state.apiBase = dom.apiBase.value.trim().replace(/\/+$/, "") || defaultApiBase();
    state.token = dom.token.value.trim();
    state.remember = dom.remember.checked;
    persistOrClear();
    renderSettings();
    dom.settings.hidden = true;
    checkHealth();
    showError("");
  });

  dom.clearBtn.addEventListener("click", (e) => {
    e.preventDefault();
    state.token = "";
    dom.token.value = "";
    localStorage.removeItem(LS_KEYS.token);
  });

  dom.newSession.addEventListener("click", () => {
    state.sessionId = null;
    renderSession();
    // Clear chat but keep the welcome hint
    dom.chat.innerHTML = "";
    addMessage("system", "New session started.");
  });

  dom.input.addEventListener("keydown", (e) => {
    // Enter = send, Shift+Enter = newline
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      dom.form.requestSubmit();
    }
  });

  dom.form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (state.sending) return;
    const text = dom.input.value.trim();
    if (!text) return;
    dom.input.value = "";
    sendMessage(text);
  });

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------
  renderSettings();
  renderSession();
  checkHealth();
  setInterval(checkHealth, 30000);  // every 30s

  if (!state.token) {
    dom.settings.hidden = false;
    addMessage("system", "No JWT token set — open Settings above and paste one from ./menu.sh (option 6).");
  }
})();
