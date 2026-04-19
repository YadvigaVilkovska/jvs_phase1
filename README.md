# Jeeves (backend)

**Phase 1** — understanding flow, review/confirmation, and execution gating are implemented; deeper product milestones are documented separately, not part of this README.

Jeeves is a **chat-first agent** with:

- **NormalizedUserRequest** (LLM-first normalization; understanding flow — `docs/UNDERSTANDING_FLOW.md`)
- **correction loop** (new revision of the same request object)
- **ExecutionDecision** (only after review/confirmation)
- **layered memory** (chat vs long-term vs core profile — see [Phase 1 memory boundaries](docs/PHASE1_MEMORY.md))
- **LangGraph orchestration**

This repository implements the **backend** (FastAPI + LangGraph + SQLModel). A minimal **HTML chat** is served at `GET /`; optional **Streamlit UI** lives under `ui/`.

The **local SQLite database file is not committed** to git. Development uses a SQLite file under `./data/` by default; that directory and database files are listed in `.gitignore`. The database file is **created on your machine** when you run the app (or when the process first opens the DB URL).

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

- Copy **`.env.example`** to **`.env`** and adjust if needed (defaults are safe for local stubbed development). You can instead rely on code defaults for `DATABASE_URL` and `JEEVES_DEV_STUB_AGENTS` when you prefer shell exports only.
- Invalid `DATABASE_URL` values fail at startup with a short explanation (unsupported `schema=` query params are rejected; use plain SQLite or a normal Postgres URL).

### Try locally (minimal)

1. Complete **Setup** above (venv + `pip install -e ".[dev]"`).
2. **Run API** (creates `./data/` and the SQLite file locally if needed — nothing under `./data/` is tracked in git):

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

- `chats` (includes `post_chat_extraction_completed` for post-close extraction idempotency)
- `messages`
- `normalized_requests`
- `execution_decisions`
- `memory_candidates`
- `memory_entries`
- `core_profile_entries`

### Local SQLite and schema changes

This repository **does not** include Alembic (or other) migrations yet. On startup, the app calls `SQLModel.metadata.create_all` (`app/db.py` / `app/main.py`). That **creates missing tables** but **does not add new columns** to tables that already exist inside an old database file.

If you use a **SQLite file created before** `chats.post_chat_extraction_completed` existed and the process fails with an error like `no such column: chats.post_chat_extraction_completed`, pick **one** path:

1. **Recreate the database (usual for local dev)**  
   Stop the server, **delete** the database file pointed to by `DATABASE_URL` (for example `./data/jeeves.db`), then start again. Startup will create a fresh schema. **All data in that file is lost.**

2. **Keep the file and patch the schema**  
   Run this against your SQLite file (path from `DATABASE_URL`):

   ```sql
   ALTER TABLE chats ADD COLUMN post_chat_extraction_completed BOOLEAN NOT NULL DEFAULT 0;
   ```

   If your SQLite tooling rejects `BOOLEAN`, use `INTEGER NOT NULL DEFAULT 0` instead (SQLite stores booleans as 0/1).

The same column is documented in [Phase 1 memory](docs/PHASE1_MEMORY.md).

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

**Direct command path, not general memory-intent understanding:** only messages whose trimmed text **starts with** `запомни` or `remember` are routed here ([Phase 1 memory](docs/PHASE1_MEMORY.md)). **Candidate memory is not confirmed memory** until `POST /memory/candidates/{id}/confirm`.

- Creates a **`MemoryCandidate` only** — **no** `memory_entries` row until confirm.
- With LLM configured (DeepSeek → OpenAI chain), the memory agent structures the payload; with no LLM, a **minimal** candidate is built from the payload text (still requiring confirm).

### Correction vs standing preference (v1)

On **`POST /chat/correction`** (same `NormalizedUserRequest` contract, new revision):

- **Task-local refinements** (language/length/tone/register for *this* answer: e.g. “in Russian”, “shorter”, “without pathos”) stay in the normalized request via the normalization agent — no durable memory unless the user also states an ongoing rule (see below).
- **Standing preferences / rules** for *future* chats (“always reply in Russian”, “address me with ты”, “never use emojis”) are detected by a **separate LLM step** in `MemoryAgent` (`StandingPreferenceExtraction`). If proposed, a **`MemoryCandidate`** is created (`source=user_requested`); the user must **confirm** via memory API — same rule as explicit memory: **no auto-write** to long-term/core profile.
- **Both** can apply in one message: normalization revises the current task; memory may add an optional candidate for the durable part. If extraction is unsure, it declines memory (conservative).

### Memory graph (orchestration)

The memory LangGraph defines nodes such as `post_chat_memory_analysis`, `review_memory_candidates`, and bridge nodes for confirm/reject/write. In v1, **durable writes and candidate confirm/reject** are driven by the **memory HTTP API** (`/memory/candidates/...`); the graph documents flow and stays separate from the main chat graph.

Confirmed rows live in `memory_entries`. The main normalization/execution path **does not** yet retrieve and inject those entries into prompts; `GET /profile` serves **`core_profile_entries`**, which is separate from `memory_entries` in v1. Details: [Phase 1 memory](docs/PHASE1_MEMORY.md). Next product/infrastructure choices (without implementing them here): [Memory next-step direction](docs/MEMORY_NEXT_STEP_DIRECTION.md).

### Post-chat close (v1)

`POST /chat/close` closes the chat (if not already closed), runs `run_post_chat_analysis`, then sets **`chats.post_chat_extraction_completed`** on success so a **second** close does **not** duplicate post-chat candidates. If extraction **fails** (exception), the flag is not set — **calling close again retries** extraction. **Older local SQLite files** need the new column — see **[Local SQLite and schema changes](#local-sqlite-and-schema-changes)** above and [Phase 1 memory](docs/PHASE1_MEMORY.md).
