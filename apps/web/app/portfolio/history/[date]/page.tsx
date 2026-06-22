import Link from "next/link";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, SectionLabel } from "@/components/ui";
import { fmtMoney, fmtNum, fmtDateTime } from "@/lib/format";
import type { SnapshotDetail } from "../../snapshot-types";

export const dynamic = "force-dynamic";

async function getSnapshot(date: string): Promise<SnapshotDetail> {
  const res = await authedFetch(`/portfolio/snapshots/${encodeURIComponent(date)}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Backend returned ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

export default async function PortfolioSnapshotPage({
  params,
}: {
  params: Promise<{ date: string }>;
}) {
  const { date } = await params;
  const snapshot = await getSnapshot(date);

  return (
    <PageContainer>
      <PageHeader
        title={`Portfolio · ${snapshot.snapshot_date}`}
        subtitle={`Generated ${fmtDateTime(snapshot.generated_at)}`}
        actions={
          <Link
            href="/portfolio/history"
            className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition-colors hover:bg-surface-raised hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            History
          </Link>
        }
      />

      <div className="space-y-6">
        {snapshot.partial_failure ? (
          <div className="rounded-xl border border-border bg-surface-raised px-4 py-3 text-sm text-warning">
            This snapshot is partial because one or more brokers were unavailable.
          </div>
        ) : null}

        <section className="rounded-xl border border-border bg-surface p-6">
          <SectionLabel>Totals by currency</SectionLabel>
          <div className="space-y-2">
            {snapshot.currency_totals.map((total) => (
              <div key={total.currency} className="flex justify-between gap-4 text-sm">
                <span className="font-medium text-fg">{total.currency}</span>
                <span className="numeric text-muted">
                  {fmtMoney(total.total_value, total.currency)} · cash{" "}
                  {fmtMoney(total.cash_value, total.currency)}
                  {!total.market_value_complete ? (
                    <span className="text-warning"> · {total.market_value_missing} missing</span>
                  ) : null}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="overflow-x-auto rounded-xl border border-border bg-surface">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-border text-xs uppercase tracking-wider text-faint">
              <tr>
                <th className="px-4 py-3 font-medium">Asset</th>
                <th className="px-4 py-3 font-medium">Broker</th>
                <th className="px-4 py-3 text-right font-medium">Quantity</th>
                <th className="px-4 py-3 text-right font-medium">Value</th>
                <th className="px-4 py-3 text-right font-medium">Allocation</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.positions.map((position) => (
                <tr
                  key={`${position.account_ref}:${position.stable_asset_id}`}
                  className="border-b border-border last:border-0"
                >
                  <td className="px-4 py-3">
                    <p className="font-medium text-fg">{position.asset_symbol}</p>
                    <p className="text-xs text-faint">{position.asset_type}</p>
                  </td>
                  <td className="px-4 py-3 text-muted">
                    {position.broker} · {position.account_ref}
                  </td>
                  <td className="numeric px-4 py-3 text-right text-muted">
                    {fmtNum(position.quantity)}
                  </td>
                  <td className="numeric px-4 py-3 text-right text-fg">
                    {fmtMoney(position.market_value, position.currency)}
                  </td>
                  <td className="numeric px-4 py-3 text-right text-muted">
                    {position.allocation_pct === null ? "—" : `${fmtNum(position.allocation_pct)}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </PageContainer>
  );
}
