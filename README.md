# AI Personal Assistant

A private, modular AI personal assistant and personal operating system — built to capture,
classify, review, and act on life data across multiple domains.

---

## Long-term vision

A system that feels like a trusted personal memory layer and life command center. You speak
or type naturally through Telegram (or eventually voice notes, email, or a dashboard form),
and the assistant understands what you meant, classifies it, extracts structured data,
stores it in the right place, and surfaces it back to you for review.

Over time, it covers:

- Tasks and reminders
- Personal finance tracking
- Food / calorie / protein logging
- Notes and journal entries
- Calendar and scheduling
- Investment notes
- Daily planning and weekly review
- Goals, habits, and routines
- Eventually: email, documents, life admin

---

## Core architecture principle

**The assistant never takes final action without your review.**

Every capture goes through this pipeline before becoming a permanent record:

```
capture → classify/extract → pending inbox → review → confirm → domain record
```

The review inbox is not a temporary MVP shortcut — it is a permanent, first-class part of
the product. You are always in control of what gets stored and acted on.

---

## Build milestones

**First end-to-end milestone (Phases 4–6):**
> I send a Telegram text message → it appears in the dashboard inbox as a classified
> pending item.

Proves the core pipeline exists. No confirmation, no domain records yet.

**MVP release (Phases 4–8):**
> I capture a task via Telegram → review and confirm it → it appears in my tasks view.

The first usable review-first assistant slice. Everything else — finance, food, calendar,
voice — is built on top of this foundation.

---

## Security note

Until Phase 15 (auth/RLS), the backend runs locally and all non-webhook routes require a
`DEV_ADMIN_TOKEN` Bearer token guard. Prefer exposing only the Telegram webhook path via
ngrok; if the full backend is tunneled, the guard still applies to every non-webhook route
that reads or mutates personal data. The webhook validates its own secret.
`SUPABASE_SERVICE_ROLE_KEY` is server-side only and must never reach the frontend or be committed.

---

## Current status

**Phase 0 — Foundation complete.**

The repo structure and all product documentation are in place. No application code, no
database schema, no dependencies have been created yet.

Next step: Phase 1 — scaffold the frontend and backend shells and connect to Supabase.

---

## Repo structure

```
ai_pa/
├── apps/
│   └── web/              # Next.js 15 frontend dashboard (Phase 1+)
├── services/
│   └── api/              # FastAPI Python backend (Phase 1+)
├── docs/                 # Product and architecture documentation
│   ├── product.md        # Vision, principles, domains
│   ├── architecture.md   # System layers and data flow
│   ├── data-model.md     # Conceptual database entities
│   ├── agent-workflow.md # How Claude Code and Codex should work together
│   ├── roadmap.md        # Phase-by-phase build plan
│   ├── mvp-boundary.md   # What is in / out of MVP
│   └── reference-assets.md # Notes on the reference PDFs
├── scripts/              # Utility scripts (Phase 2+)
├── supabase/             # Supabase migrations (Phase 2+)
├── CLAUDE.md             # Durable instructions for Claude Code
├── AGENTS.md             # Durable instructions for Codex
├── .env.example          # Environment variable template
└── README.md             # This file
```

---

## How to use this repo

### Reading order before Phase 1
1. `docs/product.md` — understand the vision and principles
2. `docs/architecture.md` — understand the system layers
3. `docs/data-model.md` — understand the data entities
4. `docs/roadmap.md` — understand what gets built and when
5. `docs/mvp-boundary.md` — understand what is explicitly out of scope

### Agent workflow
- **Claude Code** handles architecture decisions, multi-file implementations, and phase planning
- **Codex** handles focused implementation, code review after Claude phases, and bug fixes
- One phase at a time. Never implement Phase N+1 while Phase N is in progress.
- See `docs/agent-workflow.md` for the full protocol
- See `CLAUDE.md` for Claude Code's standing instructions
- See `AGENTS.md` for Codex's standing instructions

---

## Technology decisions

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Frontend | Next.js 15 + TypeScript + Tailwind | App Router, server components, Vercel-native |
| Backend | FastAPI + Python | Clean async API, great AI SDK support |
| Database | Supabase Postgres | Managed Postgres, free tier, future RLS |
| AI (primary) | Claude (Anthropic) | Best structured output for classification |
| AI (transcription) | OpenAI Whisper | Best voice-to-text, cheap per minute |
| Capture | Telegram bot | Works on any phone, free, webhook-based |
| Frontend deploy | Vercel | Free tier, native Next.js |
| Backend deploy | Render / Railway / Fly | Simple Python hosting |
