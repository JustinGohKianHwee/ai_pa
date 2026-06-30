import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { authedFetch } from "@/lib/api";
import { Badge, Card, EmptyState, PageContainer, PageHeader } from "@/components/ui";
import { fmtDateTime, fmtMoney, type Tone } from "@/lib/format";
import type { FinancialGoalsResponse, FinancialGoalProgress } from "@/app/financial-intelligence/types";
import type { Goal, GoalLinksResponse } from "../types";
import { LinkManager } from "./LinkManager";

export const dynamic = "force-dynamic";

const STATUS_TONE: Record<string, Tone> = {
  active: "info",
  achieved: "positive",
  abandoned: "neutral",
};

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

function metricLabel(metric: string | null | undefined) {
  if (!metric) return "target";
  return metric.replace(/_/g, " ");
}

function ProgressBlock({ progress }: { progress: FinancialGoalProgress | null }) {
  if (!progress) return null;

  const pct = progress.progress_pct === null ? null : Math.max(0, Math.min(1, progress.progress_pct));
  return (
    <Card className="p-4">
      <h2 className="text-sm font-medium text-fg">Financial progress</h2>
      {progress.base_value === null || pct === null ? (
        <p className="mt-2 text-sm text-muted">Progress unavailable until there is enough financial data.</p>
      ) : (
        <>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-raised">
            <div
              className="h-full rounded-full bg-accent"
              style={{ width: `${Math.round(pct * 100)}%` }}
            />
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="numeric text-fg">
              {Math.round(pct * 100)}% · {fmtMoney(progress.base_value, progress.target_currency)} /{" "}
              {fmtMoney(progress.target_value, progress.target_currency)}
            </span>
            <span className="text-muted">{metricLabel(progress.target_metric)}</span>
          </div>
        </>
      )}
    </Card>
  );
}

export default async function GoalDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [goal, links, financialGoals] = await Promise.all([
    getJson<Goal>(`/goals/${id}`),
    getJson<GoalLinksResponse>(`/goals/${id}/links`),
    getJson<FinancialGoalsResponse>("/financial_intelligence/financial-goals"),
  ]);

  if (!goal) {
    return (
      <PageContainer>
        <PageHeader
          title="Goal"
          subtitle={
            <Link href="/goals" className="text-accent hover:underline">
              Back to goals
            </Link>
          }
        />
        <EmptyState>Goal unavailable or not found.</EmptyState>
      </PageContainer>
    );
  }

  const progress = financialGoals?.items.find((item) => item.id === goal.id) ?? null;
  const portfolioAsOf = financialGoals?.portfolio_as_of ?? null;

  return (
    <PageContainer>
      <PageHeader
        title={goal.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <Link href="/goals" className="inline-flex items-center gap-1 text-accent hover:underline">
              <ArrowLeft size={14} aria-hidden />
              Back to goals
            </Link>
            <span aria-hidden>·</span>
            <span>Created {fmtDateTime(goal.created_at)}</span>
          </span>
        }
        actions={<Badge tone={STATUS_TONE[goal.status] ?? "neutral"} dot={false}>{goal.status}</Badge>}
      />

      <div className="space-y-4">
        <Card className="p-4">
          {goal.description ? <p className="text-sm text-muted">{goal.description}</p> : null}
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted">
            {goal.target ? <span>Target: {goal.target}</span> : null}
            {goal.target_date ? <span>By {goal.target_date}</span> : null}
            {goal.target_value !== null && goal.target_currency ? (
              <span>
                Numeric target: {fmtMoney(goal.target_value, goal.target_currency)}
              </span>
            ) : null}
          </div>
        </Card>

        <ProgressBlock progress={progress} />
        {progress && portfolioAsOf ? (
          <p className="-mt-2 text-xs text-faint">Portfolio as of {portfolioAsOf}</p>
        ) : null}

        <Card className="p-4">
          <LinkManager goalId={goal.id} links={links?.items ?? []} />
        </Card>
      </div>
    </PageContainer>
  );
}
