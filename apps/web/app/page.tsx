import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, BentoGrid, MetricTile } from "@/components/ui";
import { Sparkline } from "@/components/Sparkline";
import { fmtMoney, fmtInt, fmtNum, fmtSignedMoney, pnlTone } from "@/lib/format";
import type { TasksResponse } from "./tasks/types";
import type { MoneyEventsResponse } from "./finance/types";
import type { FoodLogsResponse } from "./food/types";
import type { ExerciseLogsResponse } from "./exercise/types";
import type { HabitsResponse } from "./habits/types";
import type { GoalsResponse } from "./goals/types";
import type { DecisionsResponse } from "./decisions/types";
import type { FinancialSummary } from "./financial-intelligence/types";
import type { CalendarIntentsResponse } from "./calendar/types";
import type { InboxResponse } from "./inbox/types";
import type { DailyReview } from "./review/types";
import type { SnapshotListResponse } from "./portfolio/snapshot-types";
import type { BriefingResponse } from "./briefing/types";

export const dynamic = "force-dynamic";

interface HistoryPoint {
  snapshot_date: string;
  total_value: number;
}

// Fetch helper that degrades to null on failure but lets auth redirects propagate.
async function getJson<T>(path: string): Promise<T | null> {
  try {
    const res = await authedFetch(path, { cache: "no-store" });
    return res.ok ? ((await res.json()) as T) : null;
  } catch (e) {
    const digest = (e as { digest?: string })?.digest;
    if (typeof digest === "string" && digest.startsWith("NEXT_REDIRECT")) throw e;
    return null;
  }
}

export default async function DashboardPage() {
  const [snapshots, tasks, finance, food, exercise, habits, goals, decisions, finIntel, calendar, inbox, review, briefing] =
    await Promise.all([
      getJson<SnapshotListResponse>("/portfolio/snapshots"),
      getJson<TasksResponse>("/tasks"),
      getJson<MoneyEventsResponse>("/money_events"),
      getJson<FoodLogsResponse>("/food_logs?date=today"),
      getJson<ExerciseLogsResponse>("/exercise_logs?date=today"),
      getJson<HabitsResponse>("/habits"),
      getJson<GoalsResponse>("/goals"),
      getJson<DecisionsResponse>("/decisions"),
      getJson<FinancialSummary>("/financial_intelligence/summary"),
      getJson<CalendarIntentsResponse>("/calendar_intents"),
      getJson<InboxResponse>("/inbox"),
      getJson<DailyReview>("/daily_review"),
      getJson<BriefingResponse>("/briefing"),
    ]);

  const focusTop = briefing?.briefing?.focus?.slice(0, 3) ?? [];
  const warningCount = briefing?.briefing?.warnings?.length ?? 0;

  // Portfolio tile — latest snapshot + value sparkline (fast, DB-only).
  const latest = snapshots?.items?.[0] ?? null;
  const totalsSorted =
    latest?.currency_totals?.slice().sort((a, b) => b.total_value - a.total_value) ?? [];
  const primary = totalsSorted[0] ?? null;
  const history = primary
    ? await getJson<HistoryPoint[]>(
        `/portfolio/snapshots/history?currency=${encodeURIComponent(primary.currency)}`
      )
    : null;
  const series = (history ?? []).map((p) => p.total_value);
  const delta =
    series.length >= 2 ? series[series.length - 1] - series[series.length - 2] : null;
  const deltaTone = pnlTone(delta);

  const openTasks = tasks?.items?.filter((t) => t.status === "open").length ?? null;
  const spend = finance?.totals_by_currency ?? [];
  const mealsToday = food?.total ?? null;
  const caloriesToday = food?.totals?.calories ?? null;
  const workoutsToday = exercise?.total ?? null;
  const exerciseMinsToday = exercise?.totals?.duration_min ?? null;
  const habitsCount = habits?.total ?? null;
  const activeGoals = goals?.items?.filter((g) => g.status === "active").length ?? null;
  const decisionsCount = decisions?.total ?? null;

  // Financial intelligence: pick the currency with the largest net worth as the headline.
  const finBlocks = finIntel?.currencies ?? [];
  const primaryFin =
    finBlocks
      .filter((b) => b.net_worth.value !== null)
      .sort((a, b) => (b.net_worth.value ?? 0) - (a.net_worth.value ?? 0))[0] ?? null;
  const finAsOf = finIntel?.portfolio_as_of ?? finIntel?.manual_as_of ?? null;
  const upcoming = calendar?.items ?? [];
  const pending = inbox?.total ?? null;

  const today = new Date().toLocaleDateString("en-SG", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  return (
    <PageContainer className="max-w-6xl">
      <PageHeader title="Dashboard" subtitle={today} />

      {briefing ? (
        <Link
          href="/briefing"
          className="group mb-5 flex items-center justify-between gap-4 rounded-xl border border-border bg-surface p-4 transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <div className="min-w-0">
            <span className="text-xs font-medium uppercase tracking-wider text-faint">
              Today&apos;s focus
            </span>
            {focusTop.length > 0 ? (
              <p className="mt-1 truncate text-sm text-fg">
                {focusTop.map((t) => t.title).filter(Boolean).join(" · ")}
              </p>
            ) : (
              <p className="mt-1 text-sm text-muted">No open tasks.</p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {warningCount > 0 ? (
              <span className="rounded-full border border-warning/40 px-2 py-0.5 text-xs font-medium text-warning">
                {warningCount} alert{warningCount !== 1 ? "s" : ""}
              </span>
            ) : null}
            <ArrowUpRight size={16} className="text-faint group-hover:text-fg" aria-hidden />
          </div>
        </Link>
      ) : null}

      <BentoGrid>
        {/* Portfolio — signature tile */}
        <Link
          href="/portfolio"
          className="group col-span-2 flex flex-col rounded-xl border border-border bg-surface p-5 transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent lg:row-span-2"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-faint">
              Portfolio
            </span>
            <ArrowUpRight size={16} className="text-faint group-hover:text-fg" aria-hidden />
          </div>

          {primary ? (
            <>
              <p className="numeric mt-3 text-3xl font-medium text-fg">
                {fmtMoney(primary.total_value, primary.currency)}
              </p>
              {delta !== null ? (
                <p
                  className={`numeric mt-1 text-sm ${
                    deltaTone === "positive"
                      ? "text-positive"
                      : deltaTone === "negative"
                        ? "text-negative"
                        : "text-muted"
                  }`}
                >
                  {fmtSignedMoney(delta, primary.currency)} since last
                </p>
              ) : null}
              {series.length >= 2 ? (
                <div className="mt-4">
                  <Sparkline values={series} width={260} height={48} className="w-full" />
                </div>
              ) : null}
              <div className="mt-auto space-y-1.5 pt-4">
                {totalsSorted.map((c) => (
                  <div key={c.currency} className="flex items-center justify-between text-sm">
                    <span className="text-muted">{c.currency}</span>
                    <span className="numeric text-fg">{fmtMoney(c.total_value, c.currency)}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="mt-3 flex flex-1 flex-col justify-center text-sm text-muted">
              <p>No snapshot yet.</p>
              <p className="mt-1 text-faint">Take one from the Portfolio page.</p>
            </div>
          )}
        </Link>

        <MetricTile
          href="/inbox"
          label="Inbox"
          value={pending === null ? "—" : fmtInt(pending)}
          sub={pending ? "awaiting review" : "all clear"}
          tone={pending ? "warning" : "neutral"}
        />
        <MetricTile
          href="/tasks"
          label="Open tasks"
          value={openTasks === null ? "—" : fmtInt(openTasks)}
          sub="to do"
        />

        {/* Review — today's activity */}
        <Link
          href="/review"
          className="group col-span-2 rounded-xl border border-border bg-surface p-5 transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-faint">
              Today&apos;s activity
            </span>
            <ArrowUpRight size={16} className="text-faint group-hover:text-fg" aria-hidden />
          </div>
          {review ? (
            <div className="mt-3 grid grid-cols-3 gap-3">
              <div>
                <p className="numeric text-2xl font-medium text-fg">
                  {fmtInt(review.captured_count)}
                </p>
                <p className="mt-0.5 text-xs text-muted">captured</p>
              </div>
              <div>
                <p className="numeric text-2xl font-medium text-positive">
                  {fmtInt(review.confirmed_count)}
                </p>
                <p className="mt-0.5 text-xs text-muted">confirmed</p>
              </div>
              <div>
                <p className="numeric text-2xl font-medium text-warning">
                  {fmtInt(review.pending_count)}
                </p>
                <p className="mt-0.5 text-xs text-muted">pending</p>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted">Review unavailable.</p>
          )}
        </Link>

        {/* Finance — spend by currency */}
        <Link
          href="/finance"
          className="group col-span-2 rounded-xl border border-border bg-surface p-5 transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-faint">Spend</span>
            <ArrowUpRight size={16} className="text-faint group-hover:text-fg" aria-hidden />
          </div>
          {spend.length > 0 ? (
            <div className="mt-3 space-y-1.5">
              {spend.map((c) => (
                <div key={c.currency} className="flex items-center justify-between text-sm">
                  <span className="text-muted">{c.currency}</span>
                  <span className="numeric text-fg">{fmtMoney(c.total, c.currency)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="numeric mt-3 text-2xl font-medium text-fg">—</p>
          )}
        </Link>

        <MetricTile
          href="/food"
          label="Calories today"
          value={caloriesToday === null ? "—" : fmtInt(caloriesToday)}
          sub={mealsToday ? `${mealsToday} meal${mealsToday !== 1 ? "s" : ""}` : "logged"}
        />
        <MetricTile
          href="/exercise"
          label="Exercise today"
          value={exerciseMinsToday ? `${fmtInt(exerciseMinsToday)} min` : "—"}
          sub={workoutsToday ? `${workoutsToday} workout${workoutsToday !== 1 ? "s" : ""}` : "logged"}
        />
        <MetricTile
          href="/goals"
          label="Active goals"
          value={activeGoals === null ? "—" : fmtInt(activeGoals)}
          sub="in progress"
        />
        <MetricTile
          href="/habits"
          label="Habits"
          value={habitsCount === null ? "—" : fmtInt(habitsCount)}
          sub="tracked"
        />
        <MetricTile
          href="/decisions"
          label="Decisions"
          value={decisionsCount === null ? "—" : fmtInt(decisionsCount)}
          sub="logged"
        />
        <MetricTile
          href="/financial-intelligence"
          label="Net worth"
          value={primaryFin ? fmtMoney(primaryFin.net_worth.value, primaryFin.currency) : "—"}
          sub={primaryFin ? (finAsOf ? `as of ${finAsOf}` : primaryFin.currency) : "add a snapshot"}
        />
        <MetricTile
          href="/financial-intelligence"
          label="Cash runway"
          value={
            primaryFin && primaryFin.cash_runway_months !== null
              ? `${fmtNum(primaryFin.cash_runway_months, 1)} mo`
              : "—"
          }
          sub="logged expenses"
        />
        <MetricTile
          href="/financial-intelligence"
          label="Savings rate"
          value={
            primaryFin && primaryFin.savings_rate !== null
              ? `${(primaryFin.savings_rate * 100).toFixed(0)}%`
              : "—"
          }
          sub="logged"
        />
        <MetricTile href="/calendar" label="Calendar" value={fmtInt(upcoming.length)} sub="intentions" />
      </BentoGrid>
    </PageContainer>
  );
}
