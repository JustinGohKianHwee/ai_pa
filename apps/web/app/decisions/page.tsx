import type { DecisionsResponse } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState } from "@/components/ui";
import { DecisionCard } from "./DecisionCard";

export const dynamic = "force-dynamic";

// Returns null on backend failure (cold-start 503, or before migration 0016) so the page
// renders a soft message instead of a server-side crash. Auth redirects still propagate.
async function getDecisions(): Promise<DecisionsResponse | null> {
  try {
    const res = await authedFetch("/decisions", { cache: "no-store" });
    return res.ok ? ((await res.json()) as DecisionsResponse) : null;
  } catch (e) {
    const digest = (e as { digest?: string })?.digest;
    if (typeof digest === "string" && digest.startsWith("NEXT_REDIRECT")) throw e;
    return null;
  }
}

export default async function DecisionsPage() {
  const data = await getDecisions();

  if (data === null) {
    return (
      <PageContainer>
        <PageHeader title="Decisions" subtitle="Couldn't load decisions" />
        <EmptyState>
          Decisions are unavailable right now. If this persists, the database migration (0016)
          may not be applied yet.
        </EmptyState>
      </PageContainer>
    );
  }

  // Active first, then reversed, then archived; stable within each by API order.
  const order = { active: 0, reversed: 1, archived: 2 } as const;
  const items = [...data.items].sort(
    (a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3)
  );
  const activeCount = data.items.filter((d) => d.status === "active").length;

  return (
    <PageContainer>
      <PageHeader
        title="Decisions"
        subtitle={
          data.total === 0
            ? "No decisions logged yet"
            : `${activeCount} active · ${data.total} total`
        }
      />
      {data.total === 0 ? (
        <EmptyState>
          Send a decision to your Telegram bot (e.g. &ldquo;Decision: choose term insurance over
          whole life because I want pure protection&rdquo;), then confirm it here.
        </EmptyState>
      ) : (
        <div className="space-y-2">
          {items.map((d) => (
            <DecisionCard key={d.id} decision={d} />
          ))}
        </div>
      )}
    </PageContainer>
  );
}
