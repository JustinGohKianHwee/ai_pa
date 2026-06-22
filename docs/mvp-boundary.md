# MVP Boundary

This document defines what is in the MVP, what is explicitly out of scope, and what
would count as overengineering. Read this before adding any feature.

---

## First end-to-end milestone (Phases 4–6)

> I send a Telegram text message → it appears in the dashboard inbox as a classified
> pending item.

This milestone proves the core pipeline exists and works. Nothing more.

```
Telegram message
  → FastAPI webhook receives it
  → capture_event written to Supabase
  → OpenAI classifies it
  → inbox_item written with review_status = pending
  → dashboard shows it
```

| Feature | Phase |
|---------|-------|
| Telegram text message capture | 4 |
| Dashboard review inbox | 5 |
| AI classification (OpenAI `gpt-4o-mini`) | 6 |

The first milestone does **not** include confirmation, domain records, or any module
views. Once this loop works, every subsequent feature is built on top of it.

---

## MVP release (Phases 4–8)

> I capture a task via Telegram → it appears classified in my inbox → I review and
> confirm it → it appears in my tasks view.

The first usable review-first assistant slice. Proves the full review-to-domain-record
loop works end-to-end.

| Feature | Phase |
|---------|-------|
| Telegram text message capture | 4 |
| Dashboard review inbox | 5 |
| AI classification (OpenAI `gpt-4o-mini`) | 6 |
| Confirm / reject inbox items | 7 |
| Tasks module | 8 |

The MVP release does **not** include finance, food, calendar, voice, or any other domain
module. Five phases. The end result: I can send a Telegram message, see it classified
in my inbox, and confirm it as a task.

---

## What is intentionally deferred

These features are valid long-term goals. They are not in the MVP.

| Feature | Why deferred |
|---------|-------------|
| Voice transcription (Whisper) | Adds complexity before the text loop is proven |
| Finance module | Requires money_events schema and review UX |
| Food logs | Requires food_logs schema |
| Calendar intents | Requires calendar_intents schema + careful UX |
| Read-only Tiger/IBKR portfolio | Requires broker API credentials, adapter normalization, and careful handling of currencies and data freshness |
| Daily portfolio snapshots | Requires verified broker adapters, transactional normalized persistence, portfolio-day idempotency, scheduler/retry behavior, and broker-session availability handling |
| Journal entries | Requires journal table or notes schema |
| Daily / weekly review | Requires sufficient data to aggregate |
| Vector memory / semantic search | Only useful with months of data |
| Deployment (Vercel + Render) | Local development is sufficient until Phase 15+ |
| Google Calendar sync | Requires OAuth, conflict detection, irreversible action UX |
| Morning briefing (Telegram push) | Requires cron jobs and stable production |
| Email capture | New capture surface, separate integration |
| iOS Shortcuts | Alternative capture surface, not needed yet |
| Multi-user support | This is a single-user personal tool |
| Demo mode | Not needed for personal use |
| Habit tracking | A distinct domain module, not MVP |
| Goal tracking | A distinct domain module, not MVP |

---

## What should not be built

These are things that might seem useful but would actively harm the project at this stage.

**Authentication before the loop works.**
Auth was intentionally deferred until the review-first loop was proven. Phase 15a now adds
single-owner authentication without introducing multi-user ownership or changing the loop.

**Exposing the full backend without authentication.**
The backend holds a Supabase service-role key with write access to all personal data.
All non-webhook protected routes require a valid Supabase JWT whose subject matches the
configured owner. Tunneling does not bypass this check. The Telegram webhook validates its
own secret, RLS denies direct anon/authenticated access, and the frontend never receives the
JWT signing secret or `SUPABASE_SERVICE_ROLE_KEY`.

**Multi-user support.**
This tool is built for one person. Every design decision should assume a single user.
Generalising to multi-user means data isolation, per-user AI quotas, billing, and support.
That is a product pivot, not a feature addition.

**Production deployment before local works reliably.**
Deploying to Vercel and Render before the local loop is solid means debugging production
issues on top of local issues. Prove the loop locally first.

**AI calls on page load.**
Loading the dashboard must never trigger an AI call. AI runs once, when a capture is
received. The dashboard reads from Supabase — it does not call Claude or OpenAI.

**"Auto-confirm" shortcuts.**
Any feature that bypasses the inbox review (e.g. "high-confidence items are automatically
confirmed") violates the core product principle. The review layer is permanent.

**Broad abstractions before the first use case exists.**
Do not build a generic "domain module framework" or a plugin system before you have two
domain modules working. Write the second module when you build it, then extract the
common pattern.

**Premature optimisation.**
Indexes beyond primary keys, caching layers, rate limiting, connection pooling — none of
these are needed until the system is in production with real load. Build them in Phase 16+.

---

## What counts as overengineering

You are overengineering if you are:

- Adding configuration for something that does not need to vary yet
- Writing an abstraction layer before there are two concrete uses for it
- Adding error handling for errors that cannot happen yet
- Building a feature to handle a problem you do not have
- Implementing a future phase alongside the current phase
- Adding auth before the loop works
- Adding cron jobs before the backend is stable
- Building a component library before you have three components
- Designing for scale before you have any users (including yourself using it daily)

A good test: can you explain why this specific line of code is needed for the current
phase's definition of done? If not, it should not be in this phase.

---

## The constraint that matters most

The review layer must exist in every phase from Phase 7 onwards. No shortcut, no
"for now" bypass, no "we'll add it back later."

The pipeline once a domain module exists is:
```
capture → classify/extract → pending inbox → review → atomic confirm + domain record
```

If any phase removes or bypasses the `pending inbox → review` step, that phase is wrong.
In Phase 7, before any domain module exists, confirmation atomically records
`review_status = confirmed` and `reviewed_at` only. Phase 8 is the first phase where a
newly confirmed task-type inbox_item creates exactly one linked task record in that same
transaction. Items confirmed before Phase 8 remain inbox records only; backfill is optional
future/admin work and is not required for the MVP release.

---

## Capture durability is non-negotiable

A `capture_event` must be written before any AI call is made. If the AI call fails for
any reason — timeout, malformed response, API error — the capture must still be visible
in the dashboard inbox with `item_type = unknown`,
`review_status = needs_manual_classification`, and `processing_status` set to
`classification_failed` or `invalid_ai_output`. It cannot be confirmed until the user
manually supplies a valid item type and structured data and returns it to pending review.

There is no acceptable scenario where a user sends a Telegram message and nothing appears.
