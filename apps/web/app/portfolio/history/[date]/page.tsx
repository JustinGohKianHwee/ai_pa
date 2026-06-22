import Link from "next/link";
import { authedFetch } from "@/lib/api";
import { fmtMoney, fmtNum } from "../../format";
import type { SnapshotDetail } from "../../snapshot-types";

export const dynamic = "force-dynamic";

async function getSnapshot(date: string): Promise<SnapshotDetail> {
  const response = await authedFetch(`/portfolio/snapshots/${encodeURIComponent(date)}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}: ${response.statusText}`);
  }
  return response.json();
}

export default async function PortfolioSnapshotPage({
  params,
}: {
  params: Promise<{ date: string }>;
}) {
  const { date } = await params;
  const snapshot = await getSnapshot(date);

  return (
    <main className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="mx-auto max-w-4xl space-y-6">
        <div>
          <Link href="/portfolio/history" className="text-sm text-gray-400 hover:text-gray-600">
            ← History
          </Link>
          <h1 className="mt-2 text-2xl font-semibold text-gray-900">
            Portfolio · {snapshot.snapshot_date}
          </h1>
          <p className="mt-1 text-xs text-gray-400">
            Generated {new Date(snapshot.generated_at).toLocaleString("en-SG")}
          </p>
        </div>

        {snapshot.partial_failure && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
            This snapshot is partial because one or more brokers were unavailable.
          </div>
        )}

        <section className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="mb-3 text-xs font-medium uppercase tracking-wide text-gray-400">
            Totals by currency
          </h2>
          <div className="space-y-2">
            {snapshot.currency_totals.map((total) => (
              <div key={total.currency} className="flex justify-between gap-4 text-sm">
                <span className="font-medium text-gray-700">{total.currency}</span>
                <span className="text-gray-600">
                  {fmtMoney(total.total_value, total.currency)} · cash {fmtMoney(total.cash_value, total.currency)}
                  {!total.market_value_complete && ` · ${total.market_value_missing} value missing`}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-gray-200 bg-gray-50 text-xs uppercase text-gray-400">
              <tr>
                <th className="px-4 py-3">Asset</th>
                <th className="px-4 py-3">Broker</th>
                <th className="px-4 py-3 text-right">Quantity</th>
                <th className="px-4 py-3 text-right">Value</th>
                <th className="px-4 py-3 text-right">Allocation</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.positions.map((position) => (
                <tr
                  key={`${position.account_ref}:${position.stable_asset_id}`}
                  className="border-b border-gray-100 last:border-0"
                >
                  <td className="px-4 py-3">
                    <p className="font-medium text-gray-800">{position.asset_symbol}</p>
                    <p className="text-xs text-gray-400">{position.asset_type}</p>
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {position.broker} · {position.account_ref}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-600">
                    {fmtNum(position.quantity)}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-600">
                    {fmtMoney(position.market_value, position.currency)}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-600">
                    {position.allocation_pct === null
                      ? "—"
                      : `${fmtNum(position.allocation_pct)}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </main>
  );
}
