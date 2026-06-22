import Link from "next/link";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState, Badge } from "@/components/ui";
import { Sparkline } from "@/components/Sparkline";
import { fmtMoney } from "@/lib/format";
import type { SnapshotListResponse } from "../snapshot-types";

export const dynamic = "force-dynamic";

async function getSnapshots(): Promise<SnapshotListResponse> {
  const res = await authedFetch("/portfolio/snapshots", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Backend returned ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

export default async function PortfolioHistoryPage() {
  const data = await getSnapshots();

  const latest = data.items[0] ?? null;
  const primary =
    latest?.currency_totals.slice().sort((a, b) => b.total_value - a.total_value)[0]?.currency ??
    null;
  const series = primary
    ? data.items
        .slice()
        .reverse()
        .map((s) => s.currency_totals.find((c) => c.currency === primary)?.total_value)
        .filter((v): v is number => v != null)
    : [];

  return (
    <PageContainer>
      <PageHeader
        title="Portfolio history"
        subtitle="One normalized observation per day"
        actions={
          <Link
            href="/portfolio"
            className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition-colors hover:bg-surface-raised hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Portfolio
          </Link>
        }
      />

      {data.items.length === 0 ? (
        <EmptyState>No snapshots yet. Take one from the Portfolio page.</EmptyState>
      ) : (
        <div className="space-y-6">
          {series.length >= 2 && primary ? (
            <div className="rounded-xl border border-border bg-surface p-5">
              <div className="flex items-baseline justify-between">
                <span className="text-xs font-medium uppercase tracking-wider text-faint">
                  {primary} value
                </span>
                <span className="numeric text-lg font-medium text-fg">
                  {fmtMoney(series[series.length - 1], primary)}
                </span>
              </div>
              <Sparkline values={series} width={640} height={64} className="mt-3 w-full" />
            </div>
          ) : null}

          <div className="space-y-3">
            {data.items.map((snapshot) => (
              <Link
                key={snapshot.snapshot_date}
                href={`/portfolio/history/${snapshot.snapshot_date}`}
                className="block rounded-xl border border-border bg-surface p-5 transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium text-fg">{snapshot.snapshot_date}</span>
                  {snapshot.partial_failure ? <Badge tone="warning">Partial</Badge> : null}
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
                  {snapshot.currency_totals.map((total) => (
                    <span key={total.currency} className="numeric">
                      {fmtMoney(total.total_value, total.currency)}
                    </span>
                  ))}
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}
    </PageContainer>
  );
}
