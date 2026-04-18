# Milestone 2 — Probabilistic memory (spec only)

This milestone is **documentation-only**. It prepares Phase 2 **probabilistic memory** without changing Phase 1 behavior, the chat-first understanding loop, or the execution confirmation gate.

## Boundaries

### In scope (Milestone 2)

- A **probabilistic** representation of durable user-specific priors (long-term layer and core profile layer), grounded in **observed outcomes** rather than a single boolean “true/false” fact per slot.
- Clear separation between:
  - **Chat memory** — verbatim thread, current `NormalizedUserRequest` revisions, execution artifacts for this session.
  - **Probabilistic durable fields** — slowly moving beliefs with explicit uncertainty (see `PROBABILISTIC_MEMORY_CONTRACT.md`).
- **Update rules** that consume **semantic** evidence (user text, structured assistant turns, explicit user commands) without keyword routing tables (see `MEMORY_UPDATE_RULES.md`).
- A **minimal field schema** that is enough to implement later without inventing a parallel product architecture (see `MEMORY_FIELD_SCHEMA.md`).

### Out of scope (Milestone 2)

- Any change to Python modules, LangGraph nodes, prompts, repositories, migrations, HTTP routes, or UI.
- Replacing or bypassing Phase 1:
  - `NormalizedUserRequest` remains the only normalized “task contract” for the turn.
  - User corrections still revise the **same** object type with a new `revision`.
  - `ExecutionDecision` still runs **only** after normalized-request review/confirmation.
- Designing or requiring a **central** memory pipeline built around **candidate queues + mandatory confirm** as the primary write path. (Existing v1 endpoints may remain in the codebase for compatibility; Milestone 2 defines the **target** probabilistic layer separately.)
- Tooling, browsing, delegation, decomposition — unchanged.

### Deferred to Milestone 3+

- Storage layout, indexing, retention, and privacy redaction for probabilistic fields.
- Calibration, per-field priors beyond the baseline update law, and conflict resolution across devices/sessions.
- UX for inspecting/editing/resetting beliefs (beyond stating that users must be able to understand what the system “leans toward”).
- Post-chat **batch** distillation jobs (if any) as optimization; Milestone 2 assumes **online-friendly** updates are sufficient to specify semantics.
- Advanced governance (rate limits on belief drift, legal holds, enterprise policy engines).

## Why probabilistic memory is separate from the understanding flow

The understanding flow answers: **what is the user asking to do right now, in this thread, with what ambiguity?** It is intentionally **task-local**, **reviewable**, and **versioned** as `NormalizedUserRequest` (see `docs/UNDERSTANDING_FLOW.md`).

Probabilistic memory answers a different question: **across many tasks, what does the user generally want the assistant to assume by default, and how confident are we?** That question:

- depends on **repeated evidence** and **noisy** user signals, not on a single clarified utterance;
- must not **silently rewrite** the current normalized task line (which would break user trust and the Phase 1 contract);
- must remain useful even when users are **inconsistent** or **context-dependent** — hence non-binary beliefs.

Keeping these layers separate preserves:

1. **The execution gate** — execution follows confirmed understanding, not “whatever the profile says.”
2. **Semantic normalization quality** — the normalization model is not asked to simultaneously optimize long-term belief states.
3. **Auditability** — users can see the current task; memory remains an orthogonal prior that competes politely with explicit local instructions.

## Relationship to Phase 1 (non-breaking)

Milestone 2 adds **beliefs and counters** (or equivalent sufficient statistics) that **condition** future assistant behavior **without** replacing:

- the LLM-first normalization step,
- the user-visible understanding summary,
- the explicit confirmation step before `ExecutionDecision`.

Any future implementation must treat probabilistic memory as **soft constraints** that yield to explicit user instructions for the current deliverable, while still accumulating evidence unless the user marks a dimension **not applicable** (see field schema and update rules docs).

## Success criteria for the later implementation milestone (informative)

When implementation work begins after this spec milestone, “done” should mean: every automated memory mutation is attributable to an **evidence event**, fields have explicit **applicability** and **uncertainty**, and no code path promotes a single chat episode into a irreversible hard flag without an explicit user policy exception.
