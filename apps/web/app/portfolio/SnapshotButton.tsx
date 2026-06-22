"use client";

import { useState, useTransition } from "react";
import { snapshotToday } from "./actions";

export function SnapshotButton() {
  const [isPending, startTransition] = useTransition();
  const [message, setMessage] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);

  function createSnapshot() {
    setMessage(null);
    setIsError(false);
    startTransition(async () => {
      const result = await snapshotToday();
      if (result.ok) {
        setMessage(`Saved ${result.snapshotDate ?? "today"}`);
      } else {
        setIsError(true);
        setMessage(result.detail ?? `Failed (${result.status})`);
      }
    });
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={createSnapshot}
        disabled={isPending}
        className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
      >
        {isPending ? "Saving…" : "Snapshot today"}
      </button>
      {message && (
        <span className={`text-xs ${isError ? "text-red-600" : "text-green-700"}`}>
          {message}
        </span>
      )}
    </div>
  );
}
