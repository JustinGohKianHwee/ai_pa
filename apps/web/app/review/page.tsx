import type { CaptureSummary, DailyReview, InboxItemSummary } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState, Badge, SectionLabel } from "@/components/ui";
import { fmtDateTime, fmtInt, type Tone } from "@/lib/format";

export const dynamic = "force-dynamic";

async function getDailyReview(): Promise<DailyReview> {
  const res = await authedFetch("/daily_review?date=today", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Backend returned ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

const TYPE_LABELS: Record<string, string> = {
  task: "Task",
  finance: "Finance",
  food: "Food",
  calendar: "Calendar",
  note: "Note",
  journal: "Journal",
  investment: "Investment",
  other: "Other",
};
const TYPE_TONE: Record<string, Tone> = {
  task: "info",
  finance: "positive",
  food: "warning",
  calendar: "accent",
};

function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? "Item";
}
function typeTone(type: string): Tone {
  return TYPE_TONE[type] ?? "neutral";
}

function StatTile({
  label,
  count,
  tone = "fg",
}: {
  label: string;
  count: number;
  tone?: "fg" | "positive" | "negative" | "warning";
}) {
  const color =
    tone === "positive"
      ? "text-positive"
      : tone === "negative"
        ? "text-negative"
        : tone === "warning"
          ? "text-warning"
          : "text-fg";
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <p className={`numeric text-2xl font-medium ${color}`}>{fmtInt(count)}</p>
      <p className="mt-1 text-xs text-muted">{label}</p>
    </div>
  );
}

function ReviewRow({
  title,
  type,
  label,
  timestamp,
  timeZone,
}: {
  title: string | null;
  type: string;
  label: string;
  timestamp: string;
  timeZone: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-xl border border-border bg-surface p-4">
      <div className="min-w-0">
        <p className="text-sm leading-snug text-fg">
          {title ?? <span className="italic text-faint">Untitled</span>}
        </p>
        <p className="mt-1 text-xs text-faint">
          {label}: {fmtDateTime(timestamp, timeZone)}
        </p>
      </div>
      <Badge tone={typeTone(type)}>{typeLabel(type)}</Badge>
    </div>
  );
}

export default async function ReviewPage() {
  const data = await getDailyReview();

  const isEmpty =
    data.captured_count === 0 && data.confirmed_count === 0 && data.rejected_count === 0;
  const byType = Object.entries(data.confirmed_by_type).filter(([, n]) => n > 0);

  return (
    <PageContainer>
      <PageHeader
        title="Daily review"
        subtitle={
          <span className="flex items-center gap-2">
            {data.review_date}
            <Badge tone="neutral" dot={false}>
              {data.timezone}
            </Badge>
          </span>
        }
      />

      {data.summary ? <p className="mb-6 text-sm text-muted">{data.summary}</p> : null}

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="captured" count={data.captured_count} />
        <StatTile label="confirmed" count={data.confirmed_count} tone="positive" />
        <StatTile label="rejected" count={data.rejected_count} tone="negative" />
        <StatTile label="pending" count={data.pending_count} tone="warning" />
      </div>

      {byType.length > 0 ? (
        <div className="mb-8 flex flex-wrap gap-2">
          {byType.map(([type, count]) => (
            <Badge key={type} tone={typeTone(type)}>
              {typeLabel(type)} {count}
            </Badge>
          ))}
        </div>
      ) : null}

      {isEmpty ? (
        <EmptyState>
          Nothing captured or reviewed today. Send a message via Telegram to get started.
        </EmptyState>
      ) : (
        <div className="space-y-8">
          {data.confirmed_count > 0 ? (
            <section>
              <SectionLabel>Confirmed today</SectionLabel>
              <div className="space-y-2">
                {data.confirmed_items.map((item: InboxItemSummary) => (
                  <ReviewRow
                    key={item.id}
                    title={item.title}
                    type={item.item_type}
                    label="confirmed"
                    timestamp={item.reviewed_at!}
                    timeZone={data.timezone}
                  />
                ))}
              </div>
            </section>
          ) : null}

          {data.rejected_count > 0 ? (
            <section>
              <SectionLabel>Rejected today</SectionLabel>
              <div className="space-y-2">
                {data.rejected_items.map((item: InboxItemSummary) => (
                  <ReviewRow
                    key={item.id}
                    title={item.title}
                    type={item.item_type}
                    label="rejected"
                    timestamp={item.reviewed_at!}
                    timeZone={data.timezone}
                  />
                ))}
              </div>
            </section>
          ) : null}

          {data.pending_count > 0 ? (
            <section>
              <SectionLabel>Pending review</SectionLabel>
              <div className="space-y-2">
                {data.pending_items.map((item: CaptureSummary) => (
                  <ReviewRow
                    key={item.capture_id}
                    title={item.title}
                    type={item.item_type ?? "unknown"}
                    label="captured"
                    timestamp={item.captured_at}
                    timeZone={data.timezone}
                  />
                ))}
              </div>
            </section>
          ) : null}
        </div>
      )}
    </PageContainer>
  );
}
