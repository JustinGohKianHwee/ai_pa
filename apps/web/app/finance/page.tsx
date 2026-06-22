import type { MoneyEventsResponse } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState, SectionLabel } from "@/components/ui";
import { fmtNum, fmtDateTime } from "@/lib/format";

export const dynamic = "force-dynamic";

async function getMoneyEvents(): Promise<MoneyEventsResponse> {
  const res = await authedFetch("/money_events", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Backend returned ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

export default async function FinancePage() {
  const data = await getMoneyEvents();

  return (
    <PageContainer>
      <PageHeader
        title="Finance"
        subtitle={
          data.total === 0 ? "No expenses yet" : `${data.total} expense${data.total !== 1 ? "s" : ""}`
        }
      />

      {data.total === 0 ? (
        <EmptyState>Confirm a finance expense in the inbox to see it here.</EmptyState>
      ) : (
        <div className="space-y-8">
          <div className="grid gap-3 sm:grid-cols-2">
            {data.totals_by_currency.map((bucket) => (
              <div key={bucket.currency} className="rounded-xl border border-border bg-surface p-4">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-xs font-medium uppercase tracking-wider text-faint">
                    {bucket.currency}
                  </span>
                  <span className="numeric text-xl font-medium text-fg">
                    {bucket.currency} {fmtNum(bucket.total)}
                  </span>
                </div>
                <div className="mt-3 space-y-1">
                  {bucket.by_category.map((cat) => (
                    <div key={cat.category} className="flex justify-between text-sm text-muted">
                      <span>{cat.category}</span>
                      <span className="numeric">{fmtNum(cat.amount)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <section>
            <SectionLabel>Recent expenses</SectionLabel>
            <div className="overflow-x-auto rounded-xl border border-border bg-surface">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-faint">
                    <th className="px-4 py-3 font-medium">Merchant</th>
                    <th className="px-4 py-3 font-medium">Category</th>
                    <th className="px-4 py-3 font-medium">When</th>
                    <th className="px-4 py-3 text-right font-medium">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((event) => (
                    <tr key={event.id} className="border-b border-border last:border-0">
                      <td className="px-4 py-3 text-fg">{event.merchant ?? "—"}</td>
                      <td className="px-4 py-3 text-muted">{event.category ?? "—"}</td>
                      <td className="px-4 py-3 text-muted">
                        {event.occurred_at ?? fmtDateTime(event.created_at)}
                      </td>
                      <td className="numeric px-4 py-3 text-right text-negative">
                        {event.currency} {fmtNum(event.amount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </PageContainer>
  );
}
