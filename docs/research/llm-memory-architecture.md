# LLM Memory Architecture Research Report

*Research-backed design guidance for the long-term memory layer of this single-user AI Personal OS.
Prepared as a planning document — it changes no code. Last updated 2026-06-24.*

---

## Executive Summary

This project's defining strength is its **review-first pipeline**: every capture flows through
`capture → classify/extract → pending inbox → explicit user review → atomic confirm → deterministic
domain record`. The future "LLM memory" layer must be built *on top of* that invariant, not around
it.

The central thesis, supported by the literature below, is:

1. **Postgres confirmed-domain records are the source of truth.** Tasks, money events, food logs,
   exercise, habits, goals, decisions, manual financial snapshots, and the append-only
   `memory_events` log are canonical. They are ACID, queryable, and human-reviewed.
2. **Embeddings are a recall index, not a store of truth.** Retrieval-Augmented Generation (RAG)
   uses retrieval to *ground* generation; the vector index is a lossy, approximate pointer back to
   real records — never the authority.
3. **Memory is extracted only from reviewed/confirmed records.** Unreviewed captures can be
   misclassified; embedding them would propagate errors into recall.
4. **Every memory carries provenance and lifecycle metadata** — `source_table`, `source_id`,
   `confidence`, `importance`, a validity window (`valid_from`/`valid_to`), and supersession
   (`superseded_by`) — so the system can cite sources, expire stale facts, and resolve
   contradictions deterministically.
5. **Finance is computed first, explained second.** Numbers come from deterministic SQL
   (already true in Phases 22a/22b-1); the LLM only phrases stored figures and must never invent
   them.
6. **Memory is separated by type** — event, episodic, semantic, procedural, preference, and goal —
   mirroring cognitive-science and language-agent taxonomies (Tulving; CoALA; LangMem).

All six project-specific conclusions under evaluation are **endorsed** with the citations in this
report. Vector memory itself remains **deferred** until the deterministic modules are stable and
months of real confirmed data exist (see *Do Not Build Yet*).

---

## Current Project Context

The system already contains most of the substrate a memory layer needs:

- **Deterministic domain tables** (the system of record): `tasks`, `money_events`, `food_logs`,
  `calendar_intents`, `exercise_logs`, `habits`, `goals`, `decisions`,
  `manual_financial_snapshots`, plus `portfolio_snapshots*`.
- **`memory_events`** (Phase 15b): an append-only log written *inside the same transaction* as each
  confirmation/snapshot, with `domain`, `event_type`, `payload_json`, `source_table`, `source_id`,
  `occurred_at`. This is already an event-memory stream with provenance.
- **Deterministic read layers**: the Daily Life Timeline (Phase 19) projects `memory_events`;
  `compute_summary` (Phase 22a) and `compute_monthly` (Phase 22b-1) compute financial metrics in
  Python/SQL with no AI-generated numbers. This already embodies "database math first, language
  second."
- **RLS + single-owner** model; service-role backend; no embeddings, no vector DB yet.

In short: the project is well-positioned to add a memory layer as a *derived index* over confirmed
records, and poorly served by any design that lets an LLM treat fuzzy recall as truth.

---

## Research Foundations

**Human memory (cognitive science).** Tulving distinguished **episodic memory** (specific,
time-stamped, autobiographical events) from **semantic memory** (general facts and knowledge), and
the field adds **procedural memory** (skills/how-to) ([Tulving 1972][tulving72]; [Tulving
1985][tulving85]). This tripartite split is the basis for every modern agent-memory taxonomy.

**Retrieval-Augmented Generation (RAG).** [Lewis et al. (2020)][rag] combine a parametric LLM with
a non-parametric retrieval store so generation is *grounded* in retrieved documents, improving
factual accuracy and reducing hallucination. The key lesson for us: the retrieval store exists to
ground the model in real records — it is an index over truth, not the truth.

**Self-RAG.** [Asai et al. (2023)][selfrag] add *adaptive* retrieval (retrieve only when needed) and
*self-critique* ("reflection tokens") plus citation/attribution. Lesson: retrieve on demand and
attribute outputs to sources — both directly applicable to a personal assistant answering
questions over personal data.

**MemGPT / Letta.** [Packer et al. (2023)][memgpt] frame the LLM like an operating system: a small
in-context window (RAM) backed by a large external store (disk), with paging between tiers. Lesson:
the context window is working memory; Postgres is long-term storage; retrieval is the paging
mechanism.

**Generative Agents.** [Park et al. (2023)][genagents] introduce a **memory stream** and retrieve
memories by a score combining **recency × importance × relevance**, plus **reflection** (periodically
synthesizing higher-level memories from raw observations). Lesson: not all memories are equal —
rank by importance and recency, and derive higher-level semantic memories from raw events.

**Reflexion.** [Shinn et al. (2023)][reflexion] store verbal self-reflections in an **episodic
memory buffer** to improve later attempts, without weight updates. Lesson: episodic reflections are
a legitimate, lightweight memory type — but in our system they would still be derived from
confirmed records and remain advisory.

**Cognitive Architectures for Language Agents (CoALA).** [Sumers et al. (2024, TMLR)][coala]
propose modular agent memory — **working / episodic / semantic / procedural** — with a structured
action space separating internal (memory read/write, reasoning) from external (tools) actions. This
is the cleanest academic grounding for the project's memory taxonomy.

**Survey of agent memory.** [Zhang et al. (2024)][survey] organize memory mechanisms by
**representation, source, and operation**, and contrast short-term/working memory with long-term,
and textual vs parametric vs **structured** (tables/triples/graphs) storage. Useful map of the
design space.

**Memory systems with structure/graphs.** [HippoRAG][hipporag] (NeurIPS 2024) and its successor
["From RAG to Memory" / HippoRAG 2][hipporag2] (ICML 2025) combine an LLM with a knowledge graph and
Personalized PageRank (hippocampal indexing) for multi-hop associative recall. [Zep / Graphiti][zep]
(2025) build a **bi-temporal** knowledge graph for agent memory — every fact has an event time *and*
an ingestion time, and edges carry validity intervals so superseded facts are invalidated rather
than deleted; Zep reports beating MemGPT on the Deep Memory Retrieval benchmark. [A-MEM][amem]
(2025) dynamically links memory "notes" Zettelkasten-style. [Mem0][mem0] (2025) defines explicit
memory **operations** — extract → consolidate → update/retrieve — and reports ~90% token/latency
savings versus stuffing full context.

**Operational frameworks / databases.** [LangMem / LangGraph memory][langmem-docs] codify
**semantic / episodic / procedural** memory with managers that extract, update, and consolidate, and
pluggable Postgres/vector backends ([LangMem conceptual guide][langmem-concepts]). [pgvector][pgvector]
adds a `vector` type and HNSW/IVFFlat approximate-nearest-neighbour indexes *inside Postgres*;
[Supabase][supabase-ai] documents pgvector-in-Postgres; [Postgres][postgres] provides the ACID/SQL
guarantees that make it a credible source of truth.

The strong convergence across these works: **structured/long-term memory belongs in a durable store
with provenance and temporal validity; embeddings/graphs are retrieval indexes over it; and
generation must be grounded in and attributed to that store.**

---

## Memory Taxonomy

Mapping Tulving / CoALA / LangMem onto this project (answering **Q1** and **Q5**):

| Type | Definition (here) | Source in this app | Representation |
|------|-------------------|--------------------|----------------|
| **Event** | Raw "this happened / was confirmed" log entries | `memory_events` (already exists) | Relational rows (canonical) |
| **Episodic** | Time-bound personal experiences & reflections ("the month I started BTO planning") | Derived from `memory_events` + domain rows over a window | Relational + (later) embedded summary |
| **Semantic** | Durable facts about the user's world ("CSPX is my main ETF", "BTO with partner") | Derived from confirmed records / explicit notes | Relational fact rows + (later) embedding |
| **Procedural** | How-to / rules / workflows the assistant follows | Prompts, code, and reviewed rule notes | Prompt + code (per CoALA/LangMem) — **not** free-write memory |
| **Preference** | Stable likes/constraints ("prefers term over whole life", "no investment advice") | Confirmed decisions/notes flagged as preferences | Relational fact rows (a semantic subtype) |
| **Goal** | Targets + status (financial and otherwise) | `goals` (+ Phase 22b-2 numeric targets) | Relational rows (canonical) |

Notes:
- **Working memory** (the live context window) is ephemeral per request — it is *assembled* from the
  above at query time (MemGPT/CoALA), never persisted as truth.
- **Preference** and **goal** are project-specific specializations of semantic memory; keeping them
  as distinct, queryable categories makes retrieval and safety rules (e.g. "never contradict a
  stated preference") explicit.
- **Procedural memory stays in prompts/code**, consistent with LangMem and CoALA — the assistant
  does not get an open-ended writable "skills" store in this project.

---

## Recommended Architecture

A two-layer design (answering **Q2, Q3, Q4**):

**Layer 1 — Canonical relational records (system of record).** The existing domain tables +
`memory_events`. ACID, reviewed, deterministically queryable. *All truth lives here.* This is where
counts, sums, dates, balances, statuses, and provenance are authoritative.

**Layer 2 — Derived retrieval index (recall, future).** A `memory_chunks` table (text + embedding +
metadata) built **only** from confirmed Layer-1 records. It exists to answer fuzzy/semantic queries
("what did I decide about insurance?") by retrieving pointers back to Layer-1 rows — never to store
new facts. This mirrors MemGPT's tiering (context = RAM, Postgres = disk, vector index = associative
recall) and RAG's grounding principle.

Why Postgres stays the source of truth (**Q3**): it is transactional and consistent; it already
holds the reviewed records; deterministic SQL gives exact answers (essential for finance); and it
provides referential integrity so memories can link to and be invalidated against their sources.
Embeddings are approximate nearest-neighbour lookups — lossy by construction — so treating them as
canonical would mean answering from a blurry copy instead of the original (**Q4**).

The memory **operations** (Mem0/LangMem) — *extract, consolidate, update, retrieve* — all run as
backend jobs over **confirmed** records, and any write that would create a *new* user-facing domain
record still goes through the review pipeline. Memory derivation never bypasses review.

---

## Database Design

Proposed **future** schema (not to be built yet — see *Do Not Build Yet*). Answers **Q5, Q6, Q7**.

```sql
-- FUTURE (Phase 23+). Derived recall index over CONFIRMED records only.
create table memory_chunks (
    id            uuid primary key default gen_random_uuid(),
    owner_id      text not null,
    memory_type   text not null               -- event|episodic|semantic|procedural|preference|goal
        check (memory_type in ('event','episodic','semantic','procedural','preference','goal')),
    content       text not null,              -- human-readable statement (the embeddable text)
    embedding     vector(1536),               -- pgvector; model-specific dimension
    -- provenance (Q6): every chunk points back to a real record
    source_table  text not null,
    source_id     uuid,
    -- ranking (Generative Agents): importance + recency feed retrieval scoring
    confidence    numeric check (confidence is null or (confidence between 0 and 1)),
    importance    int     check (importance is null or (importance between 1 and 10)),
    -- lifecycle / temporal validity (Zep bi-temporal; Q7)
    valid_from    timestamptz not null default now(),
    valid_to      timestamptz,                -- null = currently valid
    superseded_by uuid references memory_chunks(id),
    created_at    timestamptz not null default now()
);
create index on memory_chunks using hnsw (embedding vector_cosine_ops);  -- pgvector ANN
create index on memory_chunks (owner_id, memory_type);
create index on memory_chunks (source_table, source_id);
-- RLS deny-by-default, service-role only (matches every other table in this project).
```

- **Linking back to sources (Q6):** `source_table` + `source_id` make every chunk a pointer to a
  canonical row. Retrieval results are *resolved* to the live record before anything is shown or
  used, so the answer always reflects current truth (e.g. a goal's current status, not the status
  at embedding time).
- **Stale / contradicted / superseded (Q7):** never hard-delete. Set `valid_to` when a fact stops
  being true and link `superseded_by` to the replacing chunk (Zep's bi-temporal invalidation).
  Retrieval filters `valid_to is null`. Because chunks are derived, the cleanest refresh is often to
  re-derive from the current Layer-1 record rather than mutate in place.
- **pgvector** keeps this inside Postgres — one database, one backup, one RLS model — rather than a
  separate vector service.

---

## Retrieval Strategy

A **hybrid** strategy (answering **Q9** and **Q8**):

1. **Deterministic SQL first** for anything factual or numeric: balances, savings rate, counts,
   due dates, "what's on today". These are exact queries over Layer-1 (already implemented for
   finance via `compute_summary`/`compute_monthly`). The LLM never computes these.
2. **Semantic ANN recall** over `memory_chunks` for fuzzy/associative questions ("why did I pick
   term insurance?", "what was different the month I overspent?"). Rank candidates by
   **recency × importance × relevance** (Generative Agents), filter out `valid_to`-expired and
   superseded chunks, then resolve to the live source rows.
3. **Adaptive + attributed** (Self-RAG): retrieve only when the query needs it, and attach the
   `source_table`/`source_id` citations to whatever the LLM says, so every claim is traceable.
4. **Assemble working memory** (MemGPT/CoALA): the request-time context is built from (a) the
   deterministic query results and (b) the resolved recall hits — then the LLM phrases an answer.

**Day-planning example:** SQL pulls today's tasks (by due/urgency), calendar intents, pending inbox,
and the latest financial summary; semantic recall surfaces relevant standing preferences/decisions
("prefers deep-work mornings"); the LLM composes a briefing grounded in those, citing sources, and
proposes — never auto-executes — actions.

**Finance guardrail (Q8):** every number in an answer must originate from a deterministic query.
The LLM receives the computed figures and only renders/explains them; it is prompted that it may not
introduce or recompute numbers. This is the same "logged/deterministic first" rule already enforced
in 22a/22b-1, extended to the assistant.

---

## Safety, Auditability, and Source-of-Truth Rules

- **Extraction only from `review_status = 'confirmed'` records.** Unreviewed captures are never
  embedded or memorized; this preserves the review-first invariant end-to-end.
- **No autonomous truth writes.** Memory derivation produces *indexes/summaries*, not new domain
  records. Anything that would become a user-facing record still passes through the inbox.
- **Provenance on every memory.** `source_table` + `source_id` (+ `confidence`) make all recall
  auditable and citable; nothing is asserted without a traceable origin.
- **Temporal validity & supersession.** `valid_from`/`valid_to`/`superseded_by` resolve
  contradictions deterministically and prevent stale facts from resurfacing (Zep bi-temporal).
- **Finance: deterministic-first, explanation-second.** SQL computes; the LLM phrases. No invented
  or LLM-recomputed numbers; cross-currency totals remain forbidden without an approved FX source
  (consistent with Phases 9/14.5/22a).
- **Embeddings are never authoritative.** A retrieval hit is a pointer; the live Layer-1 row is the
  answer. If they disagree, the row wins.
- **Privacy & security.** `memory_chunks` is RLS-locked, service-role-only, single-owner — like
  every other table. Sending personal memory to an embedding/LLM provider is a data-egress decision
  that belongs to the Phase 26 security review.

---

## Implications for Roadmap

- The existing **`memory_events`** log is the correct substrate; keep writing it from every
  confirmation (already happening).
- **Phase 23 (Vector memory)** is where `memory_chunks` + pgvector + `POST /memory/search` belong —
  built on accumulated, confirmed data, embedding **summaries + high-importance events**, not every
  row.
- **Phase 26 (Security review)** must gate embedding personal data and any LLM/provider egress
  before the assistant ships.
- **Phases 27–28 (Assistant/recommendations)** consume this layer read-only and advisory; all
  actions still flow through review.
- Nothing here requires reworking 22a/22b — they already implement the deterministic-first pattern
  the assistant will reuse.

---

## Open Questions

1. **Embedding model** (provider, dimension, cost, and whether personal data may leave the host) —
   a Phase 26 decision.
2. **Reflection cadence** — when/how often to synthesize episodic/semantic summaries from events
   (Generative Agents reflection; Mem0 consolidation), balancing cost vs freshness.
3. **Importance scoring** — heuristic vs LLM-assigned `importance`, and how to keep it deterministic
   enough to trust.
4. **Multi-currency in semantic recall** — keeping the "never sum currencies" rule intact when
   memory summaries mention money.
5. **Evaluation** — how to measure recall quality for a single user (small data); adapt DMR-style
   benchmarks.
6. **Consolidation/forgetting policy** — when to collapse many events into one semantic fact, and
   how supersession interacts with re-derivation.
7. **Graph vs flat recall** — whether HippoRAG/Zep-style KG recall is worth the complexity for a
   single user, or whether flat pgvector recall suffices.

---

## Recommended Implementation Direction

- **Keep accumulating `memory_events`** from confirmations — it is already the memory backbone.
- **Defer `memory_chunks`/embeddings** until (a) the deterministic domain modules are stable and
  (b) several months of confirmed data exist (so recall has something worth indexing).
- When built: **start SQL-first**, add pgvector ANN as an *optional* recall path; **embed summaries
  and high-importance events, not every row**; always resolve hits back to live records and cite
  them.
- **Reuse the deterministic-first finance pattern** (22a/22b) for every numeric answer the assistant
  gives.
- **Keep memory inside Postgres** (pgvector) — one DB, one RLS model, one backup.

---

## Do Not Build Yet

To prevent premature vector-memory overengineering, **do not** (until Phase 23+, and after the
Phase 26 security review where noted):

- ❌ Stand up a vector database or `memory_chunks` table now.
- ❌ Embed or "memorize" **unreviewed** captures.
- ❌ Let any agent **write or mutate domain records** autonomously (review-first is permanent).
- ❌ Let the LLM **compute or invent financial numbers** (deterministic SQL only).
- ❌ Build a **knowledge-graph / temporal-graph** memory (HippoRAG/Zep-style) — advanced, optional,
  single-user ROI unproven.
- ❌ Add **real-time reflection loops**, autonomous consolidation, or fine-tuning on personal data.
- ❌ Send personal data to an external embedding/LLM provider before the Phase 26 review approves it.

Revisit all of the above at **Phase 23 (Vector memory)**, on real accumulated data.

---

## References

- [tulving72]: Tulving, E. (1972). *Episodic and Semantic Memory.* In E. Tulving & W. Donaldson
  (Eds.), *Organization of Memory* (pp. 381–403). Academic Press.
- [tulving85]: Tulving, E. (1985). *How many memory systems are there?* American Psychologist,
  40(4), 385–398. <https://doi.org/10.1037/0003-066X.40.4.385>
- [rag]: Lewis, P., et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP
  Tasks.* NeurIPS 33:9459–9474. <https://arxiv.org/abs/2005.11401>
- [selfrag]: Asai, A., et al. (2023). *Self-RAG: Learning to Retrieve, Generate and Critique through
  Self-Reflection.* ICLR 2024. <https://arxiv.org/abs/2310.11511>
- [memgpt]: Packer, C., et al. (2023). *MemGPT: Towards LLMs as Operating Systems.* (Letta.)
  <https://arxiv.org/abs/2310.08560>
- [genagents]: Park, J. S., et al. (2023). *Generative Agents: Interactive Simulacra of Human
  Behavior.* UIST 2023. <https://arxiv.org/abs/2304.03442>
- [reflexion]: Shinn, N., et al. (2023). *Reflexion: Language Agents with Verbal Reinforcement
  Learning.* NeurIPS 36:8634–8652. <https://arxiv.org/abs/2303.11366>
- [coala]: Sumers, T., et al. (2024). *Cognitive Architectures for Language Agents (CoALA).* TMLR.
  <https://arxiv.org/abs/2309.02427>
- [survey]: Zhang, Z., et al. (2024). *A Survey on the Memory Mechanism of Large Language Model based
  Agents.* <https://arxiv.org/abs/2404.13501>
- [hipporag]: Gutiérrez, B. J., et al. (2024). *HippoRAG: Neurobiologically Inspired Long-Term Memory
  for Large Language Models.* NeurIPS 2024. <https://arxiv.org/abs/2405.14831>
- [hipporag2]: Gutiérrez, B. J., et al. (2025). *From RAG to Memory: Non-Parametric Continual
  Learning for Large Language Models (HippoRAG 2).* ICML 2025. <https://arxiv.org/abs/2502.14802>
- [zep]: Rasmussen, P., et al. (2025). *Zep: A Temporal Knowledge Graph Architecture for Agent
  Memory.* <https://arxiv.org/abs/2501.13956>
- [amem]: Xu, W., et al. (2025). *A-MEM: Agentic Memory for LLM Agents.*
  <https://arxiv.org/abs/2502.12110>
- [mem0]: Chhikara, P., et al. (2025). *Mem0: Building Production-Ready AI Agents with Scalable
  Long-Term Memory.* <https://arxiv.org/abs/2504.19413>
- [pgvector]: pgvector — open-source vector similarity search for Postgres.
  <https://github.com/pgvector/pgvector>
- [supabase-ai]: Supabase — AI & Vectors (pgvector) documentation.
  <https://supabase.com/docs/guides/ai>
- [postgres]: PostgreSQL documentation. <https://www.postgresql.org/docs/>
- [langmem-docs]: LangChain — Memory overview (semantic/episodic/procedural).
  <https://docs.langchain.com/oss/python/concepts/memory>
- [langmem-concepts]: LangMem — Long-term Memory in LLM Applications (conceptual guide).
  <https://langchain-ai.github.io/langmem/concepts/conceptual_guide/>
