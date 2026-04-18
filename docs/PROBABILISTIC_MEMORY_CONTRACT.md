# Probabilistic memory — contract

This document defines the **meaning** of probabilistic memory in Jeeves. It is not an implementation guide.

## Core belief representation

Each **probabilistic memory slot** (see `MEMORY_FIELD_SCHEMA.md`) carries at least:

- a scalar **propensity** \(p \in [0,1]\) interpreted as “how strongly we should lean toward this default, given evidence so far,” and
- sufficient statistics **(k, n)** used to compute \(p\) under the baseline law below.

### Baseline law

\[
p = \frac{k}{n + 1}
\]

This is a deliberately simple, auditable default. Implementation may store \((k,n)\) only and derive \(p\) when needed.

### What is **n**

**n** is the count of **relevant outcomes** (see below) observed for this slot **after** the slot became **applicable** to the user (i.e., not `not_applicable`).

Properties:

- **n** increases only when the system could have behaved in a way that makes the user’s subsequent signal informative **about this slot**.
- If a turn is irrelevant to a slot, it must not increment **n** for that slot.

### What is **k**

**k** is the accumulated **support mass** for the proposition represented by the slot after each relevant outcome:

- Start from **k = 0** at slot creation (unless a product policy defines an explicit prior mass; if so, that mass must be documented as a bias term separate from user evidence).
- On each relevant outcome, add a **weight** \(w \in [0,1]\) to **k**, where \(w\) is higher when the user signal more clearly supports adopting/strengthening this default.

Notes:

- **k** is not required to be an integer; fractional updates are allowed when evidence is partial.
- **k** must never increase without a corresponding semantic evidence event tied to that slot (no synthetic boosts from keyword matches).

### Mapping (k, n) to p

With the baseline law:

- Early observations move \(p\) quickly; later observations move it more slowly, reflecting accumulated context.
- The “+1” in the denominator prevents division-by-zero and acts like a **conservative dampener** when evidence is sparse.

If a future implementation introduces richer priors, it must remain backward-compatible with the semantics: **sparse evidence ⇒ wide uncertainty**, not a hard commitment.

## Relevant outcome

A **relevant outcome** for slot \(S\) is an **episode** where:

1. The slot \(S\) is **applicable** (not `not_applicable`), and
2. The assistant produced (or chose among) behaviors that **could** depend on \(S\)’s value, **or** the user explicitly discussed \(S\) (e.g., “always shorter answers”), and
3. The user had a realistic opportunity to react (implicitly by continuing, explicitly by correcting, approving, rejecting, or issuing a memory-related command).

Episodes are counted at **turn granularity** or finer **only** if the finer granularity can be attributed cleanly; otherwise use one increment per user-visible step.

## Favorable outcome

A **favorable outcome** for proposition \(P\) represented by slot \(S\) is any relevant outcome where the user’s reaction implies:

- “Yes, that default is what I want in situations like this,” or
- “That was better than the alternative along the axis modeled by \(S\),” or
- an explicit instruction to remember/strengthen \(P\).

Unfavorable outcomes increment **n** (because the episode was informative) but add little or no mass to **k**, and may explicitly reduce propensity via documented update rules (`MEMORY_UPDATE_RULES.md`).

Ambiguous reactions should yield **small** \(w\), not a full step.

## Local user instruction vs memory

- **Local instruction** is whatever the user requires **for this deliverable**, carried primarily by the current `NormalizedUserRequest` (and the chat transcript). It is **authoritative for the task** even if it contradicts memory.
- **Memory** is a **prior** and **default** for future tasks when the user does not specify otherwise.

Interaction rules:

1. **Local wins for the current task** — never “helpfully” override an explicit local constraint using a probabilistic default.
2. **Memory still learns from local** only when the user signal indicates a **standing** preference (e.g., “always do this”) or repeated patterns; a one-off stylistic tweak does not automatically become a durable belief.
3. If local and memory disagree, the assistant follows local **and** logs evidence in a way that can **softly down-weight** the conflicting slot rather than flipping it instantly (unless the user explicitly asks to change the standing default).

## Why memory is not binary

Users:

- change their minds,
- want different styles in different contexts,
- give noisy feedback,
- sometimes ask for exceptions “just this once.”

Binary memory collapses these into irreversible flags that are both **wrong often** and **coercive** UX-wise. Probabilistic slots represent **graded evidence** and keep the system honest about uncertainty.

## Communication defaults as probabilistic slots

**Communication defaults** are the highest-priority probabilistic slots because they shape every reply:

Examples of slot families (non-exhaustive; exact keys live in `MEMORY_FIELD_SCHEMA.md`):

- default response language register,
- verbosity vs terseness,
- tone (neutral/warm/direct),
- formatting habits (lists vs prose) **when not overridden by task**,
- “ask clarifying questions vs assume” propensity **within safe bounds** (must remain compatible with Phase 1 clarification gates).

Each default is a **separate** slot with its own \((k,n)\), so evidence about “tone” does not contaminate “verbosity.”

These slots must always expose:

- current \(p\) (or \((k,n)\)),
- applicability (`not_applicable` when unknown),
- last evidence source type (reaction / correction / explicit / none).

## Non-goals

- Using \(p\) as a sneaky way to bypass clarification when `NormalizedUserRequest` says clarification is required.
- Encoding task-specific facts (deadlines, names, one-off constraints) into communication-default slots.
