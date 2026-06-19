export default function Home() {
  const pipeline = [
    "Capture (Telegram / voice / web form)",
    "Classify & extract (Claude AI)",
    "Pending inbox — awaiting your review",
    "Review: confirm or reject each item",
    "Confirmed domain record (task, expense, etc.)",
  ];

  const notYetBuilt = [
    "Telegram capture",
    "AI classification",
    "Review inbox",
    "Database schema",
    "Authentication",
  ];

  return (
    <main className="min-h-screen bg-gray-50 flex flex-col items-center justify-center p-8">
      <div className="max-w-lg w-full bg-white rounded-xl shadow-sm border border-gray-200 p-8">
        <div className="mb-6">
          <span className="inline-block bg-amber-100 text-amber-800 text-xs font-medium px-2.5 py-1 rounded-full">
            Phase 1 — Scaffold
          </span>
        </div>

        <h1 className="text-2xl font-semibold text-gray-900 mb-2">
          AI Personal Assistant
        </h1>
        <p className="text-gray-500 mb-8 text-sm">
          Personal operating system scaffold. The dashboard inbox is not yet
          built.
        </p>

        <div className="border-t border-gray-100 pt-6 mb-6">
          <h2 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">
            Core pipeline
          </h2>
          <ol className="space-y-2">
            {pipeline.map((step, i) => (
              <li key={i} className="flex gap-3 text-sm">
                <span className="text-gray-300 font-mono shrink-0 w-4">
                  {i + 1}.
                </span>
                <span
                  className={
                    i === 2 ? "text-gray-900 font-medium" : "text-gray-500"
                  }
                >
                  {step}
                  {i === 2 && (
                    <span className="ml-2 text-xs text-amber-600 font-normal">
                      ← first milestone
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ol>
        </div>

        <div className="border-t border-gray-100 pt-6">
          <h2 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">
            Not yet built
          </h2>
          <ul className="space-y-1">
            {notYetBuilt.map((item) => (
              <li key={item} className="text-sm text-gray-400 flex gap-2">
                <span>·</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </main>
  );
}
