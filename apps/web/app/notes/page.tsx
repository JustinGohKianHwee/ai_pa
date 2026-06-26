import type { NotesResponse } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState, Badge } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";

export const dynamic = "force-dynamic";

// Returns null on backend failure (cold-start 503, or before migration 0020) so the page renders
// a soft message instead of a server-side crash. Auth redirects still propagate.
async function getNotes(q: string): Promise<NotesResponse | null> {
  try {
    const path = q ? `/notes?q=${encodeURIComponent(q)}` : "/notes";
    const res = await authedFetch(path, { cache: "no-store" });
    return res.ok ? ((await res.json()) as NotesResponse) : null;
  } catch (e) {
    const digest = (e as { digest?: string })?.digest;
    if (typeof digest === "string" && digest.startsWith("NEXT_REDIRECT")) throw e;
    return null;
  }
}

export default async function NotesPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const term = (q ?? "").trim();
  const data = await getNotes(term);

  const search = (
    <form method="get" className="mb-4 flex gap-2">
      <input
        type="search"
        name="q"
        defaultValue={term}
        placeholder="Search notes…"
        aria-label="Search notes"
        className="w-full max-w-sm rounded-lg border border-border bg-bg px-3 py-1.5 text-sm text-fg outline-none focus-visible:ring-2 focus-visible:ring-accent"
      />
      <button
        type="submit"
        className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition-colors hover:bg-surface-raised hover:text-fg"
      >
        Search
      </button>
    </form>
  );

  if (data === null) {
    return (
      <PageContainer>
        <PageHeader title="Notes" subtitle="Couldn't load notes" />
        <EmptyState>
          Notes are unavailable right now. If this persists, the database migration (0020) may not
          be applied yet.
        </EmptyState>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title="Notes"
        subtitle={data.total === 0 ? "No notes" : `${data.total} note${data.total === 1 ? "" : "s"}`}
      />
      {search}
      {data.total === 0 ? (
        <EmptyState>
          {term
            ? `No notes match “${term}”.`
            : "Send a note to your Telegram bot (e.g. “note: call the plumber #home”), then confirm it here."}
        </EmptyState>
      ) : (
        <div className="space-y-2">
          {data.items.map((n) => (
            <div key={n.id} className="rounded-xl border border-border bg-surface p-4">
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">{n.content}</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {n.tags.map((t) => (
                  <Badge key={t} tone="neutral" dot={false}>
                    #{t}
                  </Badge>
                ))}
                <span className="text-xs text-faint">{fmtDateTime(n.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </PageContainer>
  );
}
