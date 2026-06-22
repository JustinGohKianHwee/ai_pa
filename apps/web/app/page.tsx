import Link from "next/link";

export default function Home() {
  const pipeline = [
    { label: "Capture", detail: "Telegram text → raw capture_event stored" },
    { label: "Classify & extract", detail: "OpenAI assigns type and structured data (Phase 6)" },
    { label: "Pending inbox", detail: "Awaiting your review" },
    { label: "Review", detail: "Confirm or reject each item (Phase 7)" },
    { label: "Domain record", detail: "Confirmed tasks, expenses, food logs & calendar intents become records (Phase 8–12)", active: true },
  ];

  return (
    <main className="min-h-screen bg-gray-50 flex flex-col items-center justify-center p-8">
      <div className="max-w-lg w-full space-y-4">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
          <div className="mb-6">
            <span className="inline-block bg-green-100 text-green-800 text-xs font-medium px-2.5 py-1 rounded-full">
              Phase 14 — Portfolio
            </span>
          </div>

          <h1 className="text-2xl font-semibold text-gray-900 mb-2">
            AI Personal Assistant
          </h1>
          <p className="text-gray-500 text-sm">
            Private review-first personal operating system.
          </p>
        </div>

        <Link
          href="/inbox"
          className="flex items-center justify-between bg-white rounded-xl shadow-sm border border-gray-200 p-6 hover:border-gray-300 hover:shadow transition group"
        >
          <div>
            <p className="font-medium text-gray-900 group-hover:text-gray-700">Inbox</p>
            <p className="text-sm text-gray-400 mt-0.5">Pending items awaiting review</p>
          </div>
          <span className="text-gray-300 group-hover:text-gray-400 text-lg">→</span>
        </Link>

        <Link
          href="/tasks"
          className="flex items-center justify-between bg-white rounded-xl shadow-sm border border-gray-200 p-6 hover:border-gray-300 hover:shadow transition group"
        >
          <div>
            <p className="font-medium text-gray-900 group-hover:text-gray-700">Tasks</p>
            <p className="text-sm text-gray-400 mt-0.5">Confirmed tasks, grouped by urgency</p>
          </div>
          <span className="text-gray-300 group-hover:text-gray-400 text-lg">→</span>
        </Link>

        <Link
          href="/finance"
          className="flex items-center justify-between bg-white rounded-xl shadow-sm border border-gray-200 p-6 hover:border-gray-300 hover:shadow transition group"
        >
          <div>
            <p className="font-medium text-gray-900 group-hover:text-gray-700">Finance</p>
            <p className="text-sm text-gray-400 mt-0.5">Confirmed expenses, totals by currency</p>
          </div>
          <span className="text-gray-300 group-hover:text-gray-400 text-lg">→</span>
        </Link>

        <Link
          href="/food"
          className="flex items-center justify-between bg-white rounded-xl shadow-sm border border-gray-200 p-6 hover:border-gray-300 hover:shadow transition group"
        >
          <div>
            <p className="font-medium text-gray-900 group-hover:text-gray-700">Food</p>
            <p className="text-sm text-gray-400 mt-0.5">Today&apos;s meals</p>
          </div>
          <span className="text-gray-300 group-hover:text-gray-400 text-lg">→</span>
        </Link>

        <Link
          href="/calendar"
          className="flex items-center justify-between bg-white rounded-xl shadow-sm border border-gray-200 p-6 hover:border-gray-300 hover:shadow transition group"
        >
          <div>
            <p className="font-medium text-gray-900 group-hover:text-gray-700">Calendar</p>
            <p className="text-sm text-gray-400 mt-0.5">Confirmed intentions</p>
          </div>
          <span className="text-gray-300 group-hover:text-gray-400 text-lg">→</span>
        </Link>

        <Link
          href="/review"
          className="flex items-center justify-between bg-white rounded-xl shadow-sm border border-gray-200 p-6 hover:border-gray-300 hover:shadow transition group"
        >
          <div>
            <p className="font-medium text-gray-900 group-hover:text-gray-700">Review</p>
            <p className="text-sm text-gray-400 mt-0.5">Today&apos;s activity summary</p>
          </div>
          <span className="text-gray-300 group-hover:text-gray-400 text-lg">→</span>
        </Link>

        <Link
          href="/portfolio"
          className="flex items-center justify-between bg-white rounded-xl shadow-sm border border-gray-200 p-6 hover:border-gray-300 hover:shadow transition group"
        >
          <div>
            <p className="font-medium text-gray-900 group-hover:text-gray-700">Portfolio</p>
            <p className="text-sm text-gray-400 mt-0.5">Positions across Tiger &amp; IBKR (read-only)</p>
          </div>
          <span className="text-gray-300 group-hover:text-gray-400 text-lg">→</span>
        </Link>

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h2 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-4">
            Pipeline
          </h2>
          <ol className="space-y-2.5">
            {pipeline.map((step, i) => (
              <li key={i} className="flex gap-3 text-sm">
                <span className="text-gray-300 font-mono shrink-0 w-4">{i + 1}.</span>
                <span>
                  <span className={step.active ? "font-medium text-gray-900" : "text-gray-500"}>
                    {step.label}
                  </span>
                  <span className="text-gray-400 ml-1.5">— {step.detail}</span>
                </span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </main>
  );
}
