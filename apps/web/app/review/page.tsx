import Link from "next/link";
import type { DailyReview, InboxItemSummary } from "./types";

export const dynamic = "force-dynamic";

async function getDailyReview(): Promise<DailyReview> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const token = process.env.DEV_ADMIN_TOKEN;

  if (!token) {
    throw new Error(
      "DEV_ADMIN_TOKEN is not configured. Add it to apps/web/.env.local."
    );
  }

  const res = await fetch(`${apiUrl}/daily_review?date=today`, {
    headers: { Authorization: `Bearer ${token}` },
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

const ITEM_TYPE_LABELS: Record<string, string> = {
  task: "Task",
  finance: "Finance",
  food: "Food",
  calendar: "Calendar",
  note: "Note",
  journal: "Journal",
  investment: "Investment",
};

function itemTypeLabel(type: string): string {
  return ITEM_TYPE_LABELS[type] ?? "Item";
}

function ItemTypeBadge({ type }: { type: string }) {
  const colorMap: Record<string, string> = {
    task: "bg-blue-100 text-blue-800",
    finance: "bg-emerald-100 text-emerald-800",
    food: "bg-orange-100 text-orange-800",
    calendar: "bg-purple-100 text-purple-800",
    note: "bg-gray-100 text-gray-700",
    journal: "bg-pink-100 text-pink-800",
    investment: "bg-yellow-100 text-yellow-800",
  };
  const cls = colorMap[type] ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full ${cls}`}>
      {itemTypeLabel(type)}
    </span>
  );
}

function ReviewItemCard({
  item,
  timestampLabel,
  timestamp,
}: {
  item: InboxItemSummary;
  timestampLabel: string;
  timestamp: string;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm text-gray-800 leading-snug">
          {item.title ?? <span className="italic text-gray-400">Untitled</span>}
        </p>
        <ItemTypeBadge type={item.item_type} />
      </div>
      <p className="text-xs text-gray-400 mt-2">
        {timestampLabel}: {formatDate(timestamp)}
      </p>
    </div>
  );
}

function StatBadge({ label, count }: { label: string; count: number }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 text-center">
      <p className="text-2xl font-semibold text-gray-900">{count}</p>
      <p className="text-xs text-gray-400 mt-1">{label}</p>
    </div>
  );
}

export default async function ReviewPage() {
  const data = await getDailyReview();

  const isEmpty =
    data.captured_count === 0 &&
    data.confirmed_count === 0 &&
    data.rejected_count === 0;

  return (
    <main className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <Link href="/" className="text-sm text-gray-400 hover:text-gray-600">
            ← Home
          </Link>
          <div className="flex items-baseline gap-3 mt-2">
            <h1 className="text-2xl font-semibold text-gray-900">
              Daily Review
            </h1>
            <span className="text-sm text-gray-400">{data.review_date}</span>
            <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
              {data.timezone}
            </span>
          </div>
          {data.summary && (
            <p className="mt-2 text-sm text-gray-500 italic">{data.summary}</p>
          )}
        </div>

        <div className="grid grid-cols-4 gap-3">
          <StatBadge label="Captured" count={data.captured_count} />
          <StatBadge label="Confirmed" count={data.confirmed_count} />
          <StatBadge label="Rejected" count={data.rejected_count} />
          <StatBadge label="Pending" count={data.pending_count} />
        </div>

        {isEmpty ? (
          <div className="bg-white border border-gray-200 rounded-xl p-12 text-center">
            <p className="text-gray-400 text-sm">Nothing captured or reviewed today.</p>
            <p className="text-gray-400 text-sm mt-1">
              Send a message via Telegram to get started.
            </p>
          </div>
        ) : (
          <>
            {data.confirmed_count > 0 && (
              <section className="space-y-2">
                <h2 className="text-xs font-medium text-gray-400 uppercase tracking-wide">
                  Confirmed today
                </h2>
                {data.confirmed_items.map((item) => (
                  <ReviewItemCard
                    key={item.id}
                    item={item}
                    timestampLabel="confirmed"
                    timestamp={item.reviewed_at!}
                  />
                ))}
              </section>
            )}

            {data.rejected_count > 0 && (
              <section className="space-y-2">
                <h2 className="text-xs font-medium text-gray-400 uppercase tracking-wide">
                  Rejected today
                </h2>
                {data.rejected_items.map((item) => (
                  <ReviewItemCard
                    key={item.id}
                    item={item}
                    timestampLabel="rejected"
                    timestamp={item.reviewed_at!}
                  />
                ))}
              </section>
            )}

            {data.pending_count > 0 && (
              <section className="space-y-2">
                <h2 className="text-xs font-medium text-gray-400 uppercase tracking-wide">
                  Pending review
                </h2>
                {data.pending_items.map((item) => (
                  <ReviewItemCard
                    key={item.id}
                    item={item}
                    timestampLabel="captured"
                    timestamp={item.created_at}
                  />
                ))}
              </section>
            )}
          </>
        )}
      </div>
    </main>
  );
}
