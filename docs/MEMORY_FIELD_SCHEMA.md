# Memory field schema (Milestone 2 — minimal)

This schema is the **minimum** durable surface for probabilistic memory. Implementation may add internal bookkeeping, but **must not omit** the semantic obligations defined here.

## Global requirements (every probabilistic field)

Each probabilistic field stores:

- `key` — stable identifier (machine stable).
- `value_summary` — short human-readable description of what high-\(p\) means.
- `k`, `n` — counters obeying `PROBABILISTIC_MEMORY_CONTRACT.md`.
- `p` — derived propensity \(p=k/(n+1)\) **or** computed on read from \((k,n)\).
- `applicability` — one of:
  - `unknown` — not enough evidence to treat as applicable.
  - `applicable` — field is active and may influence behavior when not contradicted locally.
  - `not_applicable` — user or policy declares this axis irrelevant; must not influence behavior.
- `last_evidence_kind` — `reaction` | `correction` | `explicit` | `none`.
- `last_updated_at` — opaque timestamp string in implementation; required for audit.

### Fields that must never be silently skipped

If a subsystem is consulted for personalization, it must **not** pretend a missing field is “neutral.” It must choose one of:

- consume the field normally when `applicability=applicable`,
- ignore it explicitly when `not_applicable`,
- treat as **unknown** and avoid claiming certainty when `unknown`.

Skipping without recording `unknown` vs `not_applicable` is forbidden because it confuses user trust and breaks debugging.

### Fields that must be explicitly marked `not_applicable`

These dimensions are socially sensitive or frequently unwanted; users must be able to opt out without the system guessing:

- any field inferring **relationship/intimacy** of address (e.g., formal vs informal pronouns) unless user consented to inference,
- any field inferring **risk-sensitive** behavioral defaults (e.g., autonomy in financial/legal/medical domains) beyond product-wide safety baselines,
- any field that guesses **protected attributes**; such slots must remain `not_applicable` unless explicitly user-authored.

## Minimal field set

### A) Communication defaults (probabilistic slots)

Each bullet is its **own** slot with independent \((k,n)\):

1. `comm_language_register` — default human language/register for assistant replies when the user does not specify otherwise in the current task.
2. `comm_verbosity` — terse vs expansive default.
3. `comm_tone` — warm/neutral/direct baseline.
4. `comm_structure` — default formatting preference when unconstrained by the task (prose vs bullets vs mixed).
5. `comm_clarification_aggressiveness` — tendency to ask clarifying questions vs proceed; must remain subordinate to Phase 1 gates (cannot force execution before confirmation).

### B) Broader user profile (probabilistic + sparse factual anchors)

These are **slow-moving** beliefs; some may remain `unknown` for a long time.

Probabilistic slots:

1. `work_context` — propensity that the user is usually discussing professional/work topics vs personal topics (not a job title extractor).
2. `decision_support_style` — prefers options+tradeoffs vs single recommendation vs “just do it” framing.
3. `risk_posture_communication` — how cautiously the assistant should phrase uncertain recommendations **by default** (distinct from safety policy).

Explicit non-probabilistic anchors (still required to be labeled clearly in storage later; specified here as semantic intent):

- `standing_exclusions` — user-declared “never do X” rules **in the user’s own wording**, edited only via explicit user confirmation in product UX (these are not implied from a single episode).

`standing_exclusions` is **not** modeled as \((k,n)\); treat it as a **small curated list** with provenance. Probabilistic memory informs defaults; **hard exclusions** remain rare and user-authored.

## Which fields are probabilistic

All slots in sections **A** and the probabilistic items in **B** use \((k,n)\) and \(p\).

## Applicability matrix (normative)

| Field | Default applicability | Must support `not_applicable` |
|------|------------------------|-------------------------------|
| Communication defaults | `unknown` at onboarding | yes |
| `work_context` | `unknown` | yes |
| `decision_support_style` | `unknown` | yes |
| `risk_posture_communication` | `unknown` | yes |
| `standing_exclusions` | `not_applicable` until user-authored | yes (via empty list + explicit opt-in) |

## Non-requirements

- This milestone does not require final human labels for every language variant; `value_summary` is English for internal consistency, while `comm_language_register` governs user-visible language.
