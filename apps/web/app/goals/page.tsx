import type { GoalsResponse } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState } from "@/components/ui";
import { GoalCard } from "./GoalCard";

export const dynamic = "force-dynamic";

// Returns null on backend failure (cold-start 503, or before migration 0015) so the page
// renders a soft message instead of a server-side crash. Auth redirects still propagate.
async function getGoals(): Promise<GoalsResponse | null> {
  try {
    const res = await authedFetch("/goals", { cache: "no-store" });
    return res.ok ? ((await res.json()) as GoalsResponse) : null;
  } catch (e) {
    const digest = (e as { digest?: string })?.digest;
    if (typeof digest === "string" && digest.startsWith("NEXT_REDIRECT")) throw e;
    return null;
  }
}

export default async function GoalsPage() {
  const data = await getGoals();

  if (data === null) {
    return (
      <PageContainer>
        <PageHeader title="Goals" subtitle="Couldn't load goals" />
        <EmptyState>
          Goals are unavailable right now. If this persists, the database migration (0015) may
          not be applied yet.
        </EmptyState>
      </PageContainer>
    );
  }

  // Active goals first, then achieved, then abandoned; stable within each by API order.
  const order = { active: 0, achieved: 1, abandoned: 2 } as const;
  const items = [...data.items].sort(
    (a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3)
  );
  const activeCount = data.items.filter((g) => g.status === "active").length;

  return (
    <PageContainer>
      <PageHeader
        title="Goals"
        subtitle={
          data.total === 0
            ? "No goals yet"
            : `${activeCount} active · ${data.total} total`
        }
      />
      {data.total === 0 ? (
        <EmptyState>
          Send a goal to your Telegram bot (e.g. &ldquo;reach 100k portfolio by end 2027&rdquo;),
          then confirm it here.
        </EmptyState>
      ) : (
        <div className="space-y-2">
          {items.map((g) => (
            <GoalCard key={g.id} goal={g} />
          ))}
        </div>
      )}
    </PageContainer>
  );
}
