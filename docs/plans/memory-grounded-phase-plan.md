# Memory-Grounded Forward Plan — Phases 23–29

*Forward phase planning that operationalizes `docs/research/llm-memory-architecture.md` and the
post-22b review (`docs/plans/roadmap-review-after-22b-memory-findings.md`). **Planning only** — no
code, no migrations, no app-logic changes. Schema/endpoint blocks are illustrative sketches for
*future* phases, explicitly **not** to be built now. Date: 2026-06-24.*

---

## Target architecture (the contract every phase below respects)
1. **Postgres deterministic domain tables = source of truth** (canonical, ACID, reviewed).
2. **`memory_items` = distilled, source-linked long-term memory** (typed, lossy, expirable, never
   authoritative; resolves to the source row).
3. **`memory_embeddings` / pgvector = fuzzy retrieval index** over `memory_items` (+ summaries).
4. **LLM = reasoning/explanation layer** — phrases retrieved/computed facts, cites sources, and for
   finance only renders deterministically-computed numbers.

Revised, memory-grounded sequence (from the review): **23** deterministic modules → **24** summaries
→ **25** attribution *(optional)* → **26** `memory_items` (deterministic) → **27** security gate →
**28** vector index → **29** assistant. Each must clear the **readiness gate** of the prior one.

---

## Phase 23 — Notes / journal + lifestyle check-ins  *(deterministic; unchanged)*
- **Goal:** capture→confirm free-form notes/journal + an optional structured daily check-in
  (energy/mood/sleep/stress/activity). Reflective log, **not** medical/diagnostic.
- **Why now (memory):** adds episodic/semantic *source material* (journal = episodic; preferences in
  notes = semantic) that later `memory_items` distill. *(Report §Memory Taxonomy.)*
- **Scope:** standard domain module(s) + `memory_events` write; searchable list; no analytics.
- **Out of scope:** correlation/insights, AI summaries, any memory extraction.

## Phase 24 — Daily/weekly summaries engine  *(deterministic derived memory; unchanged)*
- **Goal:** deterministic daily/weekly rollups from confirmed records + `memory_events` (+ the
  finance summaries already built). Surface on dashboard/review.
- **Why now (memory):** summaries are the **natural unit to embed later** and the first "derived
  memory" — built deterministically, no AI numbers. *(Report §Recommended Implementation Direction:
  "embed summaries + high-importance events, not every row"; Mem0 consolidation.)*
- **Scope:** a `daily_summaries` table populated by deterministic aggregation; optional **tiny**
  AI *phrasing* only if strictly grounded in the computed rollup (default: deterministic text).
- **Out of scope:** embeddings, recommendations, cross-currency finance totals.

## Phase 22c — Expense categories & monthly category summaries  *(NEXT; deterministic, migration-free)*
- **Goal:** surface confirmed expenses **by category, by month**, per currency — a deterministic
  finance-data-quality slice that strengthens later summaries/memory.
- **Why now (memory):** richer, categorized finance data → better deterministic summaries (Phase 24)
  and better finance `memory_items` later (review §10; "memory is downstream of good deterministic
  data").
- **Scope (migration-free):** reuse the existing `money_events.category` (set by the classifier,
  edited in the inbox before confirm — **no post-confirm mutation, no new schema**). Add
  `GET /financial_intelligence/category-summary` → current local month (USER_TIMEZONE + `created_at`
  windows, mirroring 22a/22b-1), confirmed **expense** rows grouped **by currency → category** with
  totals; a "This month by category" section on `/finance`/`/financial-intelligence`. Decimal sums.
- **Hard rules:** by currency, **never cross-currency summed**; **logged/confirmed expenses only**;
  no AI numbers, no advice; no re-categorization of confirmed records (immutable).
- **Out of scope:** statement import/matching (→ 22d), category editing post-confirm, budgets,
  AI categorization.

## Phase 22d — Statement import & verification  *(deferred, planned — NOT built)*
- **High-level only:** bank/card **statement import → staging table → match staged rows to
  `money_events` → review-before-confirm** (no auto-confirm, no auto-categorize). Substantial build
  (CSV/PDF parsing + fuzzy matching + staging/review UX); sequence after 22c if finance accuracy
  remains the priority. **Not** a memory prerequisite. No implementation plan yet.

## Phase 25 — Goal → activity attribution  *(deterministic; optional / may slip)*
- **Goal:** explicit, structured links from records/metrics to goals; dashboard progress.
- **Memory note:** **not** a memory prerequisite; can slip to after 26 without blocking the memory
  track. Keep links explicit and deterministic; broad attribution stays out (it is *not* the
  memory-graph). *(Report §Do Not Build Yet: no broad attribution engine.)*

---

## Phase 26 — Memory foundation v1: `memory_items` (deterministic, source-linked, **NO embeddings**)
**The new layer the review inserted.** This is the heart of the memory work and is deliberately
**embedding-free and egress-free**, so it needs no security gate and carries zero LLM-hallucination
risk.

- **Goal:** distill confirmed records + `memory_events` + summaries into a typed, source-linked,
  lifecycle-tracked `memory_items` table that is queryable deterministically and ready to be indexed
  later.
- **Relationship to `memory_events`:** `memory_events` (15b) is the raw append-only *event log*
  (one row per confirmation/snapshot). `memory_items` is the *curated* layer above it — typed,
  deduplicated/consolidated, validity-tracked facts. Events are the input; items are the distilled
  output.
- **Extraction = deterministic/templated, not an LLM writing truth (v1).** Build items by rule from
  `memory_events.payload_json` + domain rows + summaries (e.g. a confirmed decision → one `semantic`
  preference item; a confirmed goal → one `goal` item; a weekly summary → one `episodic` item).
  *No LLM distillation in v1* — that keeps it deterministic and defers any egress to Phase 27.
  *(Report §Safety/Source-of-Truth: extract only from confirmed records; deterministic-first.)*
- **Illustrative schema (FUTURE — do not build now):**
  ```sql
  -- Phase 26 sketch only. memory_type per the report's taxonomy.
  memory_items(
    id uuid pk, owner_id text not null,
    memory_type text check (memory_type in
      ('event','episodic','semantic','procedural','preference','goal')),
    content text not null,                 -- human-readable distilled statement
    source_table text not null, source_id uuid,   -- provenance → resolve to live row
    confidence numeric, importance int,            -- ranking inputs (Generative Agents)
    valid_from timestamptz not null default now(), valid_to timestamptz,  -- bi-temporal (Zep)
    superseded_by uuid references memory_items(id),
    created_at timestamptz not null default now()
  )  -- RLS deny-by-default; service-role only. NO embedding column yet.
  ```
  *(Provenance + validity from report §Database Design; Zep bi-temporal; Generative Agents ranking.)*
- **Operations (deterministic):** *extract* (rule-based from confirmed sources), *consolidate*
  (collapse duplicate semantic facts), *supersede* (set `valid_to` + `superseded_by` when a newer
  confirmed record contradicts). Procedural memory is **excluded** — it lives in prompts/code.
  *(Mem0 operations; CoALA/LangMem procedural-in-prompt.)*
- **Endpoints:** read-only `GET /memory_items` (filter by type/validity) + a dashboard "Memory"
  read view. **No write API** beyond the deterministic backend extractor; **no embeddings**.
- **Out of scope:** any embedding/vector; LLM distillation; autonomous writes; graph/KG.
- **Readiness gate to enter:** Phases 23–24 done; months of confirmed data; `memory_events`
  populated across domains.

## Phase 27 — Security review & hardening (the egress gate)
- **Goal:** a living `docs/security.md` risk register (severity × likelihood + mitigation + owner)
  **before** any personal data leaves the host for embeddings/LLM.
- **Must cover (at least):** auth/session integrity; RLS + service-role blast radius; secret storage
  (Render/Supabase/Vercel) + 2FA; the Tiger-key-local decision; public endpoints + rate limiting;
  dependency/supply-chain; backups/recovery; **prompt-injection** in the future AI layer; **PII /
  embedding-egress decision** (which provider, what data, retention). *(Report §Safety; review §7
  egress gate.)*
- **Definition of done:** all High items fixed; an explicit, written **approval** of what may be
  embedded and which provider may receive it.
- **Out of scope:** building embeddings/assistant (those follow this gate).

## Phase 28 — Memory retrieval index: pgvector embeddings over `memory_items` + summaries
- **Goal:** add a fuzzy associative-recall index on top of the deterministic `memory_items`.
- **Illustrative schema/index (FUTURE):** `memory_embeddings(memory_item_id fk, embedding vector,
  model text, created_at)` (or an `embedding` column on `memory_items`); **HNSW** cosine index;
  RLS. Embed **summaries + high-importance items only**, never raw rows. *(pgvector docs; report
  §Recommended Implementation Direction.)*
- **Retrieval (hybrid):**
  - **Deterministic SQL first** for facts/numbers (finance, counts, dates) — never the vector.
  - **ANN recall** for fuzzy/semantic queries; rank by **recency × importance × relevance**
    (Generative Agents); filter `valid_to`-expired/superseded; **resolve hits to the live source
    row** before use.
  - **Adaptive + attributed** (Self-RAG): retrieve only when needed; attach `source_table/source_id`
    citations to every claim.
- **`POST /memory/search`** + a dashboard search bar. **Importance scoring** (deferred feature 8)
  is implemented here, where retrieval makes it meaningful.
- **Eval:** a small/manual **retrieval-quality eval** before trusting recall (report §Open Questions).
- **Out of scope:** the assistant; autonomous actions; embedding unreviewed data; graph memory.
- **Readiness gate to enter:** Phase 26 items exist with provenance/validity; Phase 27 passed;
  egress approved; eval method defined.

## Phase 29 — LLM assistant / recommendations (retrieval-grounded; the payoff)
- **Goal:** a retrieval-grounded assistant that answers questions across months of data and offers
  recommendations — **advisory only**, review-first preserved.
- **Architecture:** MemGPT-style context assembly — working memory built at query time from (a)
  deterministic SQL results and (b) resolved recall hits; the LLM phrases + cites. *(MemGPT;
  Self-RAG attribution.)*
- **Hard rules:** **finance numbers always come from deterministic queries**, never the LLM or
  vectors; any action (task/calendar/finance/etc.) is a **proposal** routed through the existing
  inbox→review→confirm pipeline — the assistant never writes a domain record directly.
- **Out of scope:** autonomous execution; trading; fine-tuning on personal data; the assistant
  mutating memory or domain tables.
- **Readiness gate to enter:** Phase 28 retrieval works + evaluated; Phase 27 controls in place.

---

## Cross-cutting readiness gates (advance only when true)
- **Enter 26 (`memory_items`):** 23–24 done; multi-month confirmed data; `memory_events` flowing.
- **Enter 28 (embeddings):** 26 live (typed, source-linked, validity); **27 passed + egress
  approved**; eval method exists; index only summaries/high-importance items.
- **Enter 29 (assistant):** 28 retrieval evaluated; deterministic-first finance enforced; all
  actions review-gated.

## Consolidated "Do Not Build Yet" (until the gates above)
- ❌ Embeddings/pgvector before `memory_items` + security (→ 28, after 26+27).
- ❌ LLM assistant/recommendations (→ 29).
- ❌ LLM-written "truth" or any autonomous domain/memory writes.
- ❌ Embedding raw captures / pending / rejected items.
- ❌ Graph / temporal-KG memory (HippoRAG/Zep-style) — single-user ROI unproven.
- ❌ Standalone importance scoring before retrieval exists (lives in 28).
- ❌ Sending personal data to an embedding/LLM provider before the Phase 27 approval.

## Open questions to resolve per phase
- **26:** which confirmed sources map to which `memory_type`; consolidation/dedup rules; whether
  any LLM distillation is allowed later (post-27) vs deterministic-only forever.
- **27:** embedding provider + on-host vs hosted; retention; redaction of PII before embedding.
- **28:** embedding model/dimension/cost; reflection/consolidation cadence; importance heuristic;
  eval metric for a single user.
- **29:** recommendation guardrails; how proposals enter the inbox; multi-currency phrasing.

---

## Summary
- **Files changed:** created `docs/plans/memory-grounded-phase-plan.md` (this forward plan). No code,
  migrations, app logic, or `docs/roadmap.md` edits.
- **Main outcome:** detailed, citation-grounded phase definitions for **23–29**, with the new
  **Phase 26 `memory_items`** (deterministic, embedding-free) as the linchpin, **27 security** as the
  egress gate, **28** as the pgvector index over items/summaries, and **29** as the retrieval-grounded
  assistant — each with explicit readiness gates and out-of-scope lists.
- **Next suggested phase:** **Phase 23** (deterministic) — or the optional finance-data-quality phase
  if accuracy is the priority. Memory work (26+) stays gated behind the deterministic foundations.
- **Assumptions:** (1) the review's resequencing is accepted (split old 27 → 26 items / 28 index, 27
  security between). (2) `memory_items` v1 extraction is deterministic/templated (no LLM), deferring
  egress to post-27. (3) Single-user scope; review-first invariant permanent. (4) Schema blocks are
  *future sketches*, not approved migrations. (5) `docs/roadmap.md` is unchanged pending your approval
  to fold this in.
