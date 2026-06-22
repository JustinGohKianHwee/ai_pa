import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState } from "@/components/ui";
import { InboxCard } from "./InboxCard";
import type { InboxItem, InboxResponse } from "./types";

// Always render at request time — never pre-render at build; requires live token + data.
export const dynamic = "force-dynamic";

async function getInboxItems(): Promise<InboxItem[]> {
  const res = await authedFetch("/inbox", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Backend returned ${res.status}: ${res.statusText}`);
  }
  const data: InboxResponse = await res.json();
  return data.items;
}

export default async function InboxPage() {
  const items = await getInboxItems();

  return (
    <PageContainer>
      <PageHeader
        title="Inbox"
        subtitle={
          items.length === 0
            ? "No pending items"
            : `${items.length} item${items.length !== 1 ? "s" : ""} awaiting review`
        }
      />

      {items.length === 0 ? (
        <EmptyState>
          No inbox items yet. Send a message to your Telegram bot to get started.
        </EmptyState>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <InboxCard key={item.id} item={item} />
          ))}
        </div>
      )}
    </PageContainer>
  );
}
