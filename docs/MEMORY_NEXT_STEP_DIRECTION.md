# Memory — next-step direction

Referenced from README **Memory graph** for future product/infrastructure choices — **not** implemented in Phase 1. No code in this document.

## Principles

- **Task first, memory second** — memory must not lead the flow.
- Memory is for **gaps** only: use it when the **current request** plus **nearby context** are **not** enough to fill missing fields.

## Intended stored unit (product)

A **completed episode** with a **filled contract** — store meaningful fields only (no empty placeholders as the record, no ad-hoc “request classes,” no counters, no precomputed probabilities **as** the stored memory blob).

## Next infrastructure fork

Evaluate **custom** storage/retrieval over completed contracts vs an **external** layer (e.g. mem0-class) for storage/retrieval — while **contract semantics, explainability, ask/not-ask, and source priority** (current request → nearby context → memory) stay **in Jeeves**.

## Phase 1 today

Prefix **`запомни` / `remember`** is narrow; **candidate ≠ confirmed**; confirmed **`memory_entries`** are **not** wired into main-loop prompts. Details: [PHASE1_MEMORY.md](PHASE1_MEMORY.md).
