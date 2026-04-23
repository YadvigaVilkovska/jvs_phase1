from __future__ import annotations

from textwrap import dedent


CHAT_HTML = dedent(
    """
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
        .topbar, .ui-state, .composer, .chat {
          border: 1px solid var(--line);
          box-shadow: var(--shadow);
          background: var(--panel);
          border-radius: var(--radius-xl);
        }
        .topbar {
          display: flex;
          gap: 10px;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 10px;
          flex-wrap: wrap;
          padding: 12px 14px;
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
        .top-actions, .actions {
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
          padding: 14px 12px;
          min-height: 66vh;
          max-height: 66vh;
          overflow-y: auto;
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
        .ui-state, .composer {
          margin-top: 10px;
          padding: 14px;
        }
        .ui-state {
          border: 1px solid rgba(59, 130, 246, 0.24);
          background: rgba(15, 23, 42, 0.88);
          display: grid;
          gap: 10px;
        }
        .ui-state-title {
          font-size: 14px;
          font-weight: 700;
          letter-spacing: 0.2px;
          color: #c7d2fe;
        }
        .ui-state-question {
          color: var(--text);
          line-height: 1.45;
          white-space: pre-wrap;
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
        .composer {
          display: grid;
          gap: 8px;
          position: sticky;
          bottom: 0;
          padding-bottom: env(safe-area-inset-bottom);
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
          <div class="top-actions">
            <button id="startBtn">Start chat</button>
            <button id="confirmBtn" class="secondary" disabled>Confirm</button>
            <button id="closeBtn" class="danger" disabled>Close chat</button>
          </div>
        </div>

        <div class="chat" id="chat"></div>

        <div class="ui-state" id="uiState" hidden>
          <div class="ui-state-title" id="uiStateTitle"></div>
          <div class="ui-state-question" id="uiStateQuestion"></div>
          <textarea id="reviewInput" placeholder=""></textarea>
          <div class="actions">
            <button id="reviewBtn" class="secondary">OK</button>
          </div>
        </div>

        <div class="composer">
          <textarea id="input" placeholder="Напиши сообщение..."></textarea>
          <div class="actions">
            <button id="sendBtn" disabled>Send message</button>
            <button id="correctionBtn" class="secondary" disabled>Send correction</button>
          </div>
          <div class="status" id="meta">Обычный flow: Start → Message → Confirm / Correction</div>
        </div>
      </div>

      <script>
        const chatEl = document.getElementById("chat");
        const uiStateEl = document.getElementById("uiState");
        const uiStateTitleEl = document.getElementById("uiStateTitle");
        const uiStateQuestionEl = document.getElementById("uiStateQuestion");
        const reviewInputEl = document.getElementById("reviewInput");
        const reviewBtn = document.getElementById("reviewBtn");
        const inputEl = document.getElementById("input");
        const statusEl = document.getElementById("status");
        const metaEl = document.getElementById("meta");
        const startBtn = document.getElementById("startBtn");
        const sendBtn = document.getElementById("sendBtn");
        const correctionBtn = document.getElementById("correctionBtn");
        const confirmBtn = document.getElementById("confirmBtn");
        const closeBtn = document.getElementById("closeBtn");

        let chatId = null;
        let lastState = null;
        let lastUiState = null;
        let lastReviewText = "";

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

        function requireUiState(data) {
          if (!data || !data.ui_state) {
            throw new Error("ui_state is required");
          }
          return data.ui_state;
        }

        function syncUiFromState(state, uiState) {
          if (!uiState) {
            throw new Error("ui_state is required");
          }

          lastState = state || null;
          lastUiState = uiState;

          const hasChat = !!chatId;
          const mode = lastUiState.mode;
          if (!mode) {
            throw new Error("ui_state.mode is required");
          }
          const awaitingFeedback = mode === "understanding_review" || mode === "clarification";
          const awaitingConfirmation = !!state?.awaiting_confirmation;
          const closed = !!state?.chat_closed;
          const clarificationQuestion = lastUiState?.clarification?.question || "";
          const understandingText = lastUiState?.understanding?.text || "";

          uiStateEl.hidden = mode === "chat";
          uiStateTitleEl.textContent =
            mode === "understanding_review"
              ? "Понимание запроса"
              : mode === "clarification"
                ? "Уточнение"
                : "";
          uiStateQuestionEl.textContent =
            mode === "understanding_review"
              ? "Отредактируйте понимание и нажмите OK."
              : mode === "clarification"
                ? clarificationQuestion
                : "";

          reviewInputEl.hidden = mode !== "understanding_review";
          reviewBtn.hidden = true;
          if (mode === "understanding_review") {
            reviewInputEl.value = understandingText;
            lastReviewText = understandingText;
          }

          inputEl.disabled = !hasChat || closed || mode === "understanding_review";
          inputEl.placeholder =
            mode === "clarification"
              ? clarificationQuestion || "Ответьте на уточняющий вопрос..."
              : mode === "understanding_review"
                ? "Редактирование понимания..."
                : "Напиши сообщение...";

          sendBtn.disabled = !hasChat || closed;
          correctionBtn.disabled = !hasChat || !awaitingFeedback || closed;
          confirmBtn.disabled = !hasChat || !awaitingFeedback || closed;
          closeBtn.disabled = !hasChat || closed;
          correctionBtn.hidden = mode === "clarification";
          confirmBtn.hidden = mode === "clarification";
          sendBtn.textContent =
            mode === "understanding_review" ? "OK" : mode === "clarification" ? "Send answer" : "Send message";

          metaEl.textContent =
            hasChat
              ? `chat_id=${chatId} · ui_mode=${mode} · awaiting_feedback=${awaitingFeedback} · awaiting_confirmation=${awaitingConfirmation} · execution_status=${state?.execution_status ?? "idle"}`
              : "Обычный flow: Start → Message → Confirm / Correction";
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
            }, {
              mode: "chat",
              message_input_enabled: true,
              understanding: { visible: false, text: null, editable: false, submit_label: null },
              clarification: { visible: false, question: null },
            });
          } catch (e) {
            addMessage("system", `Ошибка start: ${e.message}`);
          }
        };

        sendBtn.onclick = async () => {
          if (!chatId) return;

          if (lastUiState?.mode === "understanding_review") {
            const current = reviewInputEl.value.trim();
            const baseline = lastReviewText.trim();
            try {
              if (!current) {
                const data = await api("/chat/reject", { chat_id: chatId });
                const state = data.state;
                for (const msg of state.assistant_messages || []) {
                  addMessage("assistant", msg);
                }
                syncUiFromState(state, requireUiState(data));
                return;
              }
              if (current === baseline) {
                const data = await api("/chat/confirm", { chat_id: chatId });
                const state = data.state;
                for (const msg of state.assistant_messages || []) {
                  addMessage("assistant", msg);
                }
                syncUiFromState(state, requireUiState(data));
                return;
              }

              addMessage("user", current);
              const data = await api("/chat/correction", {
                chat_id: chatId,
                correction_message: current,
              });
              const state = data.state;
              for (const msg of state.assistant_messages || []) {
                addMessage("assistant", msg);
              }
              syncUiFromState(state, requireUiState(data));
              return;
            } catch (e) {
              addMessage("system", `Ошибка review: ${e.message}`);
              return;
            }
          }

          const text = inputEl.value.trim();
          if (!text) return;

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
            syncUiFromState(state, requireUiState(data));
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
            syncUiFromState(state, requireUiState(data));
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
            syncUiFromState(state, requireUiState(data));
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
            syncUiFromState(state, requireUiState(data));
          } catch (e) {
            addMessage("system", `Ошибка close: ${e.message}`);
          }
        };

        reviewBtn.onclick = async () => {
          if (!chatId) return;
          const current = reviewInputEl.value.trim();
          if (!current) {
            try {
              const data = await api("/chat/reject", { chat_id: chatId });
              const state = data.state;
              for (const msg of state.assistant_messages || []) {
                addMessage("assistant", msg);
              }
              syncUiFromState(state, requireUiState(data));
              return;
            } catch (e) {
              addMessage("system", `Ошибка review: ${e.message}`);
              return;
            }
          }

          const baseline = lastReviewText.trim();
          try {
            if (current === baseline) {
              const data = await api("/chat/confirm", { chat_id: chatId });
              const state = data.state;
              for (const msg of state.assistant_messages || []) {
                addMessage("assistant", msg);
              }
              syncUiFromState(state, requireUiState(data));
              return;
            }

            const data = await api("/chat/correction", {
              chat_id: chatId,
              correction_message: current,
            });
            const state = data.state;
            for (const msg of state.assistant_messages || []) {
              addMessage("assistant", msg);
            }
            syncUiFromState(state, requireUiState(data));
          } catch (e) {
            addMessage("system", `Ошибка review: ${e.message}`);
          }
        };
      </script>
    </body>
    </html>
    """
).strip()
