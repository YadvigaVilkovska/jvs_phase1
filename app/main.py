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
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
  <title>Jeeves Chat</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #07111f;
      --panel: rgba(15, 23, 42, 0.92);
      --panel-strong: rgba(17, 24, 39, 0.96);
      --line: rgba(148, 163, 184, 0.16);
      --text: #e8ecf1;
      --muted: #9aa4b2;
      --accent-strong: #2563eb;
      --radius-xl: 24px;
      --radius-lg: 18px;
      --shadow: 0 24px 80px rgba(0, 0, 0, 0.35);
    }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", sans-serif;
      background:
        radial-gradient(circle at top, rgba(79, 140, 255, 0.22), transparent 35%),
        radial-gradient(circle at 20% 20%, rgba(167, 139, 250, 0.18), transparent 28%),
        linear-gradient(180deg, #07111f 0%, #030712 100%);
      color: var(--text);
      min-height: 100vh;
      min-height: 100dvh;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }
    .wrap {
      max-width: 760px;
      margin: 0 auto;
      padding: 10px 10px calc(10px + env(safe-area-inset-bottom));
      box-sizing: border-box;
    }
    .topbar {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 10px;
      flex-wrap: wrap;
      padding: 12px 14px;
      border-radius: var(--radius-xl);
      background: var(--panel);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
    }
    .title {
      font-size: 17px;
      font-weight: 700;
      letter-spacing: 0.2px;
    }
    .status {
      padding: 8px 12px;
      background: rgba(17, 24, 39, 0.8);
      border-radius: 999px;
      font-size: 12px;
      border: 1px solid var(--line);
      color: var(--muted);
      white-space: nowrap;
    }
    .top-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: stretch;
    }
    button {
      background: var(--accent-strong);
      color: white;
      border: 0;
      border-radius: 14px;
      padding: 13px 16px;
      cursor: pointer;
      font-size: 15px;
      font-weight: 600;
      min-height: 48px;
      box-shadow: 0 10px 24px rgba(37, 99, 235, 0.24);
    }
    button.secondary {
      background: rgba(55, 65, 81, 0.92);
      box-shadow: none;
    }
    button.danger {
      background: rgba(185, 28, 28, 0.92);
      box-shadow: none;
    }
    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .chat {
      background: var(--panel-strong);
      border-radius: var(--radius-xl);
      padding: 14px 12px;
      min-height: 66vh;
      max-height: 66vh;
      overflow-y: auto;
      box-shadow: var(--shadow);
      border: 1px solid var(--line);
      scroll-behavior: smooth;
      -webkit-overflow-scrolling: touch;
    }
    .msg {
      margin-bottom: 12px;
      padding: 14px 15px;
      border-radius: 18px;
      white-space: pre-wrap;
      line-height: 1.5;
      font-size: 15px;
      word-break: break-word;
    }
    .msg.user {
      background: linear-gradient(180deg, rgba(37, 99, 235, 0.96), rgba(29, 78, 216, 0.96));
      margin-left: 18%;
    }
    .msg.assistant {
      background: rgba(31, 41, 55, 0.96);
      margin-right: 18%;
      border: 1px solid rgba(255, 255, 255, 0.06);
    }
    .msg.system {
      background: rgba(63, 63, 70, 0.95);
      color: #f5f5f5;
    }
    .composer {
      margin-top: 10px;
      display: grid;
      gap: 8px;
      position: sticky;
      bottom: 0;
      padding-bottom: env(safe-area-inset-bottom);
    }
    textarea {
      width: 100%;
      min-height: 92px;
      max-height: 180px;
      resize: vertical;
      border-radius: var(--radius-lg);
      border: 1px solid var(--line);
      padding: 14px;
      font-size: 16px;
      color: #fff;
      background: rgba(15, 23, 42, 0.98);
      box-sizing: border-box;
      box-shadow: var(--shadow);
      -webkit-appearance: none;
    }
    .actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    @media (max-width: 640px) {
      .wrap {
        padding: 8px 8px calc(8px + env(safe-area-inset-bottom));
      }
      .topbar {
        width: 100%;
      }
      .top-actions button {
        flex: 1 1 calc(50% - 5px);
      }
      .chat {
        min-height: 67vh;
        max-height: 67vh;
        padding: 12px 10px;
      }
      .msg.user {
        margin-left: 10%;
      }
      .msg.assistant {
        margin-right: 10%;
      }
      textarea {
        min-height: 88px;
      }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <div class="title">Jeeves</div>
      <div class="status" id="status">Нет активного чата</div>
    </div>

    <div class="chat" id="chat"></div>

    <div class="composer">
      <textarea id="input" placeholder="Напиши сообщение..."></textarea>
      <div class="status" id="meta">Обычный flow: напиши в чат (сервер сам поймёт confirm/correction/новая задача)</div>
    </div>
  </div>

  <script>
    const chatEl = document.getElementById("chat");
    const inputEl = document.getElementById("input");
    const statusEl = document.getElementById("status");
    const metaEl = document.getElementById("meta");

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

      metaEl.textContent =
        hasChat
          ? `chat_id=${chatId} · awaiting_feedback=${awaitingFeedback} · awaiting_confirmation=${awaitingConfirmation} · execution_status=${state?.execution_status ?? "idle"}`
          : "Обычный flow: напиши в чат";
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

    async function sendText(text) {
      const msg = (text || "").trim();
      if (!msg) return;
      const id = chatId; // may be null before first /turn

      try {
        addMessage("user", msg);

        const data = await api("/chat/turn", {
          chat_id: id,
          user_id: "local-user",
          user_message: msg,
        });

        chatId = data.chat_id;
        if (chatEl.innerHTML === "" && chatId) {
          addMessage("system", `Чат создан: ${chatId}`);
        }
        const state = data.state;
        for (const msg of state.assistant_messages || []) {
          addMessage("assistant", msg);
        }
        syncUiFromState(state);
      } catch (e) {
        addMessage("system", `Ошибка message: ${e.message}`);
      }
    }

    inputEl.addEventListener("keydown", async (e) => {
      if (e.key !== "Enter") return;
      if (e.shiftKey) return;
      e.preventDefault();
      const text = inputEl.value;
      inputEl.value = "";
      await sendText(text);
    });
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
