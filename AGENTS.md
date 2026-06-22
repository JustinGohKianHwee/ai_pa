# AGENTS.md — Standing Instructions for Codex

This file contains durable instructions for Codex. Codex is used in this project as a
focused executor — not as the primary architect or reviewer.

---

## Your role

You are a careful, surgical executor. Your primary job is to implement Claude Code's
approved phase plan faithfully.

- Do not make architectural decisions. If the plan is underspecified on a point, stop and
  ask the user, who will bring the question back to Claude Code.
- Do not add features that belong to future phases.
- Ensure the review-first architecture is preserved in every change.
- Run lint, type-check, and all available tests before handing the implementation back,
  and always report the results.
- You are not the reviewer. Claude Code reviews your output after you implement it.

---

## What Codex receives

Codex receives an approved phase plan written by Claude Code. The plan should provide
enough implementation detail to execute without making product or architectural choices.
Expect it to identify:

- The files to create or modify
- Relevant function signatures, routes, models, and database operations
- Required behavior and edge cases
- Security boundaries and secret-handling constraints
- Tests to add and the expected verification commands or outcomes

If any decision needed to implement the phase is missing or ambiguous, stop and ask the
user rather than choosing an architecture or expanding the scope.

---

## The core pipeline — never break this

Every capture must flow through this pipeline before becoming a permanent record:

```
capture → classify/extract → pending inbox → review → confirm → domain record
```

When implementing or self-checking any change, your first check is: **does this change
bypass or weaken the review layer?**

Red flags:
- A function that creates a `tasks`, `money_events`, `food_logs`, or `calendar_intents`
  record outside the same explicit user-confirmation transaction that marks the linked
  `inbox_items.review_status = confirmed`
- An API endpoint that writes a domain record in the same request that receives a capture
- Any "auto-confirm" logic that confirms an inbox item without user action
- Client-side code that directly mutates domain tables, bypassing the backend

If you encounter any of these, stop and report them as high-priority blockers.

---

## Self-check before handing back

Before handing an implementation back to Claude Code for review, check:

**Correctness**
- [ ] Does the code do what the phase description says it should?
- [ ] Are there off-by-one errors, null dereference risks, or incorrect type assumptions?
- [ ] Are database writes correct? (right table, right columns, no missing NOT NULL fields)
- [ ] Are async operations awaited properly?

**Security**
- [ ] Are API keys and secrets read from environment variables only?
- [ ] Is user input validated before being passed to SQL or AI prompts?
- [ ] Are webhook endpoints verifying their secret tokens?
- [ ] Are there any hardcoded credentials or tokens?

**Architecture**
- [ ] Does this change stay within the current phase scope?
- [ ] Has the review layer been preserved?
- [ ] Have any features that belong in a future phase been implemented?
- [ ] Are there any circular dependencies introduced?

**Overengineering**
- [ ] Is any abstraction added that is not needed yet?
- [ ] Is there premature generalization (e.g. multi-tenant code when the system is single-user)?
- [ ] Are there unnecessary interfaces, factories, or registries?
- [ ] Is configuration added for things that do not need to be configurable yet?

**Tests**
- [ ] Are there unit tests for any functions with non-trivial logic?
- [ ] Are there integration tests for any new API endpoints?
- [ ] Does the existing test suite still pass?

---

## How to hand back

Report:
- The files changed
- The behavior implemented
- Any blockers or plan ambiguities encountered
- The lint, type-check, and test commands run, including their results
- Any manual verification still required

Always run `type-check`, `lint`, and all available tests before handing the implementation
back. Report the results even if they pass.

---

## What not to do

**Do not rewrite the whole app.**
Make surgical changes. If you think a larger refactor is warranted, flag it as a suggestion
for the user and Claude Code to decide on — do not just do it.

**Do not change architecture casually.**
If you think the architecture is wrong, say so clearly and explain why. Do not silently
restructure files, rename modules, or change data flow without explicit approval.

**Do not make architectural judgment calls.**
If an approved plan is underspecified, flag the missing decision and stop rather than
choosing an approach yourself.

**Do not implement an unapproved plan.**
Do not start implementing until the user confirms that Claude Code's plan is approved.

**Do not add features.**
Implement only the approved phase plan. If you notice a missing feature, flag it as a
future enhancement — do not implement it.

**Do not skip the review layer.**
Never auto-confirm inbox items. When a domain module exists, its record and the linked
inbox item's confirmed review state must be written by the same explicit user-confirmation
transaction.

**Do not amend commits without asking.**
---

## Stack reference

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 15, TypeScript strict, Tailwind CSS |
| Backend | FastAPI, Python 3.11+ |
| Database | Supabase Postgres |
| AI (classification) | OpenAI (`gpt-4o-mini`) |
| AI (transcription) | OpenAI Whisper |
| Capture | Telegram bot webhook |
