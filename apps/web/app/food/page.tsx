import Link from "next/link";
import type { FoodLog, FoodLogsResponse } from "./types";

// Always render at request time — never pre-render at build; requires live token + data.
export const dynamic = "force-dynamic";

async function getFoodLogs(): Promise<FoodLogsResponse> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const token = process.env.DEV_ADMIN_TOKEN;

  if (!token) {
    throw new Error(
      "DEV_ADMIN_TOKEN is not configured. Add it to apps/web/.env.local."
    );
  }

  const res = await fetch(`${apiUrl}/food_logs?date=today`, {
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

const MEAL_TYPE_LABELS: Record<string, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
  snack: "Snack",
};

function FoodLogCard({ log }: { log: FoodLog }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium text-gray-900 leading-snug">{log.description}</p>
        {log.meal_type && (
          <span className="shrink-0 text-xs font-medium bg-green-100 text-green-800 px-2 py-0.5 rounded-full">
            {MEAL_TYPE_LABELS[log.meal_type] ?? log.meal_type}
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-400 mt-2">
        {log.logged_at && <span>logged: {log.logged_at}</span>}
        <span>{formatDate(log.created_at)}</span>
      </div>
    </div>
  );
}

export default async function FoodPage() {
  const data = await getFoodLogs();

  return (
    <main className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <Link href="/" className="text-sm text-gray-400 hover:text-gray-600">
            ← Home
          </Link>
          <h1 className="text-2xl font-semibold text-gray-900 mt-2">Food</h1>
          <p className="mt-1 text-sm text-gray-500">
            {data.total === 0
              ? "No meals logged today"
              : `${data.total} meal${data.total !== 1 ? "s" : ""} today`}
          </p>
        </div>

        {data.total === 0 ? (
          <div className="bg-white border border-gray-200 rounded-xl p-12 text-center">
            <p className="text-gray-400 text-sm">No meals logged today.</p>
            <p className="text-gray-400 text-sm mt-1">
              Confirm a food item in the inbox to see it here.
            </p>
          </div>
        ) : (
          <section className="space-y-2">
            <h2 className="text-xs font-medium text-gray-400 uppercase tracking-wide">
              Today&apos;s meals
            </h2>
            {data.items.map((log) => (
              <FoodLogCard key={log.id} log={log} />
            ))}
          </section>
        )}
      </div>
    </main>
  );
}
