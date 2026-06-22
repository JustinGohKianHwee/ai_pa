import { CalendarDays, MapPin } from "lucide-react";
import type { CalendarIntent, CalendarIntentsResponse } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";

export const dynamic = "force-dynamic";

async function getCalendarIntents(): Promise<CalendarIntentsResponse> {
  const res = await authedFetch("/calendar_intents", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Backend returned ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

function CalendarIntentCard({ intent }: { intent: CalendarIntent }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <p className="font-medium leading-snug text-fg">{intent.title}</p>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {intent.proposed_datetime ? (
          <span className="inline-flex items-center gap-1.5">
            <CalendarDays size={14} aria-hidden />
            {intent.proposed_datetime}
          </span>
        ) : null}
        {intent.location ? (
          <span className="inline-flex items-center gap-1.5">
            <MapPin size={14} aria-hidden />
            {intent.location}
          </span>
        ) : null}
      </div>
      {intent.notes ? <p className="mt-2 text-xs text-faint">{intent.notes}</p> : null}
      <p className="mt-2 text-xs text-faint">confirmed {fmtDateTime(intent.created_at)}</p>
    </div>
  );
}

export default async function CalendarPage() {
  const data = await getCalendarIntents();

  return (
    <PageContainer>
      <PageHeader
        title="Calendar intents"
        subtitle={
          data.total === 0
            ? "No calendar intents confirmed yet"
            : `${data.total} confirmed intention${data.total !== 1 ? "s" : ""}`
        }
      />
      {data.total === 0 ? (
        <EmptyState>Confirm a calendar item in the inbox to see it here.</EmptyState>
      ) : (
        <section className="space-y-2">
          {data.items.map((intent) => (
            <CalendarIntentCard key={intent.id} intent={intent} />
          ))}
        </section>
      )}
    </PageContainer>
  );
}
