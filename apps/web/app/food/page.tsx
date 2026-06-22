import type { FoodLog, FoodLogsResponse } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState, Badge } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";

export const dynamic = "force-dynamic";

async function getFoodLogs(): Promise<FoodLogsResponse> {
  const res = await authedFetch("/food_logs?date=today", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Backend returned ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

const MEAL_TYPE_LABELS: Record<string, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
  snack: "Snack",
};

function FoodLogCard({ log }: { log: FoodLog }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium leading-snug text-fg">{log.description}</p>
        {log.meal_type ? (
          <Badge tone="warning" dot={false}>
            {MEAL_TYPE_LABELS[log.meal_type] ?? log.meal_type}
          </Badge>
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
        {log.logged_at ? <span>logged: {log.logged_at}</span> : null}
        <span>{fmtDateTime(log.created_at)}</span>
      </div>
    </div>
  );
}

export default async function FoodPage() {
  const data = await getFoodLogs();

  return (
    <PageContainer>
      <PageHeader
        title="Food"
        subtitle={
          data.total === 0
            ? "No meals logged today"
            : `${data.total} meal${data.total !== 1 ? "s" : ""} today`
        }
      />
      {data.total === 0 ? (
        <EmptyState>Confirm a food item in the inbox to see it here.</EmptyState>
      ) : (
        <section className="space-y-2">
          {data.items.map((log) => (
            <FoodLogCard key={log.id} log={log} />
          ))}
        </section>
      )}
    </PageContainer>
  );
}
