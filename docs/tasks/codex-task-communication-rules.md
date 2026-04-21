# Codex task: implement probabilistic communication rules from chat

## Context
The project currently has memory candidates and confirmed memory entries. We need to extend the architecture so that **communication rules** are learned through normal chat messages, start with a low probability/score, and become stronger over time with confirmations and behavioral evidence.

This is **not** a simple confirmed-memory flow. It is a **policy layer** for assistant behavior.

Examples of communication rules:
- "Отвечай короче"
- "Не используй эмодзи"
- "Сначала дай вывод, потом детали"
- "Будь более формальным"

---

## Goal
Implement a new flow where user messages can create and evolve communication rules:

1. User expresses a communication preference in chat.
2. System extracts a rule candidate.
3. Candidate starts with low `score`.
4. Score increases or decreases based on later evidence.
5. Active rules are injected into prompt construction.
6. Rules can be revoked or weakened by contradictory feedback.

---

## Architecture requirements

### 1) Introduce a separate communication-rules layer
Do **not** model this only as a final confirmed memory entry.

Create a dedicated service, for example:

- `CommunicationRuleService`

Add dedicated persistence models/tables for:
- `communication_rule_candidates`
- `communication_rule_evidence`
- `communication_rule_state`

You may adapt names to current repo conventions, but keep the separation clear.

---

### 2) Add domain model(s)
Add domain objects for communication rules. Minimum concepts:

- `rule_key`
- `rule_text`
- `scope`
- `extraction_confidence`
- `score`
- `status`
- `evidence_count`
- timestamps

Suggested statuses:
- `candidate`
- `soft_active`
- `active`
- `rejected`
- `revoked`

Suggested scopes:
- `global`
- `current_chat`
- optionally `topic`

---

### 3) Separate two ideas
The code must distinguish between:

- `extraction_confidence`: how confidently the system extracted the rule from the message
- `score`: how strongly the system believes this rule should influence assistant behavior over time

These are not the same value.

---

## Required behavior

### A. Ingest rules from normal chat flow
Hook the new behavior into the normal user-message pipeline.

Likely integration point:
- `ChatService.post_user_message()` or the nearest equivalent point after normalization

When a user message contains a communication-style instruction:
- extract a candidate rule
- create the candidate/state record
- append first evidence event with type like `explicit_request`

### B. Apply rules before response generation
Before generating the assistant response:
- fetch applicable rules for current user/chat
- separate them into:
  - active rules
  - soft rules
- pass them into prompt construction

Expected behavior:
- active rules behave like high-priority communication preferences
- soft rules influence behavior but do not act like hard constraints

### C. Learn from later messages
Add evidence updates from future user messages.

Minimum evidence types:
- `explicit_request`
- `repeat_request`
- `explicit_confirmation`
- `positive_feedback`
- `negative_feedback`
- `explicit_revoke`

---

## Score update policy

Implement a simple deterministic first version.

Recommended default deltas:
- initial explicit request: `+0.20`
- repeat request: `+0.20`
- explicit confirmation: `+0.35`
- positive feedback after apply: `+0.15`
- negative correction: `-0.30`
- explicit revoke: mark rule as `revoked` and set score to `0`

Thresholds:
- `score < 0.35` -> candidate only
- `0.35 <= score < 0.70` -> `soft_active`
- `score >= 0.70` -> `active`

Clamp score to `[0, 1]`.

You may add a very small optional stability bonus later, but do **not** make time alone auto-promote a rule aggressively.

---

## Canonicalization
Implement a lightweight canonicalization layer for repeated phrasing.

At minimum, normalize equivalent messages like:
- "пиши кратко"
- "отвечай короче"
- "без лишней воды"

into one canonical rule key such as:
- `brevity`

Also support simple keys such as:
- `emoji_usage`
- `formality`
- `answer_structure`

This can be a deterministic mapper for MVP.

---

## Conflict handling
Add basic conflict resolution.

Examples:
- previous active rule: `brevity=high`
- new message implies: `detail_level=high` or opposite brevity preference

For MVP, implement a simple rule:
- newer contradictory evidence should decrease score of the old conflicting rule
- explicit revoke should win immediately

Avoid leaving two obviously contradictory active rules in force at the same time.

---

## Persistence design

### Required tables / models

#### `communication_rule_candidates`
Suggested fields:
- `id`
- `user_id`
- `chat_id`
- `rule_key`
- `rule_text`
- `scope`
- `extraction_confidence`
- `initial_score`
- `status`
- `created_at`

#### `communication_rule_evidence`
Suggested fields:
- `id`
- `rule_state_id` or `rule_id`
- `event_type`
- `delta`
- `message_id` nullable
- `created_at`

#### `communication_rule_state`
Suggested fields:
- `id`
- `user_id`
- `rule_key`
- `scope`
- `canonical_value_json` nullable
- `score`
- `status`
- `evidence_count`
- `last_confirmed_at` nullable
- `last_applied_at` nullable
- `updated_at`

If your current schema patterns suggest slightly different naming, follow repo conventions.

---

## Service API
Implement a service interface roughly like:

```python
class CommunicationRuleService:
    def ingest_user_message(self, ...): ...
    def register_feedback(self, ...): ...
    def update_rule_score(self, ...): ...
    def get_applicable_rules(self, ...): ...
    def revoke_rule(self, ...): ...
```

Exact signatures may follow the project style.

---

## Prompt integration
Add a resolver that returns rules ready for prompt usage.

Example output shape:

```python
{
    "active_rules": [
        "Отвечай кратко",
        "Не используй эмодзи"
    ],
    "soft_rules": [
        "Вероятно, предпочитает более формальный тон"
    ]
}
```

This output should be easy to inject into the system/developer prompt assembly layer.

---

## Tests
Add tests that cover at least:

1. Creating an initial low-score candidate from a user chat instruction
2. Repeating the same instruction increases score
3. Explicit confirmation promotes rule toward active
4. Negative feedback decreases score
5. Contradictory instruction weakens or revokes previous rule
6. `get_applicable_rules()` returns soft vs active rules correctly
7. Revoked rule is no longer injected into prompt context

Follow the project’s existing testing style.

---

## Files likely to touch
Adjust based on repo structure, but likely areas include:
- repository models / SQLModel definitions
- repositories for new rule tables
- new service: `communication_rule_service.py`
- `chat_service.py`
- prompt-building / graph integration layer
- tests

---

## Constraints
- Keep current memory flow working
- Do not break existing `fact` / `preference` / `rule` memory behavior unless intentionally refactoring it
- Prefer minimal but clean integration over a giant rewrite
- Use current repo naming/style conventions
- Keep the MVP deterministic and testable

---

## Acceptance criteria
The task is complete when:

1. A user can express a communication rule through chat.
2. The rule is stored with low initial score.
3. Repeated or confirming messages increase score.
4. Applicable rules influence response-generation context.
5. Contradictions and revoke messages weaken or disable rules.
6. Tests pass.

---

## Implementation note
Preferred direction:
- keep `MemoryService` for ordinary memory
- create a separate communication-rule lifecycle service

MVP is acceptable if integrated conservatively, but the code should clearly reflect that communication rules are a probabilistic policy layer rather than a simple binary memory entry.
