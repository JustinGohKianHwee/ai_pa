"use client";

export default function InboxError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-2xl mx-auto">
        <div className="bg-white border border-red-200 rounded-xl p-8 text-center space-y-4">
          <p className="font-medium text-red-700">Failed to load inbox</p>
          <p className="text-sm text-gray-500">{error.message}</p>
          <button
            onClick={reset}
            className="mt-2 px-4 py-2 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-700 transition"
          >
            Try again
          </button>
        </div>
      </div>
    </main>
  );
}
