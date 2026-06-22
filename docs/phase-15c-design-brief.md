# Phase 15c — UI Revamp: Design Brief (decision record)

> Status: **design direction approved; full implementation plan deferred** until Phase 14.5
> and 15b land (the revamp is one cohesive pass over a stable page set). This brief locks the
> aesthetic decisions and design system so the eventual Codex plan is unambiguous.
>
> Grounded in two design skills (read, not installed): Anthropic `frontend-design` SKILL.md
> and `ui-ux-pro-max-skill`. Their core mandate applied here: **ground the design in this
> product, spend boldness in one signature element, and avoid AI-default looks.**

## Product framing
A private personal operating system / life dashboard integrating: inbox (review queue),
tasks, finance, portfolio, food/nutrition, calendar, daily review, and (future) exercise/
habits/goals/journal. The user wants it to feel **professional, dense, and modular**.

## Approved direction (locked)
- **Layout: A — command-center bento.** A modular grid of mixed-size tiles is the home view;
  everything glanceable at once. Refinement: add a **slim left icon rail** for navigation
  (the mockup's top bar doesn't scale to 10+ domains) — i.e. bento main area + persistent
  compact nav. The bento home is the signature surface.
- **Theme: dark + light with a toggle**, dark-first design. High-contrast.
- **Aesthetic: high-contrast data-cockpit** — crisp neutral layered surfaces, semantic color
  reserved for meaning (P&L green/red, status amber/blue/red), restrained single brand accent.

## Signature element (the one aesthetic risk, per the skill)
The **numeric/data treatment**: large **tabular-figure** numbers with inline delta + tiny
sparkline and semantic coloring (e.g. portfolio value with +/- today, per-currency subtotals).
This is the memorable, characterful thing; everything around it stays quiet and disciplined.

## Design system (to be implemented as a Tailwind theme + CSS variables)
- **Theme tokens:** semantic CSS variables for both modes — layered surfaces
  (`bg`, `surface`, `surface-raised`, `border`), text (`primary`, `secondary`, `tertiary`),
  and semantic (`positive`/green, `negative`/red, `warning`/amber, `info`/blue). Dark-first;
  light is the same tokens remapped. Target **≥4.5:1** contrast in both modes.
- **Typography (deliberate pairing — NOT default Inter):** a distinctive grotesk/geometric
  UI face (e.g. Geist or similar) + **tabular/monospaced figures** for all numeric data
  (`font-variant-numeric: tabular-nums`) so columns of money/quantities align. Clear type
  scale, two weights (400/500). Sentence case everywhere.
- **Density:** compact spacing scale (4/8/12/16), hairline `0.5px` borders, tile padding
  ~12–16px, generous use of small metric tiles. Modular bento via CSS grid with `span`-based
  tile sizing.
- **Components inventory:** app shell (icon rail + content), bento tile (sizes: 1×1, 2×1,
  2×2), metric tile, list tile (tasks/inbox/agenda), portfolio tile (numeric signature),
  status badges, P&L coloring helper, capture button, theme toggle, page header.
- **Avoid (explicit, from the skill):** warm-cream + serif + terracotta; near-black + acid-
  green/vermilion; broadsheet hairline-rule layouts. No gradients/neon as decoration.

## Quality floor (from both skills — non-negotiable)
Keyboard-visible focus states · `prefers-reduced-motion` respected · hover transitions
150–300ms · responsive at 375/768/1024/1440 · no emoji (use Lucide/Heroicons or Tabler) ·
cursor-pointer on interactive elements · no CSS specificity conflicts between sections ·
dark+light both verified.

## Scope when 15c runs (pages to restyle in one pass)
inbox, tasks, finance, food, calendar, review, portfolio, portfolio/history (14.5), login,
home/dashboard — all onto the shared shell + bento home. Frontend-only; **no backend/auth/API
changes** (zero risk to the verified auth + RLS layer).

## Why deferred (sequencing)
Doing the revamp now means re-styling again after 14.5 adds snapshot/history pages and any
15b additions. Run it as **14.5 → 15b → 15c (this) → 16 deploy**, so it covers the complete,
stable page set once.

## Next step
After 14.5 + 15b land: Claude writes the full Codex execution plan for 15c (theme tokens,
shell, component kit, per-page migration, visual QA via the browser preview tools), with a
paste-ready Codex prompt — same workflow as 14.5/15a.
