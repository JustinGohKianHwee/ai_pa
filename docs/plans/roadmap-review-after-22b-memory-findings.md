# Roadmap Review Gate — After Phase 22b (Memory-Research Findings)

*A roadmap & architecture review, not an implementation plan. No code, migrations, or app-logic
changes. Basis: `docs/research/llm-memory-architecture.md`. Date: 2026-06-24.*

---

## 0. Scope & method
Phase 22b (Financial Intelligence: monthly explanation + financial-goal progress) is merged. The
LLM memory research report exists. This document reviews whether the **post-22b roadmap is still
correctly sequenced** in light of that report, and recommends a revised order. It deliberately does
**not** design memory, vectors, or the secondary finance-data feature in detail.

Reviewed: `docs/product.md`, `docs/architecture.md`, `docs/data-model.md`,
`docs/research/llm-memory-architecture.md`, `docs/roadmap.md` (Phases 19–28), and the merged code
for `capture_events`, `inbox_items`, `money_events`, portfolio snapshots, `goals`, the monthly
explanation + financial-goal-progress routes, and `agent_runs`. **Finding:** there is no existing
assistant / recommendation / vector / evaluation logic — the AI surface today is only
capture-time classification/transcription/vision; all read layers (timeline, financial summary,
monthly explanation) are **deterministic**. Good — nothing to unwind.

---

## 1. Current roadmap assessment
Current post-22b sequence:

| # | Phase | Verdict |
|---|-------|---------|
| 23 | Notes/journal + lifestyle check-ins | **Keep** — deterministic data foundation |
| 24 | Daily briefing & weekly reflection (summaries engine) | **Keep** — deterministic derived memory; correct pre-memory step |
| 25 | Goal → activity attribution | **Keep but optional / can slip** — structured linking; not a memory prerequisite |
| 26 | Security review & hardening | **Keep, reposition** — must gate embedding + LLM egress, not the whole memory effort |
| 27 | Vector memory (pgvector + `memory_chunks` + embeddings) | **Split** — conflates two phases (see §2/§3) |
| 28 | LLM assistant / recommendations | **Keep last**, gated by security |

**Overall:** the spine is already broadly right (data → summaries → security → memory → assistant).
The **one structural gap** the research exposes: Phase 27 jumps straight from the raw `memory_events`
log to *embeddings*, skipping the **distilled, source-linked `memory_items` layer** that should be
built (deterministically, no vectors) **first**. Embeddings should index that layer, not be the
layer.

---

## 2. Key memory-research findings that affect sequencing
Each finding cites the **report section** it comes from (in `docs/research/llm-memory-architecture.md`)
and the **primary source(s)** that section cites. Full reference list: report §References.

1. **Postgres confirmed-domain records are the source of truth; embeddings are a recall index, not
   a store.** → Build the vector DB last and over distilled records; never canonical.
   *Source: report §Executive Summary (pts 1–2) & §Recommended Architecture; grounded in RAG —
   Lewis et al. 2020 (arXiv:2005.11401) and MemGPT — Packer et al. 2023 (arXiv:2310.08560); pgvector
   + PostgreSQL docs.*
2. **Extract memory only from reviewed/confirmed records.** → Memory is *downstream* of the
   deterministic modules and months of confirmed data, not parallel.
   *Source: report §Safety/Auditability/Source-of-Truth Rules & §Executive Summary (pt 3); aligns
   with Self-RAG retrieve/critique — Asai et al. 2023 (arXiv:2310.11511) and the project's
   review-first invariant.*
3. **Memory needs provenance + lifecycle metadata** (`source_table`, `source_id`, `confidence`,
   `importance`, `valid_from`/`valid_to`, `superseded_by`) → a *deterministic* `memory_items` schema
   that must exist **before** embeddings.
   *Source: report §Database Design; importance/recency ranking from Generative Agents — Park et al.
   2023 (arXiv:2304.03442); bi-temporal validity/supersession from Zep/Graphiti — Rasmussen et al.
   2025 (arXiv:2501.13956).*
4. **Distinguish memory *types* — event / episodic / semantic / procedural / preference / goal.** →
   `memory_items` should carry a `memory_type`; **procedural** memory stays in prompts/code (not a
   writable store).
   *Source: report §Memory Taxonomy; Tulving 1972/1985 (episodic vs semantic); CoALA — Sumers et al.
   2024 (arXiv:2309.02427) and LangMem docs (semantic/episodic/procedural).*
5. **Finance = deterministic query first, LLM explanation second.** → Already true
   (`compute_summary`, `compute_monthly`); the assistant must inherit this and never read numbers
   from vectors.
   *Source: report §Safety/Auditability/Source-of-Truth Rules & §Retrieval Strategy (Q8); attribution
   from Self-RAG — Asai et al. 2023.*
6. **Embeddings/LLM egress is a security + privacy event.** → The security review must land before
   anything sends personal data to an embedding/LLM provider.
   *Source: report §Safety/Auditability/Source-of-Truth Rules ("Privacy & security") & §Implications
   for Roadmap (Phase 26 gate).*
7. **Memory is a set of operations over a *structured* store, and you index summaries — not every
   row.** Extract→consolidate→update/retrieve; ranking by recency×importance×relevance.
   *Source: report §Retrieval Strategy & §Recommended Implementation Direction; Mem0 — Chhikara et al.
   2025 (arXiv:2504.19413, ~90% token/latency savings vs full context) and Generative Agents — Park
   et al. 2023.*
8. **Working memory ≠ stored truth; tiered like an OS** (context window = RAM, Postgres = disk,
   vector = associative recall). → The assistant assembles context at query time from SQL + resolved
   recall; it is not a persistent truth store.
   *Source: report §Recommended Architecture & §Memory Taxonomy; MemGPT — Packer et al. 2023.*
9. **Graph / temporal-KG memory is advanced and optional** for a single user. → Keep flat
   `memory_items` + pgvector; defer KG.
   *Source: report §Open Questions (graph vs flat) & §Do Not Build Yet; HippoRAG — Gutiérrez et al.
   2024 (arXiv:2405.14831) / HippoRAG 2 (arXiv:2502.14802); A-MEM — Xu et al. 2025 (arXiv:2502.12110);
   Zep — Rasmussen et al. 2025.*

Net effect: **insert a deterministic `memory_items` phase (with a `memory_type` taxonomy) before
embeddings, and split today's Phase 27 into items→(security)→index.** Sequencing is otherwise sound.

---

## 3. Recommended revised roadmap (after Phase 22b)

| # | Phase | Type | Note |
|---|-------|------|------|
| 23 | Notes / journal + lifestyle check-ins | deterministic module | unchanged |
| 24 | Daily/weekly summaries engine | deterministic derived | unchanged; first "derived memory", no AI numbers |
| 25 | Goal → activity attribution *(optional; may slip after memory)* | deterministic | not a memory prerequisite |
| **26** | **Memory foundation v1 — `memory_items`** (distilled, **source-linked**, deterministic, **NO embeddings**) | **NEW / split from old 27** | extract only from confirmed records; full provenance + validity + supersession; populated by rule, not by an LLM agent that writes truth |
| **27** | **Security review & hardening** (risk register) | gate | **must precede** any embedding/LLM egress; covers secret storage, RLS blast radius, the embed/egress decision, prompt-injection |
| **28** | **Memory retrieval index — pgvector embeddings over `memory_items` + summaries** | fuzzy index | the old "vector memory", now strictly an index over the items layer; importance scoring lives here |
| **29** | **LLM assistant / recommendations** (retrieval-grounded, deterministic-first finance) | reasoning layer | unchanged in spirit; advisory only, review-first preserved |

*(Optional, near-term, deterministic — see §10: an expense-category / statement-verification phase
can sit at ~23/24 to raise finance-data quality before summaries/memory.)*

Phases 23–25 are the deterministic data foundation; 26 is the deterministic memory layer; 27 is the
safety gate; 28 is the index; 29 is the consumer.

---

## 4. Memory readiness checklist (all must be true before Phase 28 embeddings)
- [ ] Deterministic domain modules stable; **several months** of confirmed data accumulated.
- [ ] `memory_events` log populated across domains (✅ exists since 15b).
- [ ] Summaries engine (Phase 24) producing deterministic daily/weekly rollups.
- [ ] `memory_items` layer (Phase 26) live: every item has `memory_type` (event/episodic/semantic/
      procedural/preference/goal), `source_table`/`source_id`, `confidence`, `importance`,
      `valid_from`/`valid_to`, `superseded_by`.
- [ ] Extraction **excludes** raw `capture_events`, `inbox_items` (pending/needs-manual), and
      rejected items — confirmed records only.
- [ ] No finance number stored as authoritative in memory; deterministic queries remain the sole
      numeric source.
- [ ] Security review (Phase 27) passed; the embedding/LLM **egress** decision explicitly approved.
- [ ] A retrieval-quality **eval** method exists (even small/manual) before trusting recall.
- [ ] Embeddings index built **only** over `memory_items` + summaries — never over raw rows.

---

## 5. Deterministic foundations to complete before memory
1. **Domain coverage** (✅ mostly): tasks, finance, food, exercise, habits, goals, decisions, manual
   financial snapshots, portfolio snapshots.
2. **Summaries engine** (Phase 24) — deterministic rollups are the natural unit to later embed.
3. **`memory_items` distillation** (Phase 26) — the source-linked structured layer.
4. *(Optional)* **Finance data quality** — expense categories + statement verification (§10) make
   finance summaries/memory materially more useful and trustworthy.

Principle: **memory is downstream of deterministic data.** Every memory record must trace to a
confirmed domain row.

---

## 6. Architecture boundaries for future memory (the 4-layer contract)
1. **Postgres deterministic domain tables = source of truth.** Canonical, ACID, reviewed. All
   numbers, statuses, dates, balances are authoritative here.
2. **`memory_items` = distilled, source-linked long-term memory.** Lossy human-readable summaries +
   lifecycle metadata; **never authoritative**; always resolvable to the source row; derived **only**
   from confirmed records; tombstoned via `valid_to`/`superseded_by` (never hard-deleted). Each item
   carries a **`memory_type`** — `event` / `episodic` / `semantic` / `procedural` / `preference` /
   `goal` (report §Memory Taxonomy; Tulving 1972/1985; CoALA — Sumers et al. 2024; LangMem docs).
   **Procedural** memory is *not* a writable store — it lives in prompts/code (CoALA/LangMem);
   **preference** and **goal** are project-specific specializations of semantic memory.
3. **`memory_embeddings` / pgvector = fuzzy retrieval index** over `memory_items` (+ summaries).
   Pointers for associative recall; results are *resolved to the live source row* before use.
4. **LLM = reasoning & explanation layer, not source of truth.** It phrases retrieved/queried facts,
   cites sources, and for finance **only renders deterministically-computed numbers** — it never
   computes or recalls figures from vectors.

How `memory_items` differs from domain tables: domain tables are *write-once-via-review, canonical,
exact*; `memory_items` are *derived, summarized, approximate, expirable, and provenance-tagged*. If
the two ever disagree, the domain row wins.

---

## 7. Phases that should explicitly NOT be built yet
- ❌ pgvector / embeddings / any vector DB (Phase 28 — after items + security).
- ❌ LLM assistant / recommendations (Phase 29).
- ❌ Any autonomous agent that **writes or mutates** domain records (review-first is permanent).
- ❌ Embedding or "memorizing" raw captures, pending, or rejected items.
- ❌ Graph / temporal-KG memory (HippoRAG/Zep-style) — advanced, single-user ROI unproven.
- ❌ Standalone "importance scoring" before retrieval exists (it belongs in Phase 28).
- ❌ Sending personal data to an external embedding/LLM provider before the Phase 27 review.

---

## 8. Risks if memory/vector retrieval is built too early
- **Garbage-in recall:** embedding misclassified/unreviewed data poisons retrieval quality.
- **Finance hallucination:** a vector-retrieved *stale* number presented as current truth — the
  single most damaging failure for this app; deterministic-first finance must be enforced first.
- **Unauditable memory:** without `source_id`/validity, you cannot cite, expire, or supersede facts;
  contradictions accumulate.
- **Privacy/egress before review:** embedding personal data off-host before the security gate.
- **Premature optimization:** building retrieval infrastructure on a few weeks of thin data wastes
  effort and tunes against noise.
- **Vector-as-truth drift:** answering from a blurry approximate copy instead of the exact record.

---

## 9. Concrete next-action recommendation
1. **Do not build memory or vectors next.** Continue the deterministic track.
2. **Apply the resequencing to `docs/roadmap.md`** (separate, approved edit): split old Phase 27 into
   **26 `memory_items` (deterministic)** and **28 vector index**, with **27 security** between memory
   and embeddings; keep 23/24 as the data+summaries foundation; mark 25 attribution optional.
3. **Immediate next phase: Phase 23 (Notes/journal + lifestyle check-ins)** as planned — *unless* you
   judge finance-data quality more pressing, in which case slot the deterministic expense-category /
   statement-verification phase first (§10). Either way, the next phase is **deterministic**, not
   memory.
4. Treat the **memory readiness checklist (§4)** as the gate before Phase 28.

---

## 10. Where expense-category tracking might fit (high-level only)
This is a **deterministic finance-data-quality** improvement, not a memory feature, and it
*strengthens* later finance summaries/memory. Kept review-first, it could be a near-term phase
around 23/24 (before the summaries/memory layers benefit from richer data):
- manual expense **category** tracking + **monthly category summaries** (deterministic);
- **statement import staging** → **match statement rows to `money_events`** → **review-before-confirm**
  (same capture→review→confirm invariant; no auto-confirm).

Recommendation: worth doing **before** memory (better data in → better memory later), but only
promote it to "immediate next phase" if you value finance accuracy over the journal/lifestyle
module. Do not expand it here.

---

## 11. Provenance & traceability matrix (recommendation → report section → primary source)

| Review recommendation | Report section | Primary source(s) |
|---|---|---|
| Postgres = source of truth; vectors = index | Executive Summary; Recommended Architecture | RAG (Lewis 2020, arXiv:2005.11401); pgvector + PostgreSQL docs |
| Build `memory_items` (source-linked, deterministic) **before** embeddings; split Phase 27 | Recommended Architecture; Database Design; Implications for Roadmap | MemGPT (Packer 2023, arXiv:2310.08560); Mem0 (Chhikara 2025, arXiv:2504.19413) |
| Extract only from confirmed records; exclude raw/pending/rejected | Safety/Auditability/Source-of-Truth Rules; Executive Summary | review-first invariant; Self-RAG (Asai 2023, arXiv:2310.11511) |
| Provenance + confidence + importance + validity + supersession on every item | Database Design | Generative Agents (Park 2023, arXiv:2304.03442); Zep/Graphiti bi-temporal (Rasmussen 2025, arXiv:2501.13956) |
| `memory_type` taxonomy (event/episodic/semantic/procedural/preference/goal); procedural stays in prompts/code | Memory Taxonomy | Tulving 1972/1985; CoALA (Sumers 2024, arXiv:2309.02427); LangMem docs |
| Finance deterministic-first; LLM only phrases stored numbers; cite sources | Safety/Source-of-Truth Rules; Retrieval Strategy | Self-RAG (Asai 2023); project `compute_summary`/`compute_monthly` |
| Security review gates embedding/LLM **egress** | Safety ("Privacy & security"); Implications for Roadmap | report Phase-26 gate |
| Index summaries + high-importance items, not every row; recency×importance×relevance ranking | Retrieval Strategy; Recommended Implementation Direction | Mem0 (Chhikara 2025); Generative Agents (Park 2023) |
| Tiered memory (context=RAM, Postgres=disk, vector=recall); working memory ≠ truth | Recommended Architecture | MemGPT (Packer 2023) |
| Defer graph/temporal-KG memory (single-user ROI unproven) | Open Questions; Do Not Build Yet | HippoRAG (Gutiérrez 2024, arXiv:2405.14831 / 2502.14802); A-MEM (Xu 2025, arXiv:2502.12110); Zep (Rasmussen 2025) |

**Honest coverage note (what changed in this revision):** the first draft fully reflected the
report's *architecture/sequencing* conclusions (SoT, items-before-index, provenance, finance-first,
security gate, do-not-build-yet) but under-used the report's **Memory Taxonomy**. This revision adds
the six-type `memory_type` model (finding #4, §6) and the operations/tiering findings (#7, #8) with
citations, so the review now traces to every major section of the report. Full bibliographic detail
lives in `docs/research/llm-memory-architecture.md` §References (not duplicated here).

---

## Summary
- **Files changed:** created/updated `docs/plans/roadmap-review-after-22b-memory-findings.md` (this
  review) — now with per-finding citations (§2), the `memory_type` taxonomy folded into §6, and a
  provenance/traceability matrix (§11). No code, migrations, app logic, or roadmap edits made.
- **Main recommendation:** the roadmap spine is sound, but **insert a deterministic, source-linked
  `memory_items` layer before embeddings and split today's Phase 27 into items→(security)→index**;
  keep memory strictly downstream of confirmed deterministic data, with Postgres as source of truth,
  embeddings as a mere index, and the LLM as a non-authoritative reasoning layer (finance numbers
  always deterministic).
- **Next suggested phase:** **Phase 23 (Notes/journal + lifestyle check-ins)** — deterministic — or,
  if finance accuracy is the priority, the deterministic expense-category / statement-verification
  phase (§10). **Not** memory/vectors.
- **Assumptions:** (1) "memory" means the future long-term layer, not the existing `memory_events`
  log (which already correctly logs confirmations/snapshots only). (2) Single-user scope unchanged.
  (3) Phases 20/21/22b are functionally complete pending the user's manual verification. (4) No
  existing vector/assistant code to migrate. (5) This review only *recommends* roadmap edits; it does
  not modify `docs/roadmap.md` — that's a follow-up to approve.
