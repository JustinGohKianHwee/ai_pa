import Link from "next/link";
import type { CurrencyTotals, MoneyEvent, MoneyEventsResponse } from "./types";
import { authedFetch } from "@/lib/api";

// Always render at request time — never pre-render at build; requires live token + data.
export const dynamic = "force-dynamic";

async function getMoneyEvents(): Promise<MoneyEventsResponse> {
  const res = await authedFetch("/money_events", {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Backend returned ${res.status}: ${res.statusText}`);
  }

  return res.json();
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-SG", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function formatAmount(amount: number, currency: string): string {
  return `${currency} ${amount.toFixed(2)}`;
}

function TotalsByCurrency({ totals }: { totals: CurrencyTotals[] }) {
  if (totals.length === 0) return null;
  return (
    <section className="space-y-3">
      <h2 className="text-xs font-medium text-gray-400 uppercase tracking-wide">
        Totals by currency
      </h2>
      <div className="grid gap-3 sm:grid-cols-2">
        {totals.map((bucket) => (
          <div
            key={bucket.currency}
            className="bg-white border border-gray-200 rounded-xl p-4"
          >
            <div className="flex items-baseline justify-between">
              <span className="text-sm font-medium text-gray-500">{bucket.currency}</span>
              <span className="text-lg font-semibold text-gray-900">
                {formatAmount(bucket.total, bucket.currency)}
              </span>
            </div>
            <div className="mt-3 space-y-1">
              {bucket.by_category.map((cat) => (
                <div
                  key={cat.category}
                  className="flex justify-between text-sm text-gray-500"
                >
                  <span>{cat.category}</span>
                  <span className="tabular-nums">{cat.amount.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ExpenseCard({ event }: { event: MoneyEvent }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="font-medium text-gray-900 leading-snug">
          {event.merchant ?? event.category ?? "Expense"}
        </p>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-400 mt-2">
          {event.category && <span>category: {event.category}</span>}
          {event.occurred_at && <span>occurred: {event.occurred_at}</span>}
          {event.notes && <span className="text-gray-500">{event.notes}</span>}
          <span>{formatDate(event.created_at)}</span>
        </div>
      </div>
      <span className="shrink-0 font-semibold text-gray-900 tabular-nums">
        {formatAmount(event.amount, event.currency)}
      </span>
    </div>
  );
}

export default async function FinancePage() {
  const data = await getMoneyEvents();

  return (
    <main className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <Link href="/" className="text-sm text-gray-400 hover:text-gray-600">
            ← Home
          </Link>
          <h1 className="text-2xl font-semibold text-gray-900 mt-2">Finance</h1>
          <p className="mt-1 text-sm text-gray-500">
            {data.total === 0
              ? "No expenses yet"
              : `${data.total} expense${data.total !== 1 ? "s" : ""}`}
          </p>
        </div>

        {data.total === 0 ? (
          <div className="bg-white border border-gray-200 rounded-xl p-12 text-center">
            <p className="text-gray-400 text-sm">No expenses yet.</p>
            <p className="text-gray-400 text-sm mt-1">
              Confirm a finance expense in the inbox to see it here.
            </p>
          </div>
        ) : (
          <>
            <TotalsByCurrency totals={data.totals_by_currency} />
            <section className="space-y-2">
              <h2 className="text-xs font-medium text-gray-400 uppercase tracking-wide">
                Recent expenses
              </h2>
              {data.items.map((event) => (
                <ExpenseCard key={event.id} event={event} />
              ))}
            </section>
          </>
        )}
      </div>
    </main>
  );
}
