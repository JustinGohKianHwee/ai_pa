import type { FoodLog, FoodLogsResponse } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState, Badge } from "@/components/ui";
import { fmtDateTime, fmtInt } from "@/lib/format";

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

function MacroStat({ label, value, unit }: { label: string; value: number; unit: string }) {
  return (
    <div>
      <p className="numeric text-lg font-medium text-fg">
        {fmtInt(value)}
        <span className="text-xs text-faint"> {unit}</span>
      </p>
      <p className="text-xs text-muted">{label}</p>
    </div>
  );
}

function FoodLogCard({ log }: { log: FoodLog }) {
  const hasMacros = log.protein_g != null || log.carbs_g != null || log.fat_g != null;
  return (
    <div className="flex gap-4 rounded-xl border border-border bg-surface p-4">
      {log.image_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={log.image_url}
          alt={log.description}
          className="h-16 w-16 shrink-0 rounded-lg border border-border object-cover"
        />
      ) : null}
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <p className="font-medium leading-snug text-fg">{log.description}</p>
          {log.meal_type ? (
            <Badge tone="warning" dot={false}>
              {MEAL_TYPE_LABELS[log.meal_type] ?? log.meal_type}
            </Badge>
          ) : null}
        </div>
        <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
          {log.calories != null ? (
            <span className="numeric font-medium text-fg">{fmtInt(log.calories)} kcal</span>
          ) : null}
          {hasMacros ? (
            <span className="numeric text-xs text-muted">
              P {fmtInt(log.protein_g ?? 0)} · C {fmtInt(log.carbs_g ?? 0)} · F{" "}
              {fmtInt(log.fat_g ?? 0)}
            </span>
          ) : null}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
          {log.logged_at ? <span>logged: {log.logged_at}</span> : null}
          <span>{fmtDateTime(log.created_at)}</span>
        </div>
      </div>
    </div>
  );
}

export default async function FoodPage() {
  const data = await getFoodLogs();
  const t = data.totals;

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
        <EmptyState>
          Send a food photo or text to your Telegram bot, then confirm it here.
        </EmptyState>
      ) : (
        <div className="space-y-6">
          <div className="rounded-xl border border-border bg-surface p-5">
            <p className="text-xs font-medium uppercase tracking-wider text-faint">Today</p>
            <p className="numeric mt-2 text-3xl font-medium text-fg">
              {fmtInt(t.calories)} <span className="text-base text-muted">kcal</span>
            </p>
            <div className="mt-4 grid grid-cols-3 gap-4 border-t border-border pt-4">
              <MacroStat label="protein" value={t.protein_g} unit="g" />
              <MacroStat label="carbs" value={t.carbs_g} unit="g" />
              <MacroStat label="fat" value={t.fat_g} unit="g" />
            </div>
          </div>

          <section className="space-y-2">
            {data.items.map((log) => (
              <FoodLogCard key={log.id} log={log} />
            ))}
          </section>
        </div>
      )}
    </PageContainer>
  );
}
