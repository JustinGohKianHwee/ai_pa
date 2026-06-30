import Link from "next/link";
import type { BriefingResponse } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState, Badge } from "@/components/ui";
import { fmtMoney, fmtSignedMoney } from "@/lib/format";

export const dynamic = "force-dynamic";

async function getBriefing(): Promise<BriefingResponse | null> {
  try {
    const res = await authedFetch("/briefing", { cache: "no-store" });
    return res.ok ? ((await res.json()) as BriefingResponse) : null;
  } catch (e) {
    const digest = (e as { digest?: string })?.digest;
    if (typeof digest === "string" && digest.startsWith("NEXT_REDIRECT")) throw e;
    return null;
  }
}

const URGENCY_TONE: Record<string, "negative" | "warning" | "neutral"> = {
  today: "negative",
  this_week: "warning",
  someday: "neutral",
};

export default async function BriefingPage() {
  const data = await getBriefing();

  if (data === null) {
    return (
      <PageContainer>
        <PageHeader title="Briefing" subtitle="Couldn't load today's briefing" />
        <EmptyState>
          The briefing is unavailable right now. If this persists, the database migration (0022) may
          not be applied yet, or USER_TIMEZONE may be unset.
        </EmptyState>
      </PageContainer>
    );
  }

  const b = data.briefing;

  return (
    <PageContainer className="max-w-3xl">
      <PageHeader title="Today" subtitle={b.headline} />

      <div className="space-y-4">
        {b.warnings.length > 0 ? (
          <div className="rounded-xl border border-warning/40 bg-surface p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-warning">Heads up</p>
            <ul className="mt-2 space-y-1 text-sm text-fg">
              {b.warnings.map((w, i) => (
                <li key={i}>• {w}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="rounded-xl border border-border bg-surface p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-faint">Focus</p>
          {b.focus.length > 0 ? (
            <ul className="mt-2 space-y-1.5">
              {b.focus.map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-3 text-sm text-fg">
                  <span>{t.title ?? "(untitled task)"}</span>
                  {t.urgency ? (
                    <Badge tone={URGENCY_TONE[t.urgency] ?? "neutral"} dot={false}>
                      {t.urgency.replace("_", " ")}
                    </Badge>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted">No open tasks. <Link href="/tasks" className="underline hover:text-fg">Tasks →</Link></p>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="rounded-xl border border-border bg-surface p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-faint">Spend today</p>
            {b.spend_today.length > 0 ? (
              <ul className="mt-2 space-y-1">
                {b.spend_today.map((s) => (
                  <li key={s.currency} className="flex justify-between text-sm">
                    <span className="text-muted">{s.currency}</span>
                    <span className="numeric text-fg">{fmtMoney(s.amount, s.currency)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="numeric mt-2 text-lg text-fg">—</p>
            )}
            {b.spend_month_to_date.length > 0 ? (
              <p className="mt-2 text-xs text-faint">
                Month to date:{" "}
                {b.spend_month_to_date.map((s) => `${fmtMoney(s.amount, s.currency)}`).join(" · ")}
              </p>
            ) : null}
          </div>

          <div className="rounded-xl border border-border bg-surface p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-faint">
              Portfolio since last snapshot
            </p>
            {b.portfolio_delta.length > 0 ? (
              <ul className="mt-2 space-y-1">
                {b.portfolio_delta.map((d) => (
                  <li key={d.currency} className="flex justify-between text-sm">
                    <span className="text-muted">{d.currency}</span>
                    <span
                      className={`numeric ${
                        d.amount > 0 ? "text-positive" : d.amount < 0 ? "text-negative" : "text-fg"
                      }`}
                    >
                      {fmtSignedMoney(d.amount, d.currency)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="numeric mt-2 text-lg text-fg">—</p>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-border bg-surface p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-faint">Calendar</p>
          {b.calendar.length > 0 ? (
            <ul className="mt-2 space-y-1 text-sm text-fg">
              {b.calendar.slice(0, 8).map((c) => (
                <li key={c.id} className="flex items-center justify-between gap-3">
                  <span>{c.title ?? "(untitled)"}</span>
                  <span className="text-xs text-faint">{c.proposed_datetime ?? ""}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted">No calendar intentions.</p>
          )}
        </div>

        <div className="flex items-center justify-between rounded-xl border border-border bg-surface p-4">
          <span className="text-sm text-muted">Inbox awaiting review</span>
          <Link href="/inbox" className="text-sm font-medium text-accent hover:underline">
            {b.pending_inbox} pending →
          </Link>
        </div>
      </div>
    </PageContainer>
  );
}
