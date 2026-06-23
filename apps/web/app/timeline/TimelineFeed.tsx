"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import {
  CheckSquare,
  Wallet,
  Apple,
  Dumbbell,
  Repeat,
  Target,
  Calendar,
  PieChart,
  Circle,
  type LucideIcon,
} from "lucide-react";
import { EmptyState } from "@/components/ui";
import { fmtDayHeading, fmtTime, fmtInt, fmtNum, type Tone } from "@/lib/format";
import { fetchTimeline } from "./actions";
import { TIMELINE_DOMAINS, type TimelineEntry } from "./types";

// Defensive readers — payloads are typed as unknown and keys may be missing.
type Payload = Record<string, unknown>;
const str = (v: unknown): string | null =>
  typeof v === "string" && v.trim() ? v : null;
const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;
const join = (parts: (string | null)[]): string => parts.filter(Boolean).join(" · ");

interface DomainMeta {
  label: string;
  icon: LucideIcon;
  tone: Tone;
  title: (p: Payload) => string;
  summary: (p: Payload) => string;
  href: (p: Payload) => string;
}

const DOMAIN_META: Record<string, DomainMeta> = {
  task: {
    label: "Task",
    icon: CheckSquare,
    tone: "info",
    title: (p) => str(p.title) ?? "Task",
    summary: (p) => join([str(p.status), str(p.due_date) ? `due ${str(p.due_date)}` : null]),
    href: () => "/tasks",
  },
  money: {
    label: "Money",
    icon: Wallet,
    tone: "warning",
    title: (p) => str(p.merchant) ?? "Expense",
    summary: (p) => {
      const amount = num(p.amount);
      const ccy = str(p.currency) ?? "";
      return join([
        amount != null ? `${ccy} ${fmtNum(amount)}`.trim() : null,
        str(p.direction),
      ]);
    },
    href: () => "/finance",
  },
  food: {
    label: "Food",
    icon: Apple,
    tone: "positive",
    title: (p) => str(p.description) ?? "Food",
    summary: (p) => {
      const cal = num(p.calories);
      return join([str(p.meal_type), cal != null ? `${fmtInt(cal)} kcal` : null]);
    },
    href: () => "/food",
  },
  exercise: {
    label: "Exercise",
    icon: Dumbbell,
    tone: "info",
    title: (p) => str(p.activity) ?? "Exercise",
    summary: (p) => {
      const dur = num(p.duration_min);
      const dist = num(p.distance_km);
      return join([
        dur != null ? `${fmtInt(dur)} min` : null,
        dist != null ? `${fmtNum(dist)} km` : null,
      ]);
    },
    href: () => "/exercise",
  },
  habit: {
    label: "Habit",
    icon: Repeat,
    tone: "info",
    title: (p) => str(p.name) ?? "Habit",
    summary: (p) =>
      join([str(p.cadence), str(p.target) ? `target ${str(p.target)}` : null]),
    href: () => "/habits",
  },
  goal: {
    label: "Goal",
    icon: Target,
    tone: "accent",
    title: (p) => str(p.title) ?? "Goal",
    // status is frozen at confirmation time (always 'active'), so omit it to avoid
    // showing a stale status after a later toggle.
    summary: (p) =>
      join([str(p.target), str(p.target_date) ? `by ${str(p.target_date)}` : null]),
    href: () => "/goals",
  },
  calendar: {
    label: "Calendar",
    icon: Calendar,
    tone: "accent",
    title: (p) => str(p.title) ?? "Calendar",
    summary: (p) => join([str(p.proposed_datetime), str(p.location)]),
    href: () => "/calendar",
  },
  portfolio_snapshot: {
    label: "Portfolio",
    icon: PieChart,
    tone: "neutral",
    title: () => "Portfolio snapshot",
    summary: (p) => join([str(p.snapshot_date), p.partial_failure === true ? "partial" : null]),
    href: (p) => {
      const date = str(p.snapshot_date);
      return date ? `/portfolio/history/${date}` : "/portfolio";
    },
  },
};

const FALLBACK: DomainMeta = {
  label: "Event",
  icon: Circle,
  tone: "neutral",
  title: (p) => str(p.title) ?? "Event",
  summary: () => "",
  href: () => "/timeline",
};

const toneDot: Record<Tone, string> = {
  neutral: "bg-faint",
  positive: "bg-positive",
  negative: "bg-negative",
  warning: "bg-warning",
  info: "bg-info",
  accent: "bg-accent",
};

function TimelineRow({ entry }: { entry: TimelineEntry }) {
  const meta = DOMAIN_META[entry.domain] ?? FALLBACK;
  const Icon = meta.icon;
  const summary = meta.summary(entry.payload);
  return (
    <Link
      href={meta.href(entry.payload)}
      className="group flex items-start gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-surface-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      <span className="relative mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border bg-surface">
        <Icon size={14} className="text-muted group-hover:text-fg" aria-hidden />
        <span
          className={`absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full ${toneDot[meta.tone]}`}
          aria-hidden
        />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-3">
          <p className="truncate font-medium text-fg">{meta.title(entry.payload)}</p>
          <span className="numeric shrink-0 text-xs text-faint">{fmtTime(entry.occurred_at)}</span>
        </div>
        <p className="mt-0.5 text-xs text-muted">
          <span className="text-faint">{meta.label}</span>
          {summary ? <span> · {summary}</span> : null}
        </p>
      </div>
    </Link>
  );
}

export function TimelineFeed({
  initialItems,
  initialCursor,
  initialError,
}: {
  initialItems: TimelineEntry[];
  initialCursor: string | null;
  initialError: boolean;
}) {
  const [items, setItems] = useState<TimelineEntry[]>(initialItems);
  const [cursor, setCursor] = useState<string | null>(initialCursor);
  const [active, setActive] = useState<string[]>([]);
  const [error, setError] = useState<boolean>(initialError);
  const [isPending, startTransition] = useTransition();

  function applyFilter(next: string[]) {
    setActive(next);
    startTransition(async () => {
      const res = await fetchTimeline({ domains: next.length ? next : undefined });
      if (!res.ok || !res.data) {
        setError(true);
        return;
      }
      setError(false);
      setItems(res.data.items);
      setCursor(res.data.next_cursor);
    });
  }

  function toggle(value: string) {
    applyFilter(active.includes(value) ? active.filter((d) => d !== value) : [...active, value]);
  }

  function loadOlder() {
    if (!cursor) return;
    startTransition(async () => {
      const res = await fetchTimeline({
        domains: active.length ? active : undefined,
        cursor,
      });
      // On a load-more failure keep the already-loaded items (and the cursor, so the
      // button stays available to retry) rather than hiding the whole list.
      if (!res.ok || !res.data) return;
      const data = res.data;
      setItems((prev) => [...prev, ...data.items]);
      setCursor(data.next_cursor);
    });
  }

  // Group consecutively by local day (items arrive newest-first, globally ordered).
  const groups: { heading: string; entries: TimelineEntry[] }[] = [];
  for (const entry of items) {
    const heading = fmtDayHeading(entry.occurred_at);
    const last = groups[groups.length - 1];
    if (last && last.heading === heading) last.entries.push(entry);
    else groups.push({ heading, entries: [entry] });
  }

  const chipBase =
    "rounded-full border px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => applyFilter([])}
          disabled={isPending}
          className={`${chipBase} ${
            active.length === 0
              ? "border-accent bg-accent text-accent-fg"
              : "border-border text-muted hover:bg-surface-raised hover:text-fg"
          }`}
        >
          All
        </button>
        {TIMELINE_DOMAINS.map((d) => {
          const on = active.includes(d.value);
          return (
            <button
              key={d.value}
              type="button"
              onClick={() => toggle(d.value)}
              disabled={isPending}
              className={`${chipBase} ${
                on
                  ? "border-accent bg-accent text-accent-fg"
                  : "border-border text-muted hover:bg-surface-raised hover:text-fg"
              }`}
            >
              {d.label}
            </button>
          );
        })}
      </div>

      {error ? (
        <EmptyState>
          Couldn&apos;t load the timeline. If this persists, the backend may be unavailable.
        </EmptyState>
      ) : items.length === 0 ? (
        <EmptyState>
          Nothing here yet. Confirmed tasks, expenses, meals, workouts, calendar intents, and
          portfolio snapshots will appear here as you review them.
        </EmptyState>
      ) : (
        <div className="space-y-6">
          {groups.map((group) => (
            <section key={group.heading}>
              <h2 className="mb-1 px-2 text-xs font-medium uppercase tracking-wider text-faint">
                {group.heading}
              </h2>
              <div className="border-l border-border pl-2">
                {group.entries.map((entry) => (
                  <TimelineRow key={entry.id} entry={entry} />
                ))}
              </div>
            </section>
          ))}

          {cursor ? (
            <div className="flex justify-center pt-2">
              <button
                type="button"
                onClick={loadOlder}
                disabled={isPending}
                className="rounded-lg border border-border px-4 py-1.5 text-xs font-medium text-muted transition-colors hover:bg-surface-raised hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
              >
                {isPending ? "Loading…" : "Load older"}
              </button>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
