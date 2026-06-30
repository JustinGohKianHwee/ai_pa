import type { ReflectionResponse } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState } from "@/components/ui";

export const dynamic = "force-dynamic";

async function getReflection(): Promise<ReflectionResponse | null> {
  try {
    const res = await authedFetch("/reflection", { cache: "no-store" });
    return res.ok ? ((await res.json()) as ReflectionResponse) : null;
  } catch (e) {
    const digest = (e as { digest?: string })?.digest;
    if (typeof digest === "string" && digest.startsWith("NEXT_REDIRECT")) throw e;
    return null;
  }
}

function List({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-wider text-faint">{title}</p>
      {items.length > 0 ? (
        <ul className="mt-2 space-y-1 text-sm text-fg">
          {items.map((s, i) => (
            <li key={i}>• {s}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-muted">{empty}</p>
      )}
    </div>
  );
}

export default async function ReflectionPage() {
  const data = await getReflection();

  if (data === null) {
    return (
      <PageContainer>
        <PageHeader title="Weekly reflection" subtitle="Couldn't load the reflection" />
        <EmptyState>
          The reflection is unavailable right now. If this persists, the database migration (0022)
          may not be applied yet, or USER_TIMEZONE may be unset.
        </EmptyState>
      </PageContainer>
    );
  }

  const r = data.reflection;

  return (
    <PageContainer className="max-w-3xl">
      <PageHeader title="Weekly reflection" subtitle={`${r.week_start} → ${r.week_end}`} />

      <div className="space-y-4">
        <List title="Wins" items={r.wins} empty="Nothing logged yet this week." />
        <List title="Concerns" items={r.concerns} empty="No concerns flagged." />
        <List title="Trends vs last week" items={r.trends} empty="Not enough data to compare." />

        <div className="rounded-xl border border-border bg-surface p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-faint">
            Active goals
          </p>
          {r.progress.length > 0 ? (
            <ul className="mt-2 space-y-1.5 text-sm text-fg">
              {r.progress.map((g) => (
                <li key={g.id} className="flex items-center justify-between gap-3">
                  <span>{g.title ?? "(untitled goal)"}</span>
                  <span className="text-xs text-faint">
                    {[g.target, g.target_date].filter(Boolean).join(" · ")}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted">No active goals.</p>
          )}
        </div>
      </div>
    </PageContainer>
  );
}
