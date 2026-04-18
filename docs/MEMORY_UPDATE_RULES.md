# Memory update rules (probabilistic)

These rules define **how evidence becomes (k, n) changes**. They intentionally avoid any **central** candidate/confirm queue; confirmation for **task understanding** remains part of Phase 1 and must not be conflated with memory updates.

## Evidence sources

Memory may move only on:

1. **User reaction** — satisfaction signals, thanks, complaints, “too long”, “rewrite”, etc., interpreted **semantically** (LLM judgment or user explicit wording), never keyword lists.
2. **Correction** — user messages that revise `NormalizedUserRequest` via the correction loop.
3. **Explicit instruction** — user says they want a standing preference remembered (including “remember …” commands in locales supported by the product).

Each update must record `last_evidence_kind` accordingly.

## Update on user reaction

When a user reaction is **relevant** to slot \(S\) (see contract):

- increment **n** by 1 for \(S\),
- add weight \(w\) to **k** if the reaction is **favorable** toward the current behavior along \(S\)’s axis,
- otherwise add \(w \approx 0\) to **k** (optionally small negative mass via product-specific damping, but never silently flip to a hard opposite without explicit instruction).

If the reaction targets the **task content** rather than a standing default (e.g., “wrong date”), do not treat it as strong evidence for communication defaults.

## Update on correction

Corrections always produce a new `NormalizedUserRequest` revision; memory update distinguishes:

- **Task-local correction** — fixes scope, facts, or deliverable shape for this task: update chat memory; **do not** substantially move durable defaults unless the correction language indicates standing change.
- **Standing correction** — user indicates repetition across future tasks (“always”, “never”, “by default”): this may create evidence for relevant slots **with small \(w\)** unless the user explicitly demands an immediate high-confidence change.

After a correction, increment **n** for slots that were **actually implicated** by the correction’s meaning (not all slots globally).

## Update on explicit instruction

Explicit instructions are the strongest permitted evidence:

- The user is stating a **policy** for future behavior.
- Apply a **larger** \(w\) to **k** (still not infinite; avoid single-message tyranny) and increment **n**.
- If the instruction is unsafe, illegal, or violates product policy, **do not** learn it as a default; mark as `not_applicable` or ignore with logged refusal per future implementation policy.

If the user names a slot explicitly (“change my default tone to …”), update that slot’s summary and **reset** or **re-anchor** \((k,n)\) in implementation later **only** via a documented, user-visible operation (this doc marks the semantic need, not the UX).

## Why one episode must not produce a hard conclusion

Single episodes are high-variance:

- users experiment,
- mistakes happen,
- assistants misread intent.

Therefore:

- **never** promote a probabilistic slot to certainty from one datapoint unless the user explicitly demands it and the product layer records it as a **user-authored preference** (not implied statistics),
- prefer **small** \(w\) for ambiguous signals.

## Combining probabilistic memory with the current local task

Ordering:

1. Build and clarify `NormalizedUserRequest` (Phase 1).
2. After confirmation, execute under explicit local constraints.
3. When generating language, **read** probabilistic defaults only where local constraints are silent.
4. After the turn, apply MEMORY_UPDATE_RULES to slots implicated by evidence.

Conflict resolution:

- Local explicit instructions **suppress** defaults for this task.
- Repeated local instructions across many tasks accumulate into higher **k** for matching slots.

## Applicability changes

Users must be able to set `not_applicable` for a slot:

- immediately stops influence,
- stops **n** increments except for evidence that explicitly re-enables the slot.

Moving from `not_applicable` back to active must require an **explicit** user action.

## Forbidden patterns

- Using execution-stage success as a blanket excuse to spike all communication slots.
- Writing durable memory that contradicts the latest **confirmed** normalized task line for the same turn (task line wins retroactively for that task).
- Inferring standing preferences from **pre-confirmation** drafts while the user is still correcting understanding (evidence is too noisy); memory learning should anchor on post-confirmation behavior **unless** the user is explicitly talking about memory, not the task.
