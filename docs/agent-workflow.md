# Agent Workflow

How Claude Code and Codex should be used together during the build.

---

## Two agents, two roles

| Agent | Primary role | When to use |
|-------|-------------|-------------|
| **Claude Code** | Architect and implementer | Architecture decisions, multi-file phase implementations, explanations, doc updates |
| **Codex** | Reviewer and surgical implementer | Reviewing Claude's work, small focused fixes, writing tests, catching bugs |

Neither agent replaces the other. The most effective workflow alternates between them:
Claude implements a phase, Codex reviews it, the user merges and moves on.

---

## Phase workflow

### Before a phase begins

1. The user reads the phase definition in `docs/roadmap.md`
2. The user opens Claude Code and says: "We are starting Phase N — [name]"
3. Claude Code reads `CLAUDE.md`, `docs/roadmap.md` (the relevant phase), and any files
   it needs to understand the current state
4. Claude Code confirms its understanding of the phase scope before writing any code
5. If anything is unclear, Claude Code asks before building

### During a phase

- Claude Code works on only the files required by that phase
- Claude Code does not refactor adjacent code unless it is directly blocking the phase
- Claude Code does not add features that belong to future phases
- If Claude Code notices something that should be in a future phase, it flags it in a
  comment or note — but does not build it

### After a phase (Claude Code summary)

Claude Code must provide:
- A list of files created or modified, with a one-line explanation of why each one exists
- A description of how data flows through the new code end-to-end
- Instructions for how to run and test the changes locally
- At least one thing that could break in production and why
- What the user should understand about this phase before moving on

### After a phase (Codex review)

1. The user opens Codex and says: "Review Phase N — [name]. See AGENTS.md for instructions."
2. Codex reviews all changed files using the checklist in `AGENTS.md`
3. Codex runs type-check, lint, and any available tests
4. Codex reports findings with file:line references and severity ratings
5. High findings must be resolved before merging
6. Medium and low findings can be deferred if the user decides they are acceptable

### Merging

Only merge a phase when:
- Claude Code has provided its post-phase summary
- Codex has completed its review
- All high-severity findings are resolved
- The user has tested the feature manually (where possible)

---

## Branch strategy

For each phase, use a separate branch:

```
main                    ← stable, reviewed code only
  └── phase-1-scaffold  ← Claude Code works here
  └── phase-2-schema    ← Claude Code works here
  └── phase-3-api       ← Claude Code works here
```

If both agents are working simultaneously on the same phase (e.g. Claude implements
while Codex reviews a prior phase):
- Claude works on `phase-N`
- Codex reviews on `phase-N-review` (a branch off `phase-N`)
- Codex's fix commits are cherry-picked or merged back to `phase-N`

---

## What to never do

**Do not let either agent make broad refactors without approval.**
A refactor that touches more than the current phase scope requires explicit user
approval. If an agent starts refactoring things that were not part of the task, stop it.

**Do not let Claude skip ahead.**
Claude Code must not implement Phase N+1 while Phase N is in progress. If you notice
Claude adding features that belong to a future phase, call it out.

**Do not let Codex change architecture.**
Codex's job during review is to find bugs, not redesign systems. If Codex thinks the
architecture is wrong, it should flag it as a finding — not rewrite it.

**Do not bypass the review layer.**
If either agent writes code that creates domain records without going through the inbox,
reject the change immediately. This is a high-severity finding in every review.

**Do not merge without review.**
Every phase gets a Codex review before merging. No exceptions during the build phase.

---

## Documentation updates

When the architecture changes (new entity, new endpoint, new layer), the documentation
must be updated in the same phase:
- `docs/architecture.md` if the system layers change
- `docs/data-model.md` if a new entity is added or a field is changed
- `CLAUDE.md` if a new standing instruction is needed
- `docs/roadmap.md` if a phase definition changes

Documentation updates are part of the phase, not optional cleanup.

---

## Using Codex as a learning tool

After each phase, you can ask Codex to:
- Explain a specific piece of code that Claude wrote
- Generate test cases for a specific function or endpoint
- Write a short summary of what the phase built and how it fits the larger system
- Check for any patterns that differ from the architecture docs

This helps you stay informed and build your own understanding alongside the agents.
