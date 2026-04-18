# AGENTS.md

## Repository intent
This repo implements Jeeves as a chat-first agent with:
- NormalizedUserRequest
- correction loop
- ExecutionDecision
- layered memory
- LangGraph orchestration

## Non-negotiable architecture rules
- Never execute before normalized request review/confirmation.
- User correction must revise the same request object, not create a different abstraction.
- Do not replace semantic revision with fake heuristics if the task requires real model-driven revision.
- Do not write directly into deep memory without candidate/review flow.
- Keep chat memory, long-term memory, and core profile separate.

## Working style
- Inspect before editing.
- Plan before coding.
- Prefer minimal diffs.
- Reuse existing domain models and services.
- Do not invent new abstractions without necessity.

## Done means
- relevant tests pass
- core flow is preserved
- no stub is presented as finished behavior
- changed files are listed
- architectural impact is explained briefly

## If task is ambiguous
Ask questions before editing.


## Mandatory workflow
1. First inspect current files.
2. Then write a short plan.
3. Do not code before the plan.
4. Then list exact files to change.
5. Only then implement.

## Forbidden
- Do not invent placeholder behavior and present it as final.
- Do not replace semantic behavior with heuristics unless explicitly requested.
- Do not collapse multi-step flow into one step.
- Do not bypass confirmation or review stages.
- Do not introduce new abstractions unless necessary.
- Do not claim task is complete if core behavior is still stubbed.

## For this repo specifically
- Never run ExecutionDecision before NormalizedUserRequest review.
- User correction must revise the same request object.
- Keep chat memory, long-term memory, and core profile separate.
- Memory candidates must be reviewed before becoming durable memory.
- If LLM-backed behavior is required, do not fake it with rule-based code.

## Required output format
- Current understanding
- Plan
- Files to change
- Implementation
- What remains stubbed, if anything
