# Jeeves (backend)

Jeeves is a **chat-first agent** with:

- **NormalizedUserRequest** (LLM-first normalization; understanding flow — `docs/UNDERSTANDING_FLOW.md`)
- **correction loop** (new revision of the same request object)
- **ExecutionDecision** (only after review/confirmation)
- **layered memory** (chat memory vs long-term memory vs core profile)
- **LangGraph orchestration**

This repository implements the **backend** (FastAPI + LangGraph + SQLModel). A minimal **HTML chat** is served at `GET /`; optional **Streamlit UI** lives under `ui/`.

### Key non-negotiables enforced

- **No `ExecutionDecision` before NormalizedUserRequest review/confirmation**
- **Corrections create a new `revision` of the same `NormalizedUserRequest`**
- **No deep memory writes without candidate + user review**
- **Chat memory / long-term memory / core profile are separate layers**

### Setup

- Python: **3.11+**

Install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
```

Environment:

- Copy `.env.example` to `.env` or rely on code defaults (SQLite at `sqlite:///./data/jeeves.db`).
- Invalid `DATABASE_URL` values fail at startup with a short explanation (unsupported `schema=` query params are rejected; use plain SQLite or a normal Postgres URL).

### Try locally (minimal)

1. Complete **Setup** above (venv + `pip install -e ".[dev]"`).
2. **Run API** (creates `./data/` for SQLite if needed):

   ```bash
   export DATABASE_URL="${DATABASE_URL:-sqlite:///./data/jeeves.db}"
   export JEEVES_DEV_STUB_AGENTS=true
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

   `JEEVES_DEV_STUB_AGENTS=true` enables `/dev/demo-flow` and the same in-process stub agents as tests — **no API keys** required for that path. For real LLM calls, set `JEEVES_DEV_STUB_AGENTS=false` and configure at least one provider below (see **LLM providers & fallback**).

3. **Exercise**: open `http://127.0.0.1:8000/` (simple chat UI) or `http://127.0.0.1:8000/docs`, or:

   ```bash
   BASE=http://127.0.0.1:8000 bash scripts/smoke_test.sh
   ```

   (`make smoke` runs the same script; needs `curl` and `jq`.)

If you use a `.env` instead of exports, set `DATABASE_URL` and `JEEVES_DEV_STUB_AGENTS` there, then `uvicorn app.main:app --reload`.

### Local chat UI (Streamlit)

Chat in a browser without Swagger — the UI only calls the existing HTTP API (`httpx`), same review/confirm rules as `/docs`.

1. Install UI extra: `pip install -e ".[ui]"`.
2. Start the **backend** (as above).
3. Start the **UI**:

   ```bash
   export JEEVES_API_BASE=http://127.0.0.1:8000
   streamlit run ui/streamlit_app.py
   ```

   Or: `make ui` (set `JEEVES_API_BASE` if the API is not on `127.0.0.1:8000`).

The sidebar has **Start chat** / **Close chat**; the main column is the thread; the right column lists **memory candidates** with **Confirm** / **Reject**. When a normalized request awaits review, the bottom chat box is disabled until **Confirm** or **Apply correction** (matches backend gates).

### API endpoints (v1)

- `GET /` — minimal HTML chat (same API as below)
- `GET /health`
- `GET /dev/ping-db`
- `POST /dev/bootstrap-chat`
- `POST /dev/demo-flow`
- `POST /chat/start`
- `POST /chat/message`
- `POST /chat/correction`
- `POST /chat/confirm`
- `POST /chat/close`
- `POST /memory/store`
- `GET /memory/candidates`
- `POST /memory/candidates/{id}/confirm`
- `POST /memory/candidates/{id}/reject`
- `GET /profile?user_id=...`

### LLM providers & fallback

All LLM-backed paths use **PydanticAI** with the **OpenAI-compatible** client (`OpenAIModel` + `OpenAIProvider`). Provider order and automatic fallback on runtime/API errors are centralized in **`app/llm/fallback.py`**.

| Layer | Primary | Fallback |
| --- | --- | --- |
| **Normalization** (parse task) | OpenAI | DeepSeek |
| **ExecutionDecision**, **Memory**, **Execution runner** | DeepSeek | OpenAI |

A step runs only if the corresponding flag is on **and** the API key is non-empty after trim. If the primary call fails, the next provider in the chain is tried; if all fail, you get one `RuntimeError` with combined reasons.

**OpenAI** (`OPENAI_ENABLED=true`, `OPENAI_API_KEY` required):

| Variable | Role |
| --- | --- |
| `OPENAI_BASE_URL` | Optional; default OpenAI cloud if empty |
| `OPENAI_NORMALIZE_MODEL` | Normalization (with fallback to `OPENAI_INTERPRET_MODEL`) |
| `OPENAI_INTERPRET_MODEL` | Default name used in several fallbacks |
| `RESPONSE_FALLBACK_MODEL` | OpenAI model when DeepSeek is primary and no explicit override is set |

**DeepSeek** (`DEEPSEEK_ENABLED=true`, `DEEPSEEK_API_KEY` required):

| Variable | Role |
| --- | --- |
| `DEEPSEEK_BASE_URL` | Default `https://api.deepseek.com` |
| `DEEPSEEK_RESPONSE_MODEL` | Shared default when a specific model is unset |
| `DEEPSEEK_NORMALIZE_MODEL` | Normalization (when used as fallback after OpenAI) |
| `DEEPSEEK_EXECUTION_MODEL` | ExecutionDecision |
| `DEEPSEEK_MEMORY_MODEL` | Memory agents |
| `DEEPSEEK_RUNNER_MODEL` | Text-only execution runner |

When `JEEVES_DEV_STUB_AGENTS=true`, dev/demo paths use in-process stubs instead of real providers. Unit tests inject **PydanticAI `TestModel`** and do not need network keys.

### Persistence

Implemented tables (via SQLModel) in `app/repositories/models.py`:

- `chats`
- `messages`
- `normalized_requests`
- `execution_decisions`
- `memory_candidates`
- `memory_entries`
- `core_profile_entries`

### Tests

```bash
pytest
```

### What is stubbed or out of scope (v1)

- **Tools, delegates, web retrieval, external APIs**: not implemented; `ExecutionService` returns **blocked** unless the decision is text-only self-execution with all `needs_*` false.
- **Queue / worker for post-chat analysis**: `POST /chat/close` runs `run_post_chat_analysis` **in-process** (same request). A future worker would call the same function; queue wiring is not production-ready yet.

### Execution runner (v1)

The backend includes a **minimal text-only execution runner**:

- Runs only when `ExecutionDecision.can_execute_self=true` and all `needs_*` flags are false.
- Produces plain text; does **not** invoke tools, browsing, or delegates.
- Otherwise returns an honest **blocked** result (no fake execution).

### Explicit memory command flow (v1)

Messages matching the explicit-memory pattern (e.g. `запомни` / `remember`):

- Create a **`MemoryCandidate` only** (no durable write until confirm).
- With LLM configured (DeepSeek → OpenAI chain), classification uses the memory agent; with no LLM available, a **placeholder** candidate is used (still requiring `POST /memory/candidates/{id}/confirm`).

### Correction vs standing preference (v1)

On **`POST /chat/correction`** (same `NormalizedUserRequest` contract, new revision):

- **Task-local refinements** (language/length/tone/register for *this* answer: e.g. “in Russian”, “shorter”, “without pathos”) stay in the normalized request via the normalization agent — no durable memory unless the user also states an ongoing rule (see below).
- **Standing preferences / rules** for *future* chats (“always reply in Russian”, “address me with ты”, “never use emojis”) are detected by a **separate LLM step** in `MemoryAgent` (`StandingPreferenceExtraction`). If proposed, a **`MemoryCandidate`** is created (`source=user_requested`); the user must **confirm** via memory API — same rule as explicit memory: **no auto-write** to long-term/core profile.
- **Both** can apply in one message: normalization revises the current task; memory may add an optional candidate for the durable part. If extraction is unsure, it declines memory (conservative).

### Memory graph (orchestration)

The memory LangGraph defines nodes such as `post_chat_memory_analysis`, `review_memory_candidates`, and bridge nodes for confirm/reject/write. In v1, **durable writes and candidate confirm/reject** are driven by the **memory HTTP API** (`/memory/candidates/...`); the graph documents flow and stays separate from the main chat graph.
