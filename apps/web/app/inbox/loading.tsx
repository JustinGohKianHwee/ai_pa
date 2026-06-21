export default function InboxLoading() {
  return (
    <main className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <div className="h-8 w-20 bg-gray-200 rounded animate-pulse" />
          <div className="h-4 w-40 bg-gray-100 rounded animate-pulse mt-2" />
        </div>
        <div className="space-y-3">
          {[1, 2, 3].map((n) => (
            <div
              key={n}
              className="bg-white border border-gray-200 rounded-xl p-5 space-y-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="h-5 bg-gray-200 rounded animate-pulse w-2/3" />
                <div className="flex gap-1.5">
                  <div className="h-5 w-16 bg-gray-100 rounded animate-pulse" />
                  <div className="h-5 w-16 bg-gray-100 rounded animate-pulse" />
                </div>
              </div>
              <div className="h-4 bg-gray-100 rounded animate-pulse w-full" />
              <div className="h-4 bg-gray-100 rounded animate-pulse w-3/4" />
              <div className="h-3 bg-gray-100 rounded animate-pulse w-1/3 mt-2" />
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
