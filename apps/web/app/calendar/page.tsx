import Link from "next/link";
import type { CalendarIntent, CalendarIntentsResponse } from "./types";
import { authedFetch } from "@/lib/api";

// Always render at request time — never pre-render at build; requires live token + data.
export const dynamic = "force-dynamic";

async function getCalendarIntents(): Promise<CalendarIntentsResponse> {
  const res = await authedFetch("/calendar_intents", {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Backend returned ${res.status}: ${res.statusText}`);
  }

  return res.json();
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-SG", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function CalendarIntentCard({ intent }: { intent: CalendarIntent }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <p className="font-medium text-gray-900 leading-snug">{intent.title}</p>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500 mt-2">
        {intent.proposed_datetime && (
          <span>&#128197; {intent.proposed_datetime}</span>
        )}
        {intent.location && <span>&#128205; {intent.location}</span>}
      </div>
      {intent.notes && (
        <p className="text-xs text-gray-400 mt-2">{intent.notes}</p>
      )}
      <p className="text-xs text-gray-300 mt-2">confirmed {formatDate(intent.created_at)}</p>
    </div>
  );
}

export default async function CalendarPage() {
  const data = await getCalendarIntents();

  return (
    <main className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <Link href="/" className="text-sm text-gray-400 hover:text-gray-600">
            ← Home
          </Link>
          <h1 className="text-2xl font-semibold text-gray-900 mt-2">
            Calendar Intents
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {data.total === 0
              ? "No calendar intents confirmed yet"
              : `${data.total} confirmed intention${data.total !== 1 ? "s" : ""}`}
          </p>
        </div>

        {data.total === 0 ? (
          <div className="bg-white border border-gray-200 rounded-xl p-12 text-center">
            <p className="text-gray-400 text-sm">No calendar intents confirmed yet.</p>
            <p className="text-gray-400 text-sm mt-1">
              Confirm a calendar item in the inbox to see it here.
            </p>
          </div>
        ) : (
          <section className="space-y-2">
            <h2 className="text-xs font-medium text-gray-400 uppercase tracking-wide">
              Confirmed intentions
            </h2>
            {data.items.map((intent) => (
              <CalendarIntentCard key={intent.id} intent={intent} />
            ))}
          </section>
        )}
      </div>
    </main>
  );
}
