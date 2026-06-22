# Agent Workflow

How Claude Code and Codex should be used together during the build.

---

## Two agents, two roles

| Agent | Primary role | When to use |
|-------|-------------|-------------|
| **Claude Code** | Architect + Reviewer | Phase planning, security review, post-implementation review, architecture decisions, doc updates |
| **Codex** | Executor | Implement Claude's phase plan, write tests, verify lint/type-check/tests pass before handing back |

The workflow for every phase is: **Claude plans → Codex implements → Claude reviews.**

Neither agent replaces the other. Claude's plan is the contract Codex works to.
Claude's review is the gate before merging.

---

## Phase workflow

### Before a phase (Claude Code)

1. The user opens Claude Code and says: "We are starting Phase N — [name]"
2. Claude Code reads `CLAUDE.md`, `docs/roadmap.md` (the relevant phase), and any files
   it needs to understand the current state
3. Claude Code confirms the previous phase's definition of done before proceeding
4. Claude Code writes a plan that includes:
   - Which files change and why each one exists
   - Exact function/endpoint signatures and data shapes
   - Edge cases, failure modes, and security constraints
   - Test coverage expectations (which scenarios must be tested)
   - Any architectural choice with more than one reasonable answer — decided in the plan,
     not left for Codex to resolve
5. The user reviews and approves the plan before Codex starts

### During a phase (Codex)

- Codex implements the approved plan exactly
- Codex does not make architectural decisions — if the plan is underspecified on a point,
  Codex stops and asks the user, who brings the question back to Claude Code
- Codex does not add features that belong to future phases
- Codex runs lint, type-check, and all tests before handing back; reports the results

### After a phase (Claude Code review)

1. The user opens Claude Code and says: "Review Phase N — [name]. Codex has implemented it."
2. Claude Code reads every changed file against the approved plan
3. Claude Code checks the review checklist (see below)
4. Claude Code reports findings with file:line references and severity ratings
5. High findings must be resolved before merging — Claude Code either fixes them directly
   or writes a precise sub-plan for Codex to fix them
6. Once all high findings are resolved, Claude Code provides the post-phase summary

### Review checklist (Claude Code uses this when reviewing Codex output)

**Pipeline integrity**
- [ ] Does any change bypass the capture → inbox → review → confirm → domain record pipeline?
- [ ] Is any domain record created without an explicit user-confirmation step?

**Correctness**
- [ ] Does the code match the approved plan?
- [ ] Are there null-dereference risks, incorrect type assumptions, or off-by-one errors?
- [ ] Are database writes correct (right table, right columns, no missing NOT NULL fields)?
- [ ] Are async operations awaited correctly?

**Security**
- [ ] Are secrets read from environment variables only — never hardcoded or leaked to the frontend?
- [ ] Is user input validated at system boundaries?
- [ ] Are webhook endpoints verifying their secret tokens?
- [ ] For broker/financial code: are allowlists enforced, are non-finite floats rejected,
     is TLS handled correctly?

**Scope**
- [ ] Does the implementation stay within the current phase scope?
- [ ] Has Codex added features that belong to a future phase?
- [ ] Are there circular dependencies introduced?

**Overengineering**
- [ ] Is any abstraction added that is not required by the phase?
- [ ] Is there premature generalization or unnecessary configurability?

**Tests**
- [ ] Are there tests for non-trivial logic and all new API endpoints?
- [ ] Does the full existing test suite still pass?

### Merging

Only merge a phase when:
- Claude Code's plan was approved before implementation started
- Codex has confirmed lint, type-check, and tests pass
- Claude Code has completed its review
- All high-severity findings are resolved
- The user has manually tested the feature where possible

---

## Branch strategy

For each phase, use a separate branch:

```
main                      ← stable, reviewed code only
  └── phase-N-name        ← Codex implements here
```

If a finding from Claude's review requires a fix:
- Small fixes: Claude Code commits directly to the phase branch
- Larger fixes: Claude Code writes a sub-plan; Codex implements on the same branch

---

## What to never do

**Do not let Codex make architectural decisions.**
If Codex encounters an underspecified point and makes a judgment call instead of asking,
that judgment call needs to be reviewed carefully. Codex's job is faithful execution of the
plan, not design.

**Do not let Claude skip the plan step.**
Claude Code must not implement a full phase directly anymore. If Claude starts writing
implementation code for a phase that has not been handed to Codex, stop it. The plan must
come first so the user can review it before any code is written.

**Do not let either agent bypass the review layer.**
If either agent writes code that creates domain records without going through the inbox,
reject the change immediately. This is a high-severity finding in every review.

**Do not merge without Claude's review.**
Every phase gets a Claude Code review after Codex implements. No exceptions.

**Do not let Codex change architecture.**
Codex's job is execution, not design. If Codex thinks the architecture is wrong, it should
flag it for the user and Claude Code — not restructure it silently.

---

## Documentation updates

When the architecture changes (new entity, new endpoint, new layer), the documentation
must be updated in the same phase:
- `docs/architecture.md` if the system layers change
- `docs/data-model.md` if a new entity is added or a field is changed
- `CLAUDE.md` if a new standing instruction is needed
- `docs/roadmap.md` if a phase definition changes

Documentation updates are part of the phase plan — Claude Code includes them in the plan,
Codex implements them, Claude Code verifies them during review.

---

## Using Claude Code as a learning tool

After each phase review, ask Claude Code to:
- Explain why a specific design choice was made in the plan
- Walk through the data flow for a new feature end-to-end
- Describe what could break in production and why
- Explain what the next phase builds on top of this one

This helps you stay informed and build your own mental model alongside the agents.
