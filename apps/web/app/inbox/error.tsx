"use client";

import { PageContainer } from "@/components/ui";

export default function InboxError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <PageContainer>
      <div className="space-y-4 rounded-xl border border-border bg-surface p-8 text-center">
        <p className="font-medium text-negative">Failed to load inbox</p>
        <p className="text-sm text-muted">{error.message}</p>
        <button
          onClick={reset}
          className="mt-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg transition-colors hover:bg-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          Try again
        </button>
      </div>
    </PageContainer>
  );
}
