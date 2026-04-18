# Understanding flow (chat-first)

Jeeves treats each user turn as a **single structured object** (`NormalizedUserRequest`) produced by the normalization LLM. That object encodes an explicit **three-phase understanding model** without extra graph nodes:

1. **Semantic normalization** — `semantic_utterance_interpretation`: what the words mean in isolation.
2. **Dialog attachment** — `dialog_attachment_interpretation`: what prior turn or artifact the utterance targets, or what referential link is still unresolved.
3. **Action** — `normalized_user_request`: the executable task line once (1) and (2) are settled enough to proceed, or the best-effort task plus clarification.

## Clarification kinds

`understanding_clarification_kind` refines *why* clarification is needed (orthogonal to tools/execution):

| Value | Meaning |
| --- | --- |
| `none` | No understanding-level block. |
| `phrase_unclear` | The utterance itself could not be interpreted reliably. |
| `attachment_unclear` | The phrase is understood but **what it refers to** in the thread is not. |
| `execution_data_missing` | Utterance and attachment are clear enough, but **facts/parameters** are missing for execution. |

When `phrase_unclear` or `attachment_unclear` is set, the domain model forces `needs_clarification=true` if the model omitted it. The assistant must ask rather than guess.

## Persistence (v1)

Understanding fields are **not** written to `normalized_requests`. They exist on the in-memory `NormalizedUserRequest` for the turn and appear in the **assistant message** from `show_normalized_request`. After reload from DB, those fields default to empty / `none` until the next normalization.

## Product rules (unchanged)

- Normalization (including the three phases above) is **shown to the user** before confirmation.
- **ExecutionDecision** runs only after explicit confirmation.
- Corrections are normal chat messages; they produce a **new revision** of the same `NormalizedUserRequest` contract.

## LLM-first

Routing between the three failure modes is **not** keyword-based: the classifier is the normalization model’s structured output.
