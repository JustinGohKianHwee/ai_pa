"use client";

import { useState, useTransition } from "react";
import { Camera } from "lucide-react";
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
        className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg transition-colors hover:bg-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
      >
        <Camera size={15} aria-hidden />
        {isPending ? "Saving…" : "Snapshot today"}
      </button>
      {message ? (
        <span className={`text-xs ${isError ? "text-negative" : "text-positive"}`}>{message}</span>
      ) : null}
    </div>
  );
}
