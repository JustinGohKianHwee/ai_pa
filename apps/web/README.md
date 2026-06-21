# apps/web — Frontend Dashboard

**Status: Phase 9 ✓ complete — inbox review + tasks + finance views live.**

`/inbox` shows classified pending items with **Confirm / Reject / Edit** controls (Phase 7).
`/tasks` shows confirmed tasks grouped by urgency, with a **Mark complete** action (Phase 8).
`/finance` shows confirmed expenses with totals grouped by currency and category, read-only
(Phase 9). All mutations go through Next.js Server Actions that hold `DEV_ADMIN_TOKEN`
server-side — the browser never sees the token and never calls the backend or Supabase directly.

## Stack
- Next.js 15 (App Router)
- TypeScript (strict mode)
- Tailwind CSS

## Role in the system

The frontend is the review and control layer. Its primary job is to show what the AI has
captured and classified so the user can confirm, edit, or reject each item before it
becomes a permanent record. The inbox is the central screen.

## Directory layout

```
app/
  layout.tsx          — root layout
  page.tsx            — dashboard home (links to /inbox, /tasks, /finance)
  inbox/
    page.tsx          — Server Component: fetches GET /inbox, renders item cards
    InboxCard.tsx     — Client Component: Confirm / Reject / Edit controls
    actions.ts        — Server Actions: confirm / reject / edit (server-only token)
    loading.tsx       — Suspense skeleton shown while fetching
    error.tsx         — error boundary (Client Component)
    types.ts          — TypeScript interfaces matching backend response shape
  tasks/
    page.tsx          — Server Component: fetches GET /tasks, groups by urgency
    TaskList.tsx      — Client Component: urgency groups + Mark-complete action
    actions.ts        — Server Action: complete task (server-only token)
    types.ts          — Task interfaces matching backend response shape
  finance/
    page.tsx          — Server Component: fetches GET /money_events, totals + expenses (read-only)
    types.ts          — MoneyEvent / totals interfaces matching backend response shape
```

## Environment variables

Create `apps/web/.env.local` (git-ignored):

```
# Backend base URL — public, just a URL
NEXT_PUBLIC_API_URL=http://localhost:8000

# Development auth guard — SERVER-SIDE ONLY (no NEXT_PUBLIC_ prefix).
# Must match DEV_ADMIN_TOKEN in services/api/.env.local exactly.
# Temporary guard until Phase 15 (real auth). Never expose to the browser.
DEV_ADMIN_TOKEN=<your-token-here>
```

**`DEV_ADMIN_TOKEN` has no `NEXT_PUBLIC_` prefix** — it is only accessible in Next.js
Server Components and API routes (server-side). It never appears in client JS bundles.

## How to run

```bash
# From repo root:
cd apps/web
npm run dev   # http://localhost:3000
```

Then open http://localhost:3000/inbox (review queue), http://localhost:3000/tasks (confirmed
tasks), or http://localhost:3000/finance (confirmed expenses). If no items appear, send a
Telegram message to @JustinGoh_PABot first and confirm the backend is running on port 8000.

## How to build / typecheck

```bash
cd apps/web
npm run build
```

## Fetch flow (Phase 5)

```
Browser → Next.js server (SSR)
            → GET http://localhost:8000/inbox
              Authorization: Bearer <DEV_ADMIN_TOKEN>   ← server-side only
            ← { items: [...], total: N }
          → renders HTML → Browser
```

`DEV_ADMIN_TOKEN` never leaves the server. The browser only receives rendered HTML.

## What is intentionally not built yet

- Authentication — Phase 15
- Domain module views beyond tasks & finance (food, calendar) — Phases 11–12
- Task editing from the `/tasks` view, finance editing/deletion from `/finance` (edits happen
  in the inbox before confirmation)
- Finance income display and charts — out of scope for Phase 9

## Phase history

- Phase 1: Next.js 15 scaffold, TypeScript strict, Tailwind CSS, placeholder home page
- Phase 5: Dashboard inbox (`/inbox`), `GET /inbox` integration, Server Component fetch
- Phase 6: classification surfaced in the inbox (item type, structured data, confidence)
- Phase 7: Confirm / Reject / Edit controls via Server Actions (`inbox/actions.ts`, `InboxCard.tsx`)
- Phase 8: Tasks view (`/tasks`) — urgency groups, Mark-complete, home link
- Phase 9: Finance view (`/finance`) — recent expenses + totals by currency/category (read-only), home link
