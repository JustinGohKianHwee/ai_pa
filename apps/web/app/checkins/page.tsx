import type { Checkin, CheckinsResponse } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState, Badge } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";

export const dynamic = "force-dynamic";

// Returns null on backend failure (cold-start 503, or before migration 0021) so the page renders
// a soft message instead of a server-side crash. Auth redirects still propagate.
async function getCheckins(): Promise<CheckinsResponse | null> {
  try {
    const res = await authedFetch("/checkins", { cache: "no-store" });
    return res.ok ? ((await res.json()) as CheckinsResponse) : null;
  } catch (e) {
    const digest = (e as { digest?: string })?.digest;
    if (typeof digest === "string" && digest.startsWith("NEXT_REDIRECT")) throw e;
    return null;
  }
}

function metrics(c: Checkin): string {
  return [
    c.energy != null ? `energy ${c.energy}/5` : null,
    c.stress != null ? `stress ${c.stress}/5` : null,
    c.sleep_hours != null ? `${c.sleep_hours}h sleep` : null,
    c.activity ? c.activity : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

export default async function CheckinsPage() {
  const data = await getCheckins();

  if (data === null) {
    return (
      <PageContainer>
        <PageHeader title="Check-ins" subtitle="Couldn't load check-ins" />
        <EmptyState>
          Check-ins are unavailable right now. If this persists, the database migration (0021) may
          not be applied yet.
        </EmptyState>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title="Check-ins"
        subtitle={
          data.total === 0 ? "No check-ins" : `${data.total} check-in${data.total === 1 ? "" : "s"}`
        }
      />
      <p className="mb-3 text-xs text-faint">
        A personal wellbeing log — not medical advice.
      </p>
      {data.total === 0 ? (
        <EmptyState>
          Send a daily check-in to your Telegram bot (e.g. “energy 4/5, slept 7h, a bit stressed,
          went for a walk”), then confirm it here.
        </EmptyState>
      ) : (
        <div className="space-y-2">
          {data.items.map((c) => (
            <div key={c.id} className="rounded-xl border border-border bg-surface p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="numeric text-sm text-fg">{metrics(c) || "Check-in"}</p>
                {c.mood ? (
                  <Badge tone="accent" dot={false}>
                    {c.mood}
                  </Badge>
                ) : null}
              </div>
              {c.notes ? (
                <p className="mt-1 text-sm leading-relaxed text-muted">{c.notes}</p>
              ) : null}
              <p className="mt-2 text-xs text-faint">
                {c.as_of ? `${c.as_of} · ` : ""}
                {fmtDateTime(c.created_at)}
              </p>
            </div>
          ))}
        </div>
      )}
    </PageContainer>
  );
}
