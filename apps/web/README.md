# apps/web — Frontend Dashboard

**Status: Phase 15a — Supabase authentication implemented; manual setup pending.**

`/inbox` shows classified pending items with **Confirm / Reject / Edit** controls (Phase 7).
`/tasks` shows confirmed tasks grouped by urgency, with a **Mark complete** action (Phase 8).
`/finance` shows confirmed expenses with totals grouped by currency and category, read-only
(Phase 9). Supabase Auth stores the owner's session in cookies. Server Components and Server
Actions forward the short-lived access token to FastAPI; the browser never receives backend
secrets or calls the service-role database client.

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
  login/page.tsx      — public email/password login
  logout/actions.ts   — server-side sign-out action
  inbox/
    page.tsx          — Server Component: fetches GET /inbox, renders item cards
    InboxCard.tsx     — Client Component: Confirm / Reject / Edit controls
    actions.ts        — Server Actions: confirm / reject / edit (authenticated fetch)
    loading.tsx       — Suspense skeleton shown while fetching
    error.tsx         — error boundary (Client Component)
    types.ts          — TypeScript interfaces matching backend response shape
  tasks/
    page.tsx          — Server Component: fetches GET /tasks, groups by urgency
    TaskList.tsx      — Client Component: urgency groups + Mark-complete action
    actions.ts        — Server Action: complete task (authenticated fetch)
    types.ts          — Task interfaces matching backend response shape
  finance/
    page.tsx          — Server Component: fetches GET /money_events, totals + expenses (read-only)
    types.ts          — MoneyEvent / totals interfaces matching backend response shape
lib/
  api.ts              — server-only authenticated FastAPI fetch helper
  supabase/           — browser, server, and middleware cookie clients
middleware.ts         — refreshes sessions and protects dashboard routes
```

## Environment variables

Create `apps/web/.env.local` (git-ignored):

```
# Backend base URL — public, just a URL
NEXT_PUBLIC_API_URL=http://localhost:8000
# Supabase Auth public configuration. The anon key is safe to expose; RLS denies data access.
NEXT_PUBLIC_SUPABASE_URL=<your-project-url>
NEXT_PUBLIC_SUPABASE_ANON_KEY=<your-anon-key>
```

Never add `SUPABASE_SERVICE_ROLE_KEY` or broker credentials to frontend environment files.

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
Browser → Supabase Auth (email/password; cookie session)
        → Next.js server (SSR)
            → GET http://localhost:8000/inbox
              Authorization: Bearer <Supabase access token>
            ← { items: [...], total: N }
          → renders HTML → Browser
```

Middleware refreshes the cookie session and redirects unauthenticated dashboard requests to
`/login`. A backend 401 also redirects to `/login`. The service-role key and JWT signing secret
never leave FastAPI.

## What is intentionally not built yet

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
- Phase 15a: Supabase email/password login, session-refresh middleware, authenticated backend
  fetches, and logout.
