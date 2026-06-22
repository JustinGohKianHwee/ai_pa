import Link from "next/link";
import { authedFetch } from "@/lib/api";
import { fmtMoney } from "../format";
import type { SnapshotListResponse } from "../snapshot-types";

export const dynamic = "force-dynamic";

async function getSnapshots(): Promise<SnapshotListResponse> {
  const response = await authedFetch("/portfolio/snapshots", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}: ${response.statusText}`);
  }
  return response.json();
}

export default async function PortfolioHistoryPage() {
  const data = await getSnapshots();

  return (
    <main className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="mx-auto max-w-2xl space-y-6">
        <div>
          <Link href="/portfolio" className="text-sm text-gray-400 hover:text-gray-600">
            ← Portfolio
          </Link>
          <h1 className="mt-2 text-2xl font-semibold text-gray-900">Portfolio history</h1>
          <p className="mt-1 text-sm text-gray-500">One normalized observation per day.</p>
        </div>

        {data.items.length === 0 ? (
          <div className="rounded-xl border border-gray-200 bg-white p-6 text-sm text-gray-500">
            No snapshots yet.
          </div>
        ) : (
          <div className="space-y-3">
            {data.items.map((snapshot) => (
              <Link
                key={snapshot.snapshot_date}
                href={`/portfolio/history/${snapshot.snapshot_date}`}
                className="block rounded-xl border border-gray-200 bg-white p-5 hover:border-gray-300"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium text-gray-900">{snapshot.snapshot_date}</span>
                  {snapshot.partial_failure && (
                    <span className="text-xs text-amber-700">Partial</span>
                  )}
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-500">
                  {snapshot.currency_totals.map((total) => (
                    <span key={total.currency}>
                      {fmtMoney(total.total_value, total.currency)}
                    </span>
                  ))}
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
