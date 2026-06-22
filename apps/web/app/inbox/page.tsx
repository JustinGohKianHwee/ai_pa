import Link from "next/link";
import type { InboxItem, InboxResponse } from "./types";
import { InboxCard } from "./InboxCard";
import { authedFetch } from "@/lib/api";

// Always render at request time — never pre-render at build; requires live token + data.
export const dynamic = "force-dynamic";

async function getInboxItems(): Promise<InboxItem[]> {
  const res = await authedFetch("/inbox", {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Backend returned ${res.status}: ${res.statusText}`);
  }

  const data: InboxResponse = await res.json();
  return data.items;
}

export default async function InboxPage() {
  const items = await getInboxItems();

  return (
    <main className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <Link
            href="/"
            className="inline-flex text-sm text-gray-400 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 focus-visible:ring-offset-2 rounded"
          >
            &larr; Home
          </Link>
          <h1 className="text-2xl font-semibold text-gray-900 mt-2">Inbox</h1>
          <p className="mt-1 text-sm text-gray-500">
            {items.length === 0
              ? "No pending items"
              : `${items.length} item${items.length !== 1 ? "s" : ""} awaiting review`}
          </p>
        </div>

        {items.length === 0 ? (
          <div className="bg-white border border-gray-200 rounded-xl p-12 text-center">
            <p className="text-gray-400 text-sm">
              No inbox items yet.
            </p>
            <p className="text-gray-400 text-sm mt-1">
              Send a message to your Telegram bot to get started.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {items.map((item) => (
              <InboxCard key={item.id} item={item} />
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
