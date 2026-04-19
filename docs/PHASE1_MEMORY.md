# Phase 1 memory

Aligned with [README](../README.md) (sections **Explicit memory command flow**, **Memory graph**, **Post-chat close**, **Local SQLite and schema changes**).

## Explicit `запомни` / `remember`

**Direct command path, not general memory-intent understanding:** only messages whose **trimmed** text **starts with** `запомни` or `remember` are routed here. That produces a **`MemoryCandidate`** (LLM-structured or minimal stub). **No** `memory_entries` row until `POST /memory/candidates/{id}/confirm`.

## Candidate vs confirmed

- **Candidate** — `memory_candidates` (pending review).
- **Confirmed** — after confirm, **`memory_entries`**.

## Main normalization / execution loop

The main path **does not** retrieve **`memory_entries`** or inject them into prompts. **`GET /profile`** reads **`core_profile_entries`**, separate from **`memory_entries`**.

## Post-chat close

`POST /chat/close` sets **`chats.post_chat_extraction_completed`** after successful `run_post_chat_analysis`, so a **second** close does **not** duplicate post-chat candidates. If extraction **fails**, the flag stays unset — **call close again** to retry.

## Local SQLite

No Alembic migrations in this repo; `create_all` does not add columns to existing tables. Pre-change SQLite files need **`post_chat_extraction_completed`** — see README **Local SQLite and schema changes** (recreate file or `ALTER TABLE`).

See also: [UNDERSTANDING_FLOW.md](UNDERSTANDING_FLOW.md) · [MEMORY_NEXT_STEP_DIRECTION.md](MEMORY_NEXT_STEP_DIRECTION.md)
