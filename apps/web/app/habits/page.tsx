import type { Habit, HabitsResponse } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState, Badge } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";

export const dynamic = "force-dynamic";

// Returns null on backend failure (cold-start 503, or before migration 0015) so the page
// renders a soft message instead of a server-side crash. Auth redirects still propagate.
async function getHabits(): Promise<HabitsResponse | null> {
  try {
    const res = await authedFetch("/habits", { cache: "no-store" });
    return res.ok ? ((await res.json()) as HabitsResponse) : null;
  } catch (e) {
    const digest = (e as { digest?: string })?.digest;
    if (typeof digest === "string" && digest.startsWith("NEXT_REDIRECT")) throw e;
    return null;
  }
}

function HabitCard({ habit }: { habit: Habit }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium leading-snug text-fg">{habit.name}</p>
        {habit.cadence ? (
          <Badge tone="info" dot={false}>
            {habit.cadence}
          </Badge>
        ) : null}
      </div>
      {habit.target ? (
        <p className="mt-1.5 text-sm text-muted">Target: {habit.target}</p>
      ) : null}
      {habit.notes ? <p className="mt-1 text-sm text-muted">{habit.notes}</p> : null}
      <p className="mt-2 text-xs text-faint">{fmtDateTime(habit.created_at)}</p>
    </div>
  );
}

export default async function HabitsPage() {
  const data = await getHabits();

  if (data === null) {
    return (
      <PageContainer>
        <PageHeader title="Habits" subtitle="Couldn't load habits" />
        <EmptyState>
          Habits are unavailable right now. If this persists, the database migration (0015) may
          not be applied yet.
        </EmptyState>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title="Habits"
        subtitle={
          data.total === 0
            ? "No habits yet"
            : `${data.total} habit${data.total !== 1 ? "s" : ""}`
        }
      />
      {data.total === 0 ? (
        <EmptyState>
          Send a habit to your Telegram bot (e.g. &ldquo;meditate every morning&rdquo;), then
          confirm it here.
        </EmptyState>
      ) : (
        <div className="space-y-2">
          {data.items.map((h) => (
            <HabitCard key={h.id} habit={h} />
          ))}
        </div>
      )}
    </PageContainer>
  );
}
