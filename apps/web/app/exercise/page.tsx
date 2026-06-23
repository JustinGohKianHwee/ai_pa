import type { ExerciseLog, ExerciseLogsResponse } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState, Badge } from "@/components/ui";
import { fmtDateTime, fmtInt, fmtNum } from "@/lib/format";

export const dynamic = "force-dynamic";

// Returns null on backend failure (e.g. a cold-start 503, or before migration 0013 is
// applied) so the page renders a soft message instead of a server-side crash. Auth
// redirects (401 -> /login) still propagate.
async function getExerciseLogs(): Promise<ExerciseLogsResponse | null> {
  try {
    const res = await authedFetch("/exercise_logs?date=today", { cache: "no-store" });
    return res.ok ? ((await res.json()) as ExerciseLogsResponse) : null;
  } catch (e) {
    const digest = (e as { digest?: string })?.digest;
    if (typeof digest === "string" && digest.startsWith("NEXT_REDIRECT")) throw e;
    return null;
  }
}

function TotalStat({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <div>
      <p className="numeric text-lg font-medium text-fg">
        {value}
        <span className="text-xs text-faint"> {unit}</span>
      </p>
      <p className="text-xs text-muted">{label}</p>
    </div>
  );
}

function ExerciseLogCard({ log }: { log: ExerciseLog }) {
  const hasSetsReps = log.sets != null || log.reps != null;
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium leading-snug text-fg">{log.activity}</p>
        {log.intensity ? (
          <Badge tone="info" dot={false}>
            {log.intensity}
          </Badge>
        ) : null}
      </div>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
        {log.duration_min != null ? (
          <span className="numeric font-medium text-fg">{fmtInt(log.duration_min)} min</span>
        ) : null}
        {log.distance_km != null ? (
          <span className="numeric text-muted">{fmtNum(log.distance_km)} km</span>
        ) : null}
        {hasSetsReps ? (
          <span className="numeric text-xs text-muted">
            {fmtInt(log.sets ?? 0)} × {fmtInt(log.reps ?? 0)}
          </span>
        ) : null}
        {log.calories != null ? (
          <span className="numeric text-xs text-muted">{fmtInt(log.calories)} kcal</span>
        ) : null}
      </div>
      {log.notes ? <p className="mt-2 text-sm text-muted">{log.notes}</p> : null}
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
        {log.logged_at ? <span>logged: {log.logged_at}</span> : null}
        <span>{fmtDateTime(log.created_at)}</span>
      </div>
    </div>
  );
}

export default async function ExercisePage() {
  const data = await getExerciseLogs();

  if (data === null) {
    return (
      <PageContainer>
        <PageHeader title="Exercise" subtitle="Couldn't load workouts" />
        <EmptyState>
          Exercise data is unavailable right now. If this persists, the database migration
          (0013) may not be applied yet.
        </EmptyState>
      </PageContainer>
    );
  }

  const t = data.totals;

  return (
    <PageContainer>
      <PageHeader
        title="Exercise"
        subtitle={
          data.total === 0
            ? "No workouts logged today"
            : `${data.total} workout${data.total !== 1 ? "s" : ""} today`
        }
      />

      {data.total === 0 ? (
        <EmptyState>
          Send a workout to your Telegram bot (e.g. &ldquo;ran 5k in 28 min&rdquo;), then confirm
          it here.
        </EmptyState>
      ) : (
        <div className="space-y-6">
          <div className="rounded-xl border border-border bg-surface p-5">
            <p className="text-xs font-medium uppercase tracking-wider text-faint">Today</p>
            <div className="mt-3 grid grid-cols-3 gap-4">
              <TotalStat label="duration" value={fmtInt(t.duration_min)} unit="min" />
              <TotalStat label="distance" value={fmtNum(t.distance_km)} unit="km" />
              <TotalStat label="burned" value={fmtInt(t.calories)} unit="kcal" />
            </div>
          </div>

          <section className="space-y-2">
            {data.items.map((log) => (
              <ExerciseLogCard key={log.id} log={log} />
            ))}
          </section>
        </div>
      )}
    </PageContainer>
  );
}
