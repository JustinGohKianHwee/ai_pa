import type { JournalResponse } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState, Badge } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";

export const dynamic = "force-dynamic";

// Returns null on backend failure (cold-start 503, or before migration 0020) so the page renders
// a soft message instead of a server-side crash. Auth redirects still propagate.
async function getJournal(): Promise<JournalResponse | null> {
  try {
    const res = await authedFetch("/journal", { cache: "no-store" });
    return res.ok ? ((await res.json()) as JournalResponse) : null;
  } catch (e) {
    const digest = (e as { digest?: string })?.digest;
    if (typeof digest === "string" && digest.startsWith("NEXT_REDIRECT")) throw e;
    return null;
  }
}

export default async function JournalPage() {
  const data = await getJournal();

  if (data === null) {
    return (
      <PageContainer>
        <PageHeader title="Journal" subtitle="Couldn't load journal" />
        <EmptyState>
          The journal is unavailable right now. If this persists, the database migration (0020) may
          not be applied yet.
        </EmptyState>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title="Journal"
        subtitle={
          data.total === 0 ? "No entries" : `${data.total} entr${data.total === 1 ? "y" : "ies"}`
        }
      />
      {data.total === 0 ? (
        <EmptyState>
          Send a reflective entry to your Telegram bot (e.g. “journal: felt good after the run
          today”), then confirm it here.
        </EmptyState>
      ) : (
        <div className="space-y-2">
          {data.items.map((j) => (
            <div key={j.id} className="rounded-xl border border-border bg-surface p-4">
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">{j.content}</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {j.mood ? (
                  <Badge tone="accent" dot={false}>
                    {j.mood}
                  </Badge>
                ) : null}
                <span className="text-xs text-faint">{fmtDateTime(j.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </PageContainer>
  );
}
