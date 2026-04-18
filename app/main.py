from __future__ import annotations

import html

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.api import chat_router, dev_router, memory_router, profile_router
from app.db import create_db_and_tables


CHAT_HTML = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Jeeves Chat</title>
  <style>
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      background: #0b1020;
      color: #e8ecf1;
    }
    .wrap {
      max-width: 900px;
      margin: 0 auto;
      padding: 20px;
    }
    .topbar {
      display: flex;
      gap: 10px;
      align-items: center;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }
    button {
      background: #2563eb;
      color: white;
      border: 0;
      border-radius: 10px;
      padding: 10px 14px;
      cursor: pointer;
      font-size: 14px;
    }
    button.secondary {
      background: #374151;
    }
    button.danger {
      background: #b91c1c;
    }
    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .status {
      padding: 8px 12px;
      background: #111827;
      border-radius: 10px;
      font-size: 14px;
    }
    .chat {
      background: #111827;
      border-radius: 16px;
      padding: 16px;
      min-height: 420px;
      max-height: 65vh;
      overflow-y: auto;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.06);
    }
    .msg {
      margin-bottom: 12px;
      padding: 12px 14px;
      border-radius: 14px;
      white-space: pre-wrap;
      line-height: 1.45;
    }
    .msg.user {
      background: #1d4ed8;
      margin-left: 80px;
    }
    .msg.assistant {
      background: #1f2937;
      margin-right: 80px;
    }
    .msg.system {
      background: #3f3f46;
    }
    .composer {
      margin-top: 16px;
      display: grid;
      gap: 10px;
    }
    textarea {
      width: 100%;
      min-height: 110px;
      max-height: 220px;
      resize: vertical;
      border-radius: 14px;
      border: 1px solid #374151;
      padding: 14px;
      font-size: 15px;
      color: #fff;
      background: #0f172a;
      box-sizing: border-box;
    }
    .actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    .hint {
      color: #9ca3af;
      font-size: 13px;
    }
    .gate {
      margin-top: 14px;
      padding: 12px;
      border-radius: 12px;
      background: #3b0764;
      color: #f5d0fe;
      display: none;
    }
    .small {
      font-size: 12px;
      color: #a1a1aa;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <button id="startBtn">Start chat</button>
      <button id="confirmBtn" class="secondary" disabled>Confirm</button>
      <button id="closeBtn" class="danger" disabled>Close chat</button>
      <div class="status" id="status">Нет активного чата</div>
    </div>

    <div class="chat" id="chat"></div>

    <div class="gate" id="gateBox">
      Сейчас агент ждёт review:
      либо нажми <b>Confirm</b>,
      либо отправь исправление через <b>Send correction</b>.
    </div>

    <div class="composer">
      <textarea id="input" placeholder="Напиши сообщение..."></textarea>
      <div class="actions">
        <button id="sendBtn" disabled>Send message</button>
        <button id="correctionBtn" class="secondary" disabled>Send correction</button>
      </div>
      <div class="hint">
        Обычный flow: Start chat → Send message → Confirm или Send correction.
      </div>
      <div class="small" id="meta"></div>
    </div>
  </div>

  <script>
    const chatEl = document.getElementById("chat");
    const inputEl = document.getElementById("input");
    const statusEl = document.getElementById("status");
    const metaEl = document.getElementById("meta");
    const gateBox = document.getElementById("gateBox");

    const startBtn = document.getElementById("startBtn");
    const sendBtn = document.getElementById("sendBtn");
    const correctionBtn = document.getElementById("correctionBtn");
    const confirmBtn = document.getElementById("confirmBtn");
    const closeBtn = document.getElementById("closeBtn");

    let chatId = null;
    let lastState = null;

    function addMessage(role, text) {
      const div = document.createElement("div");
      div.className = `msg ${role}`;
      div.textContent = text;
      chatEl.appendChild(div);
      chatEl.scrollTop = chatEl.scrollHeight;
    }

    function setStatus(text) {
      statusEl.textContent = text;
    }

    function syncUiFromState(state) {
      lastState = state || null;

      const hasChat = !!chatId;
      const awaitingFeedback = !!state?.awaiting_user_feedback;
      const awaitingConfirmation = !!state?.awaiting_confirmation;
      const closed = !!state?.chat_closed;

      sendBtn.disabled = !hasChat || awaitingFeedback || closed;
      correctionBtn.disabled = !hasChat || !awaitingFeedback || closed;
      confirmBtn.disabled = !hasChat || !awaitingFeedback || closed;
      closeBtn.disabled = !hasChat || closed;

      gateBox.style.display = awaitingFeedback ? "block" : "none";

      metaEl.textContent =
        hasChat
          ? `chat_id=${chatId} | awaiting_feedback=${awaitingFeedback} | awaiting_confirmation=${awaitingConfirmation} | execution_status=${state?.execution_status ?? "idle"}`
          : "";
    }

    async function api(path, payload) {
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      let data = null;
      try {
        data = await res.json();
      } catch (_) {}

      if (!res.ok) {
        const detail = data?.detail
          ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail))
          : `HTTP ${res.status}`;
        throw new Error(detail);
      }

      return data;
    }

    startBtn.onclick = async () => {
      try {
        const userId = "local-user";
        const data = await api("/chat/start", { user_id: userId });
        chatId = data.chat_id;
        chatEl.innerHTML = "";
        addMessage("system", `Чат создан: ${chatId}`);
        setStatus("Чат активен");
        syncUiFromState({
          awaiting_user_feedback: false,
          awaiting_confirmation: false,
          execution_status: "idle",
          chat_closed: false,
        });
      } catch (e) {
        addMessage("system", `Ошибка start: ${e.message}`);
      }
    };

    sendBtn.onclick = async () => {
      const text = inputEl.value.trim();
      if (!text || !chatId) return;

      try {
        addMessage("user", text);
        inputEl.value = "";

        const data = await api("/chat/message", {
          chat_id: chatId,
          user_message: text,
        });

        const state = data.state;
        for (const msg of state.assistant_messages || []) {
          addMessage("assistant", msg);
        }
        syncUiFromState(state);
      } catch (e) {
        addMessage("system", `Ошибка message: ${e.message}`);
      }
    };

    correctionBtn.onclick = async () => {
      const text = inputEl.value.trim();
      if (!text || !chatId) return;

      try {
        addMessage("user", `[correction] ${text}`);
        inputEl.value = "";

        const data = await api("/chat/correction", {
          chat_id: chatId,
          correction_message: text,
        });

        const state = data.state;
        for (const msg of state.assistant_messages || []) {
          addMessage("assistant", msg);
        }
        syncUiFromState(state);
      } catch (e) {
        addMessage("system", `Ошибка correction: ${e.message}`);
      }
    };

    confirmBtn.onclick = async () => {
      if (!chatId) return;

      try {
        const data = await api("/chat/confirm", { chat_id: chatId });
        const state = data.state;

        for (const msg of state.assistant_messages || []) {
          addMessage("assistant", msg);
        }
        syncUiFromState(state);
      } catch (e) {
        addMessage("system", `Ошибка confirm: ${e.message}`);
      }
    };

    closeBtn.onclick = async () => {
      if (!chatId) return;

      try {
        const data = await api("/chat/close", { chat_id: chatId });
        const state = data.state;
        addMessage("system", "Чат закрыт");
        syncUiFromState(state);
      } catch (e) {
        addMessage("system", `Ошибка close: ${e.message}`);
      }
    };
  </script>
</body>
</html>
"""


def create_app() -> FastAPI:
    app = FastAPI(title="Jeeves Backend", version="0.1.0")

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok"}

    app.include_router(chat_router)
    app.include_router(memory_router)
    app.include_router(profile_router)
    app.include_router(dev_router)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def root():
        return HTMLResponse(CHAT_HTML)

    @app.on_event("startup")
    def _startup():
        create_db_and_tables()

    return app


app = create_app()